"""Customer / product master CSV-XLSX parsing and loading."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import HTTPException

from app.config import (
    CUSTOMER_MASTER_SALES_ORG_MARKET_MAP,
    INBOUND_PROCESSED_DIR,
    INBOUND_QUEUE_DIR,
)
from app.db import DB_LOCK, connect
from app.services.audit import audit, log_status, promotion_snapshot
from app.utils import iso_week, utcnow


def master_file_rows(filename: str, contents: bytes) -> list[tuple[int, dict[str, str]]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must use UTF-8 encoding") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("The file must contain a header row")
        return [
            (row_number, {re.sub(r"[^a-z0-9]", "", (key or "").lower()): (value or "").strip()
                          for key, value in row.items() if key})
            for row_number, row in enumerate(reader, start=2)
            if any(value and value.strip() for value in row.values() if value is not None)
        ]
    if suffix != ".xlsx":
        raise ValueError("Upload a CSV or XLSX file")
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 50_000_000:
                raise ValueError("Expanded XLSX file is too large")
            names = set(archive.namelist())
            if "xl/worksheets/sheet1.xml" not in names:
                raise ValueError("The XLSX workbook does not contain Sheet1")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.iter()
                            if node.tag.endswith("}t") or node.tag == "t")
                    for item in shared_root
                ]
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            grid: list[list[str]] = []
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: dict[int, str] = {}
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    cell_ref = cell.attrib.get("r", "")
                    letters = re.match(r"[A-Z]+", cell_ref)
                    if not letters:
                        continue
                    column = 0
                    for character in letters.group():
                        column = column * 26 + ord(character) - 64
                    cell_type = cell.attrib.get("t")
                    value_node = next((part for part in cell if part.tag.endswith("}v")), None)
                    if cell_type == "inlineStr":
                        value = "".join(
                            part.text or ""
                            for part in cell.iter()
                            if part.tag.endswith("}t")
                        )
                    elif value_node is None or value_node.text is None:
                        value = ""
                    elif cell_type == "s":
                        value = shared[int(value_node.text)]
                    else:
                        value = value_node.text
                    values[column - 1] = value.strip()
                if values:
                    grid.append([values.get(index, "") for index in range(max(values) + 1)])
    except (zipfile.BadZipFile, ET.ParseError, IndexError, KeyError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Unable to read the XLSX workbook; export a valid .xlsx file") from exc
    if not grid or not grid[0]:
        raise ValueError("The workbook must contain a header row on its first sheet")
    headers = [re.sub(r"[^a-z0-9]", "", header.lower()) for header in grid[0]]
    return [
        (row_number, dict(zip(headers, values)))
        for row_number, values in enumerate(grid[1:], start=2)
        if any(value for value in values)
    ]


def required_master_value(row: dict[str, str], *headers: str) -> str:
    for header in headers:
        value = row.get(re.sub(r"[^a-z0-9]", "", header.lower()), "")
        if value:
            return value.strip()
    raise ValueError(f"Missing required column/value: {headers[0]}")


def fail_managed_file(file_id: int, message: str) -> None:
    with DB_LOCK, connect() as db:
        db.execute(
            "UPDATE managed_file SET status='FAILED',processed_at=?,message=? WHERE id=?",
            (utcnow().isoformat(), message[:1000], file_id),
        )


def apply_customer_master(db: sqlite3.Connection, data: list[tuple[int, dict[str, str]]]) -> int:
    rows: list[tuple[int, str, str, str, str | None]] = []
    markets = {row["code"] for row in db.execute("SELECT code FROM market WHERE active=1")}
    for row_number, row in data:
        try:
            market = required_master_value(
                row, "Market Code", "Market", "Sales Organization", "Sales Org"
            )
            market = CUSTOMER_MASTER_SALES_ORG_MARKET_MAP.get(market, market)
            if market not in markets:
                market_row = db.execute(
                    "SELECT code FROM market WHERE p10_sales_org=? AND active=1", (market,)
                ).fetchone()
                if market_row:
                    market = str(market_row["code"])
            external_code = required_master_value(
                row,
                "Plan Account Code L04",
                "Plan Account L04",
                "Customer L04",
                "Customer ID",
                "Customer Number",
                "Account Code",
            )
            name = required_master_value(row, "Plan Account Name", "Customer Name", "Name")
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        if market not in markets:
            raise ValueError(f"Row {row_number}: unknown or inactive market {market}")
        parent = next(
            (value for key, value in row.items() if key in {"parentl03", "customerl03", "l03"}),
            "",
        )
        rows.append((row_number, market, external_code, name, parent or None))
    if not rows:
        raise ValueError("The customer master file contains no data rows")
    for _, market, external_code, name, parent in rows:
        existing = db.execute(
            "SELECT id FROM customer_l04 WHERE market_code=? AND "
            "((external_code=? AND name=?) OR (external_code IS NULL AND name=?)) LIMIT 1",
            (market, external_code, name, name),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE customer_l04 SET name=?,parent_l03=?,external_code=?,active=1,source_updated_at=? WHERE id=?",
                (name, parent, external_code, utcnow().isoformat(), existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO customer_l04(market_code,name,parent_l03,external_code,source_updated_at) "
                "VALUES(?,?,?,?,?)",
                (market, name, parent, external_code, utcnow().isoformat()),
            )
    return len(rows)


def ensure_product_hierarchy(db: sqlite3.Connection, code: str, description: str,
                             brand: str, sub_brand: str, category: str) -> str:
    path = [
        brand,
        sub_brand,
        category,
        "All Products",
        "All Products",
        "All Products",
        "All Products",
        "All Products",
        "All Products",
    ]
    parent: str | None = None
    for level, text in enumerate(path, start=1):
        identity = hashlib.sha256(f"{level}|{parent}|{text}".encode()).hexdigest()[:18]
        node_id = f"SAP-P{level}-{identity}"
        db.execute(
            "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET text=excluded.text",
            (node_id, parent, level, text, text),
        )
        parent = node_id
    identity = hashlib.sha256(f"10|{parent}|{code}".encode()).hexdigest()[:18]
    node_id = f"SAP-P10-{identity}"
    db.execute(
        "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,10,?,?) "
        "ON CONFLICT(node_id) DO UPDATE SET parent_id=excluded.parent_id,code=excluded.code,text=excluded.text",
        (node_id, parent, code, description),
    )
    return node_id


def apply_product_master(
    db: sqlite3.Connection,
    data: list[tuple[int, dict[str, str]]],
    user_email: str,
) -> int:
    rows: list[tuple[int, str, str, str, str, str]] = []
    seen_codes: set[str] = set()
    for row_number, row in data:
        try:
            code = required_master_value(
                row,
                "P10 OSKU",
                "Product P10 OSKU",
                "Product OSKU",
                "P10 OSKU Code",
                "OSKU",
                "OSKU Code",
                "Material Number",
            )
            description = required_master_value(row, "Product Description", "Description")
            brand = required_master_value(row, "Brand")
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        sub_brand = next(
            (value for key, value in row.items() if key in {"subbrand", "subbrandname"}),
            "",
        ) or brand
        category = next(
            (value for key, value in row.items() if key in {"category", "productcategory"}),
            "",
        ) or "Uncategorized"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", code):
            raise ValueError(f"Row {row_number}: invalid P10 OSKU code")
        if code in seen_codes:
            raise ValueError(f"Row {row_number}: duplicate P10 OSKU code {code}")
        seen_codes.add(code)
        rows.append((row_number, code, description, brand, sub_brand, category))
    if not rows:
        raise ValueError("The product master file contains no data rows")

    previously_active = {
        row["code"]
        for row in db.execute("SELECT code FROM product_p09 WHERE active=1")
    }
    included_codes = {row[1] for row in rows}
    newly_inactive = previously_active - included_codes
    db.execute("UPDATE product_p09 SET active=0")
    for _, code, description, brand, sub_brand, category in rows:
        node = ensure_product_hierarchy(db, code, description, brand, sub_brand, category)
        db.execute(
            "INSERT INTO product_p09(code,description,brand,sub_brand,category,hierarchy_node_id,active) "
            "VALUES(?,?,?,?,?,?,1) ON CONFLICT(code) DO UPDATE SET description=excluded.description,"
            "brand=excluded.brand,sub_brand=excluded.sub_brand,category=excluded.category,"
            "hierarchy_node_id=excluded.hierarchy_node_id,active=1",
            (code, description, brand, sub_brand, category, node),
        )

    if newly_inactive:
        today = date.today()
        current_week = iso_week(today)
        changed_at = utcnow().isoformat()
        baseline_changes: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for code in sorted(newly_inactive):
            baseline_rows = db.execute(
                "SELECT market_code,customer_id,iso_week,qty_cs FROM baseline "
                "WHERE p09_code=? AND iso_week>=? AND qty_cs<>0",
                (code, current_week),
            ).fetchall()
            for baseline in baseline_rows:
                db.execute(
                    "UPDATE baseline SET qty_cs=0,source='UPLOAD',changed_by=?,changed_at=? "
                    "WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                    (
                        user_email,
                        changed_at,
                        baseline["market_code"],
                        baseline["customer_id"],
                        code,
                        baseline["iso_week"],
                    ),
                )
                baseline_changes.setdefault(
                    (baseline["market_code"], baseline["customer_id"]), []
                ).append(
                    {
                        "product": code,
                        "week": baseline["iso_week"],
                        "old_value": float(baseline["qty_cs"]),
                        "new_value": 0,
                    }
                )
        for (market_code, customer_id), changes in baseline_changes.items():
            audit(
                db,
                "baseline",
                f"{market_code}:{customer_id}",
                "PRODUCT_DEACTIVATION",
                user_email,
                after={"changes": changes},
            )

        affected_promotions: set[int] = set()
        for code in sorted(newly_inactive):
            affected_promotions.update(
                row["promotion_id"]
                for row in db.execute(
                    "SELECT pi.promotion_id FROM promotion_item pi "
                    "JOIN promotion pr ON pr.id=pi.promotion_id "
                    "WHERE pi.p09_code=? AND pr.start_date>?",
                    (code, today.isoformat()),
                )
            )
        for promotion_id in sorted(affected_promotions):
            before = promotion_snapshot(db, promotion_id)
            removed_products = sorted(set(before["products"]) & newly_inactive)
            for code in removed_products:
                db.execute(
                    "DELETE FROM promotion_item WHERE promotion_id=? AND p09_code=?",
                    (promotion_id, code),
                )
            old_status = before["status"]
            db.execute(
                "UPDATE promotion SET status='NEW',approved_by=NULL,approved_at=NULL,"
                "version=version+1 WHERE id=?",
                (promotion_id,),
            )
            if old_status != "NEW":
                log_status(db, promotion_id, user_email, old_status, "NEW")
            after = promotion_snapshot(db, promotion_id)
            audit(
                db,
                "promotion",
                str(promotion_id),
                "PRODUCT_DEACTIVATION",
                user_email,
                before=before,
                after={
                    **after,
                    "removed_products": removed_products,
                    "reason": "Product master extract deactivated products in a future promotion",
                },
            )
    return len(rows)


def process_master_file(file_id: int, user_email: str) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        record = db.execute("SELECT * FROM managed_file WHERE id=?", (file_id,)).fetchone()
        if record is None:
            raise HTTPException(status_code=404, detail="File not found")
        if record["direction"] != "INBOUND" or record["status"] not in {"QUEUED", "FAILED"}:
            raise HTTPException(status_code=409, detail="Only queued or failed inbound files can be processed")
        with db:
            db.execute(
                "UPDATE managed_file SET status='PROCESSING',message=NULL WHERE id=?",
                (file_id,),
            )
        source = Path(record["stored_path"])
        if source.parent.resolve() != INBOUND_QUEUE_DIR.resolve() or not source.is_file():
            raise HTTPException(status_code=404, detail="Queued file is missing from the inbound queue")
        filename = record["original_name"]
        category = record["category"]
        file_bytes = source.read_bytes()
        try:
            data = master_file_rows(filename, file_bytes)
            with db:
                count = (
                    apply_customer_master(db, data)
                    if category == "CUSTOMER_MASTER"
                    else apply_product_master(db, data, user_email)
                )
                db.execute(
                    "UPDATE managed_file SET row_count=?,message=? WHERE id=?",
                    (count, f"Validated and applied {count} rows", file_id),
                )
                audit(db, "master_file", str(file_id), "PROCESS", user_email,
                      after={"category": category, "rows": count})
        except ValueError as exc:
            message = str(exc)
            fail_managed_file(file_id, message)
            raise HTTPException(status_code=422, detail=message) from exc
        except sqlite3.IntegrityError as exc:
            message = "The extract contains a master-data row that conflicts with existing records"
            fail_managed_file(file_id, message)
            raise HTTPException(status_code=422, detail=message) from exc
        destination = INBOUND_PROCESSED_DIR / source.name
        source.replace(destination)
        with db:
            db.execute(
                "UPDATE managed_file SET stored_path=?,status='PROCESSED',processed_at=? WHERE id=?",
                (str(destination), utcnow().isoformat(), file_id),
            )
    return {"id": file_id, "status": "PROCESSED", "rows": count}
