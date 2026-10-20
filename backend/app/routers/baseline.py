"""Weekly Baseline Volume: baseline grid, XLSX export/upload."""

from __future__ import annotations

import base64
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, check_assignment, require_permission
from app.schemas import BaselineFileUpload, BaselineSave
from app.services.audit import audit
from app.services.master_data import master_file_rows
from app.services.planning import product_rows_for_account
from app.services.xlsx import build_xlsx
from app.utils import future_weeks, iso_week, utcnow, week_monday

router = APIRouter(tags=['baseline'])


@router.get(f"{API_PREFIX}/baseline")
async def get_baseline(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    require_permission(user, "weekly", "view")
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        rows = product_rows_for_account(db, market, customer_id)
        weeks = future_weeks(int(market_row["horizon_weeks"]))
        result = []
        for product in rows:
            baseline = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            actual = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            result.append(
                {
                    **dict(product),
                    "baseline": [baseline.get(w, 0) for w in weeks],
                    "actual_last_year": [
                        actual.get(iso_week(week_monday(w) - timedelta(weeks=52)), 0) for w in weeks
                    ],
                }
            )
    return {
        "market": market,
        "customer_id": customer_id,
        "plan_mode": market_row["plan_mode"],
        "weeks": weeks,
        "products": result,
    }


@router.put(f"{API_PREFIX}/baseline")
async def save_baseline(payload: BaselineSave, user: CurrentUser) -> dict[str, Any]:
    require_permission(user, "weekly", "edit")
    if not payload.cells:
        return {"saved": 0}
    with DB_LOCK, connect() as db:
        with db:
            market_row = db.execute(
                "SELECT plan_mode,horizon_weeks FROM market WHERE code=?",
                (payload.market,),
            ).fetchone()
            if market_row is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            weeks = set(future_weeks(int(market_row["horizon_weeks"])))
            listed = {
                row["p09_code"]
                for row in db.execute(
                    "SELECT l.p09_code FROM listing l JOIN product_p09 p ON p.code=l.p09_code "
                    "AND p.active=1 WHERE l.market_code=? AND l.customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            unique: set[tuple[str, str]] = set()
            values = []
            for cell in payload.cells:
                if not math.isfinite(cell.qty_cs):
                    raise HTTPException(
                        status_code=422, detail="Baseline values must be finite numbers"
                    )
                try:
                    week_monday(cell.week)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if cell.week not in weeks:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Past or out-of-horizon week is locked: {cell.week}",
                    )
                if cell.product not in listed:
                    raise HTTPException(
                        status_code=400, detail=f"Product is not listed: {cell.product}"
                    )
                key = (cell.product, cell.week)
                if key in unique:
                    raise HTTPException(
                        status_code=422,
                        detail="Duplicate product/week cells in request",
                    )
                unique.add(key)
                values.append(
                    (
                        payload.market,
                        payload.customer_id,
                        cell.product,
                        cell.week,
                        cell.qty_cs,
                        "MANUAL",
                        user["email"],
                        utcnow().isoformat(),
                    )
                )
            existing = {
                (row["p09_code"], row["iso_week"]): float(row["qty_cs"])
                for row in db.execute(
                    "SELECT p09_code,iso_week,qty_cs FROM baseline "
                    "WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            changes = [
                {
                    "product": value[2],
                    "week": value[3],
                    "old_value": existing.get((value[2], value[3])),
                    "new_value": float(value[4]),
                }
                for value in values
                if existing.get((value[2], value[3])) != float(value[4])
            ]
            db.executemany(
                "INSERT INTO baseline(market_code,customer_id,p09_code,iso_week,qty_cs,source,changed_by,changed_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(market_code,customer_id,p09_code,iso_week) "
                "DO UPDATE SET qty_cs=excluded.qty_cs,source=excluded.source,changed_by=excluded.changed_by,changed_at=excluded.changed_at",
                values,
            )
            if changes:
                audit(
                    db,
                    "baseline",
                    f"{payload.market}:{payload.customer_id}",
                    "BULK_UPSERT",
                    user["email"],
                    after={"changes": changes},
                )
    return {"saved": len(values)}


@router.get(f"{API_PREFIX}/baseline/audit/export")
async def export_baseline_audit(
    market: str,
    customer_id: int,
    user: CurrentUser,
) -> Response:
    require_permission(user, "weekly", "export")
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        customer = db.execute(
            "SELECT name FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
            (market, customer_id),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Plan account not found")
        audit_rows = db.execute(
            "SELECT ts,user,action,after_json FROM audit_log "
            "WHERE entity='baseline' AND entity_id=? ORDER BY id DESC",
            (f"{market}:{customer_id}",),
        ).fetchall()
        rows: list[dict[str, str]] = []
        for entry in audit_rows:
            timestamp = datetime.fromisoformat(entry["ts"]).strftime("%d%m%Y %H:%M:%S")
            details = json.loads(entry["after_json"] or "{}")
            changes = details.get("changes", [])
            if changes:
                for change in reversed(changes):
                    rows.append(
                        {
                            "Plan Account": customer["name"],
                            "Product (P10 OSKU)": change["product"],
                            "Week": change["week"],
                            "Previous Forecast": "" if change["old_value"] is None else str(change["old_value"]),
                            "New Forecast": str(change["new_value"]),
                            "Change": "Baseline forecast changed",
                            "User ID": entry["user"],
                            "Time Stamp": timestamp,
                        }
                    )
            elif details.get("cells"):
                rows.append(
                    {
                        "Plan Account": customer["name"],
                        "Product (P10 OSKU)": "",
                        "Week": "",
                        "Previous Forecast": "",
                        "New Forecast": "",
                        "Change": f"Baseline updated ({details['cells']} cells; legacy audit summary)",
                        "User ID": entry["user"],
                        "Time Stamp": timestamp,
                    }
                )
    columns = (
        "Plan Account",
        "Product (P10 OSKU)",
        "Week",
        "Previous Forecast",
        "New Forecast",
        "Change",
        "User ID",
        "Time Stamp",
    )
    return Response(
        build_xlsx(rows, columns),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="baseline_audit_{market}_{customer_id}.xlsx"'
        },
    )


@router.get(f"{API_PREFIX}/baseline/export")
async def export_baseline(
    market: str,
    customer_id: int,
    user: CurrentUser,
    weeks: list[str] | None = Query(default=None),
) -> Response:
    require_permission(user, "weekly", "export")
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        customer = db.execute(
            "SELECT id,name FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
            (market, customer_id),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Plan account not found")
        available_weeks = future_weeks(int(market_row["horizon_weeks"]))
        if weeks is None:
            export_weeks = available_weeks
        elif len(set(weeks)) != len(weeks) or not set(weeks).issubset(available_weeks):
            raise HTTPException(status_code=422, detail="Export weeks must be unique future weeks in the current planning horizon")
        else:
            export_weeks = weeks
        products = [
            product for product in product_rows_for_account(db, market, customer_id)
            if product["active"]
        ]
        rows = []
        for product in products:
            baseline_by_week = {
                row["iso_week"]: float(row["qty_cs"])
                for row in db.execute(
                    "SELECT iso_week,qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            rows.append(
                {
                    "Plan Account": customer["name"],
                    "Product": product["code"],
                    **{
                        f"Week {week.split('-W')[1]} {week.split('-W')[0]}":
                        str(baseline_by_week.get(week, 0))
                        for week in export_weeks
                    },
                }
            )
    columns = (
        "Plan Account",
        "Product",
        *(f"Week {week.split('-W')[1]} {week.split('-W')[0]}" for week in export_weeks),
    )
    filename = f"baseline_{market}_{customer_id}.xlsx"
    return Response(
        build_xlsx(rows, columns),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(f"{API_PREFIX}/baseline/upload")
async def upload_baseline(payload: BaselineFileUpload, user: CurrentUser) -> dict[str, int]:
    require_permission(user, "weekly", "import")
    if Path(payload.filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail="Upload a baseline XLSX workbook")
    try:
        contents = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The upload is not valid base64 data") from exc
    if not contents or len(contents) > 10_000_000:
        raise HTTPException(status_code=413, detail="Baseline workbook must be between 1 byte and 10 MB")
    try:
        rows = master_file_rows(payload.filename, contents)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not rows or len(rows) > 20_000:
        raise HTTPException(status_code=422, detail="Baseline workbook must contain between 1 and 20,000 data rows")

    with DB_LOCK, connect() as db:
        with db:
            market_row = db.execute(
                "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (payload.market,)
            ).fetchone()
            if market_row is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            customer = db.execute(
                "SELECT id,name FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
                (payload.market, payload.customer_id),
            ).fetchone()
            if customer is None:
                raise HTTPException(status_code=404, detail="Plan account not found")
            weeks = set(future_weeks(int(market_row["horizon_weeks"])))
            listed = {
                row["code"]
                for row in product_rows_for_account(db, payload.market, payload.customer_id)
                if row["active"]
            }
            first_row = rows[0][1]
            header_order = list(first_row)
            header_keys = set(header_order)
            errors: list[str] = []
            omitted_errors = 0

            def add_error(message: str) -> None:
                nonlocal omitted_errors
                if len(errors) < 100:
                    errors.append(message)
                else:
                    omitted_errors += 1

            for required in ("planaccount", "product"):
                if required not in header_keys:
                    label = "Plan Account" if required == "planaccount" else "Product"
                    add_error(f"Header: missing required column '{label}'")
            if header_order[:2] != ["planaccount", "product"]:
                add_error("Header: columns must start with 'Plan Account' and 'Product'")

            week_columns: dict[str, str] = {}
            for key in header_order:
                if key in {"planaccount", "product"}:
                    continue
                match = re.fullmatch(r"week(\d{1,2})(\d{4})", key)
                if not match:
                    add_error(f"Header: unsupported column '{key}'")
                    continue
                week_number, year = int(match.group(1)), int(match.group(2))
                week = f"{year}-W{week_number:02d}"
                try:
                    week_monday(week)
                except ValueError:
                    add_error(f"Header: '{key}' is not a valid ISO week")
                    continue
                if week not in weeks:
                    add_error(f"Header: {key} is outside the current future planning horizon")
                    continue
                if week in week_columns:
                    add_error(f"Header: duplicate column for ISO week {week}")
                    continue
                week_columns[week] = key
            if not week_columns:
                add_error("Header: include at least one future week column, such as 'Week 43 2026'")

            unique_products: set[str] = set()
            values = []
            for row_number, row in rows:
                account = row.get("planaccount", "").strip()
                product = row.get("product", "").strip()
                if not account:
                    add_error(f"Row {row_number}, Plan Account: value is required")
                elif account != customer["name"]:
                    add_error(
                        f"Row {row_number}, Plan Account: '{account}' does not match the selected plan account '{customer['name']}'"
                    )
                if not product:
                    add_error(f"Row {row_number}, Product: P10 OSKU is required")
                elif product not in listed:
                    add_error(
                        f"Row {row_number}, Product: '{product}' is not a listed P10 OSKU for plan account '{customer['name']}'"
                    )
                elif product in unique_products:
                    add_error(f"Row {row_number}, Product: duplicate P10 OSKU '{product}'")
                else:
                    unique_products.add(product)
                for week, column in week_columns.items():
                    quantity_text = row.get(column, "").strip()
                    header = f"Week {week.split('-W')[1]} {week.split('-W')[0]}"
                    if not quantity_text:
                        add_error(f"Row {row_number}, {header}: forecast value is required")
                        continue
                    try:
                        quantity = float(quantity_text)
                    except (ValueError, OverflowError):
                        add_error(f"Row {row_number}, {header}: '{quantity_text}' is not a valid number")
                        continue
                    if not math.isfinite(quantity) or quantity < 0 or quantity > 1_000_000_000:
                        add_error(f"Row {row_number}, {header}: forecast must be between 0 and 1,000,000,000")
                        continue
                    if account == customer["name"] and product in listed:
                        values.append(
                            (
                                payload.market,
                                payload.customer_id,
                                product,
                                week,
                                quantity,
                                "UPLOAD",
                                user["email"],
                                utcnow().isoformat(),
                            )
                        )
            if errors:
                if omitted_errors:
                    errors.append(f"{omitted_errors} additional validation findings omitted")
                raise HTTPException(
                    status_code=422,
                    detail="Invalid baseline workbook:\n- " + "\n- ".join(errors),
                )
            if not values:
                raise HTTPException(status_code=422, detail="The workbook contains no forecast values to load")
            existing = {
                (row["p09_code"], row["iso_week"]): float(row["qty_cs"])
                for row in db.execute(
                    "SELECT p09_code,iso_week,qty_cs FROM baseline "
                    "WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            changes = [
                {
                    "product": value[2],
                    "week": value[3],
                    "old_value": existing.get((value[2], value[3])),
                    "new_value": float(value[4]),
                }
                for value in values
                if existing.get((value[2], value[3])) != float(value[4])
            ]
            db.executemany(
                "INSERT INTO baseline(market_code,customer_id,p09_code,iso_week,qty_cs,source,changed_by,changed_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(market_code,customer_id,p09_code,iso_week) "
                "DO UPDATE SET qty_cs=excluded.qty_cs,source=excluded.source,"
                "changed_by=excluded.changed_by,changed_at=excluded.changed_at",
                values,
            )
            if changes:
                audit(
                    db,
                    "baseline",
                    f"{payload.market}:{payload.customer_id}",
                    "UPLOAD",
                    user["email"],
                    after={
                        "changes": changes,
                        "filename": Path(payload.filename).name,
                    },
                )
    return {"saved": len(values)}
