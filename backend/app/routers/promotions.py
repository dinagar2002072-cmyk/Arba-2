"""Promotions screen: create/edit and workflow (save, confirm, approve, revert)."""

from __future__ import annotations

import math
import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, check_assignment, require_role
from app.schemas import PromoPayload, PromotionCopyPayload
from app.services.audit import (
    audit,
    audit_promotion_changes,
    log_status,
    promotion_snapshot,
)
from app.services.promotions import (
    next_promo_number,
    promotion_baseline,
    promotion_json,
)
from app.utils import utcnow

router = APIRouter(tags=['promotions'])


@router.get(f"{API_PREFIX}/promotions/baseline")
async def promotion_baselines(
    market: str,
    customer_id: int,
    start_date: date,
    end_date: date,
    user: CurrentUser,
) -> dict[str, Any]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="End Date must be on or after Start Date")
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        rows = db.execute(
            "SELECT p.code FROM listing l JOIN product_p09 p ON p.code=l.p09_code "
            "WHERE l.market_code=? AND l.customer_id=? AND p.active=1 ORDER BY p.description",
            (market, customer_id),
        ).fetchall()
        baselines = {
            row["code"]: promotion_baseline(
                db, market, customer_id, row["code"], start_date, end_date
            )
            for row in rows
        }
    return {"baselines": baselines}


@router.get(f"{API_PREFIX}/promotions")
async def get_promotions(
    user: CurrentUser, market: str | None = None, customer_id: int | None = None
) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        query = (
            "SELECT pr.*,c.name AS customer_name FROM promotion pr "
            "JOIN customer_l04 c ON c.id=pr.customer_id AND c.active=1 "
            "WHERE (NOT EXISTS (SELECT 1 FROM promotion_item empty_item "
            "WHERE empty_item.promotion_id=pr.id) OR EXISTS ("
            "SELECT 1 FROM promotion_item pi JOIN listing l "
            "ON l.market_code=pr.market_code AND l.customer_id=pr.customer_id "
            "AND l.p09_code=pi.p09_code WHERE pi.promotion_id=pr.id))"
        )
        parameters: list[Any] = []
        if market:
            query += " AND pr.market_code=?"
            parameters.append(market)
        if customer_id:
            query += " AND pr.customer_id=?"
            parameters.append(customer_id)
        if user["role"] != "ADMIN":
            query += " AND EXISTS(SELECT 1 FROM user_assignment ua WHERE ua.user_id=? AND ua.market_code=pr.market_code AND ua.customer_id=pr.customer_id)"
            parameters.append(user["id"])
        rows = db.execute(
            query + " ORDER BY pr.start_date DESC,pr.promo_number DESC", parameters
        ).fetchall()
        promos = [promotion_json(db, row) for row in rows]
    return {"promotions": promos}


@router.get(f"{API_PREFIX}/promotions/{{promotion_id}}/audit")
async def promotion_audit(promotion_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        promotion = db.execute(
            "SELECT market_code,customer_id FROM promotion WHERE id=?",
            (promotion_id,),
        ).fetchone()
        if promotion is None:
            raise HTTPException(status_code=404, detail="Promotion not found")
        check_assignment(db, user, promotion["market_code"], int(promotion["customer_id"]))
        entries = db.execute(
            "SELECT action,user,ts,before_json,after_json FROM audit_log "
            "WHERE entity='promotion' AND entity_id=? ORDER BY id DESC",
            (str(promotion_id),),
        ).fetchall()
        changes: list[dict[str, str]] = []
        for entry in entries:
            before = json.loads(entry["before_json"] or "{}")
            after = json.loads(entry["after_json"] or "{}")
            timestamp = datetime.fromisoformat(entry["ts"]).strftime("%d%m%Y %H:%M:%S")
            if entry["action"] == "FIELD_CHANGE":
                descriptions = after.get("changes", [])
            elif entry["action"] == "CREATE_ENTRY":
                descriptions = [after.get("change", "Promotion created")]
            elif entry["action"] == "COPY_ENTRY":
                descriptions = ["Promotion copied"]
            elif entry["action"] == "EDIT":
                field_names = {
                    "description": "Promotion Description",
                    "start_date": "Start Date",
                    "end_date": "End Date",
                    "cons_start": "Consumption Start Date",
                    "cons_end": "Consumption End Date",
                    "tactic": "Tactic",
                    "incentive_type": "Incentive Type",
                    "incentive_value": "Incentive Amount / Percentage",
                    "comments": "Comments",
                    "products": "Products / Volumes",
                }
                descriptions = [
                    field_names[field] for field in field_names if field in after
                ] or ["Promotion updated"]
            elif "status" in before and "status" in after:
                descriptions = [f"Status: {before['status']} -> {after['status']}"]
            else:
                descriptions = [entry["action"].replace("_", " ").title()]
            changes.extend(
                {
                    "change": description,
                    "user_id": entry["user"],
                    "time_stamp": timestamp,
                }
                for description in descriptions
            )
    return {"changes": changes}


@router.post(f"{API_PREFIX}/promotions/copy")
async def copy_promotions(payload: PromotionCopyPayload, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "PLANNER", "APPROVER")
    if len(set(payload.promotion_ids)) != len(payload.promotion_ids):
        raise HTTPException(status_code=422, detail="Select each promotion only once")

    def next_year(value: str) -> str:
        original = date.fromisoformat(value)
        try:
            return original.replace(year=original.year + 1).isoformat()
        except ValueError:
            return original.replace(year=original.year + 1, day=28).isoformat()

    with DB_LOCK, connect() as db:
        with db:
            created = []
            for source_id in payload.promotion_ids:
                source = db.execute(
                    "SELECT pr.*,m.name AS market_name FROM promotion pr "
                    "JOIN market m ON m.code=pr.market_code "
                    "WHERE pr.id=? AND pr.market_code=? AND pr.customer_id=? "
                    "AND EXISTS (SELECT 1 FROM promotion_item pi "
                    "JOIN product_p09 p ON p.code=pi.p09_code AND p.active=1 "
                    "JOIN listing l ON l.market_code=pr.market_code AND l.customer_id=pr.customer_id "
                    "AND l.p09_code=pi.p09_code WHERE pi.promotion_id=pr.id)",
                    (source_id, payload.market, payload.customer_id),
                ).fetchone()
                if source is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Promotion {source_id} was not found for this plan account",
                    )
                check_assignment(db, user, source["market_code"], int(source["customer_id"]))
                promo_number = next_promo_number(db, source["market_name"])
                cursor = db.execute(
                    "INSERT INTO promotion(promo_number,market_code,customer_id,start_date,end_date,"
                    "cons_start,cons_end,description,comments,tactic,incentive_type,incentive_value,"
                    "incentive_configured,status,created_by,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        promo_number,
                        source["market_code"],
                        source["customer_id"],
                        next_year(source["start_date"]),
                        next_year(source["end_date"]),
                        next_year(source["cons_start"]),
                        next_year(source["cons_end"]),
                        source["description"],
                        source["comments"],
                        source["tactic"],
                        source["incentive_type"],
                        source["incentive_value"],
                        source["incentive_configured"],
                        "NEW",
                        user["email"],
                        utcnow().isoformat(),
                    ),
                )
                new_id = int(cursor.lastrowid)
                items = db.execute(
                    "SELECT pi.p09_code,pi.total_cs FROM promotion_item pi "
                    "JOIN product_p09 p ON p.code=pi.p09_code AND p.active=1 "
                    "JOIN listing l ON l.market_code=? AND l.customer_id=? AND l.p09_code=pi.p09_code "
                    "WHERE pi.promotion_id=?",
                    (payload.market, payload.customer_id, source_id),
                ).fetchall()
                db.executemany(
                    "INSERT INTO promotion_item(promotion_id,p09_code,total_cs) VALUES(?,?,?)",
                    [(new_id, item["p09_code"], item["total_cs"]) for item in items],
                )
                log_status(db, new_id, user["email"], None, "NEW")
                audit(
                    db,
                    "promotion",
                    str(new_id),
                    "COPY_ENTRY",
                    user["email"],
                    before={"source_promotion": source_id},
                    after={"status": "NEW", "source_promotion": source_id},
                )
                created.append(
                    promotion_json(
                        db,
                        db.execute("SELECT * FROM promotion WHERE id=?", (new_id,)).fetchone(),
                    )
                )
    return {"promotions": created}


@router.post(f"{API_PREFIX}/promotions")
async def save_promotion(payload: PromoPayload, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "PLANNER", "APPROVER")
    if payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=422, detail="Promotion End Date must be on or after Start Date"
        )
    if payload.cons_end < payload.cons_start:
        raise HTTPException(
            status_code=422,
            detail="Consumption End must be on or after Consumption Start",
        )
    if not payload.items:
        raise HTTPException(status_code=422, detail="Select at least one promotion product")
    with DB_LOCK, connect() as db:
        with db:
            market = db.execute(
                "SELECT name,plan_mode FROM market WHERE code=?", (payload.market,)
            ).fetchone()
            if market is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            tactic = db.execute(
                "SELECT incentive_type FROM tactic WHERE market_code=? AND name=? AND active=1",
                (payload.market, payload.tactic),
            ).fetchone()
            if not tactic:
                raise HTTPException(
                    status_code=422, detail="Tactic is not configured for this market"
                )
            if tactic["incentive_type"] == "VARIABLE" and payload.incentive_value > 100:
                raise HTTPException(
                    status_code=422,
                    detail="Percentage per case must be between 0 and 100",
                )
            listed = {
                r["p09_code"]
                for r in db.execute(
                    "SELECT l.p09_code FROM listing l JOIN product_p09 p ON p.code=l.p09_code "
                    "AND p.active=1 WHERE l.market_code=? AND l.customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            if payload.id is not None and payload.start_date <= date.today():
                listed.update(
                    row["p09_code"]
                    for row in db.execute(
                        "SELECT pi.p09_code FROM promotion_item pi "
                        "JOIN promotion pr ON pr.id=pi.promotion_id "
                        "JOIN product_p09 p ON p.code=pi.p09_code "
                        "WHERE pr.id=? AND pr.market_code=? AND pr.customer_id=? "
                        "AND pr.start_date<=? AND p.active=0",
                        (
                            payload.id,
                            payload.market,
                            payload.customer_id,
                            date.today().isoformat(),
                        ),
                    )
                )
            if not set(payload.items).issubset(listed):
                raise HTTPException(
                    status_code=400,
                    detail="Every promotion product must be listed for this account",
                )
            for product, total in payload.items.items():
                if not math.isfinite(total) or total < 0:
                    raise HTTPException(status_code=422, detail="Item totals must be non-negative")
                baseline = promotion_baseline(
                    db,
                    payload.market,
                    payload.customer_id,
                    product,
                    payload.start_date,
                    payload.end_date,
                )
                if total < baseline:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Total cases for {product} must be at least its baseline ({baseline:g})",
                    )

            if payload.id is None:
                before_snapshot = None
                promo_number = next_promo_number(db, market["name"])
                cursor = db.execute(
                    "INSERT INTO promotion(promo_number,market_code,customer_id,start_date,end_date,cons_start,cons_end,"
                    "description,comments,tactic,incentive_type,incentive_value,incentive_configured,"
                    "status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        promo_number,
                        payload.market,
                        payload.customer_id,
                        payload.start_date.isoformat(),
                        payload.end_date.isoformat(),
                        payload.cons_start.isoformat(),
                        payload.cons_end.isoformat(),
                        payload.description.strip(),
                        payload.comments.strip(),
                        payload.tactic,
                        tactic["incentive_type"],
                        payload.incentive_value,
                        1,
                        "NEW",
                        user["email"],
                        utcnow().isoformat(),
                    ),
                )
                promo_id = int(cursor.lastrowid)
                log_status(db, promo_id, user["email"], None, "NEW")
            else:
                row = db.execute("SELECT * FROM promotion WHERE id=?", (payload.id,)).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="Promotion not found")
                check_assignment(db, user, row["market_code"], int(row["customer_id"]))
                if row["status"] not in {"NEW", "SAVED"}:
                    raise HTTPException(
                        status_code=409,
                        detail="Only Entry or Planned promotions can be edited; revert an approved promotion first.",
                    )
                if payload.version is None or payload.version != row["version"]:
                    raise HTTPException(
                        status_code=409,
                        detail="Promotion was changed by another user. Reload before saving.",
                    )
                promo_id = int(row["id"])
                before_snapshot = promotion_snapshot(db, promo_id)
                cursor = db.execute(
                    "UPDATE promotion SET market_code=?,customer_id=?,start_date=?,end_date=?,cons_start=?,cons_end=?,"
                    "description=?,comments=?,tactic=?,incentive_type=?,incentive_value=?,"
                    "incentive_configured=1,version=version+1 WHERE id=? AND version=?",
                    (
                        payload.market,
                        payload.customer_id,
                        payload.start_date.isoformat(),
                        payload.end_date.isoformat(),
                        payload.cons_start.isoformat(),
                        payload.cons_end.isoformat(),
                        payload.description.strip(),
                        payload.comments.strip(),
                        payload.tactic,
                        tactic["incentive_type"],
                        payload.incentive_value,
                        promo_id,
                        row["version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise HTTPException(
                        status_code=409, detail="Promotion was changed by another user"
                    )
            warnings = db.execute(
                "SELECT DISTINCT pr.promo_number FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id "
                "WHERE pr.market_code=? AND pr.customer_id=? AND pr.id<>? "
                "AND pr.start_date<=? AND pr.end_date>=? AND pi.p09_code IN ({})".format(
                    ",".join("?" for _ in payload.items)
                ),
                (
                    payload.market,
                    payload.customer_id,
                    promo_id,
                    payload.end_date.isoformat(),
                    payload.start_date.isoformat(),
                    *payload.items.keys(),
                ),
            ).fetchall()
            db.execute("DELETE FROM promotion_item WHERE promotion_id=?", (promo_id,))
            db.executemany(
                "INSERT INTO promotion_item(promotion_id,p09_code,total_cs) VALUES(?,?,?)",
                [(promo_id, product, total) for product, total in payload.items.items()],
            )
            audit_promotion_changes(
                db,
                promo_id,
                user["email"],
                before_snapshot,
                promotion_snapshot(db, promo_id),
            )
            result = promotion_json(
                db,
                db.execute("SELECT * FROM promotion WHERE id=?", (promo_id,)).fetchone(),
            )
    return {
        "promotion": result,
        "overlap_warnings": [r["promo_number"] for r in warnings],
    }


@router.post(f"{API_PREFIX}/promotions/{{promotion_id}}/save")
async def plan_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "NEW":
                raise HTTPException(status_code=409, detail="Only Entry promotions can be saved as Planned")
            db.execute(
                "UPDATE promotion SET status='SAVED',version=version+1 WHERE id=? AND status='NEW'",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "NEW", "SAVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "SAVE",
                user["email"],
                before={"status": "NEW"},
                after={"status": "SAVED"},
            )
    return {"status": "SAVED"}


@router.post(f"{API_PREFIX}/promotions/{{promotion_id}}/confirm")
async def confirm_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "SAVED":
                raise HTTPException(status_code=409, detail="Only Planned promotions can be confirmed")
            db.execute(
                "UPDATE promotion SET status='CHANGED',version=version+1 WHERE id=? AND status='SAVED'",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "SAVED", "CHANGED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "CONFIRM",
                user["email"],
                before={"status": "SAVED"},
                after={"status": "CHANGED"},
            )
    return {"status": "CHANGED"}


@router.post(f"{API_PREFIX}/promotions/{{promotion_id}}/approve")
async def approve_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "CHANGED":
                raise HTTPException(status_code=409, detail="Only Approval Pending promotions can be approved")
            db.execute(
                "UPDATE promotion SET status='APPROVED',approved_by=?,approved_at=?,version=version+1 "
                "WHERE id=? AND status='CHANGED'",
                (user["email"], utcnow().isoformat(), promotion_id),
            )
            log_status(db, promotion_id, user["email"], "CHANGED", "APPROVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "APPROVE",
                user["email"],
                before={"status": "CHANGED"},
                after={"status": "APPROVED"},
            )
    return {"status": "APPROVED"}


@router.post(f"{API_PREFIX}/promotions/{{promotion_id}}/revert")
async def revert_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "APPROVED" or date.fromisoformat(row["start_date"]) <= date.today():
                raise HTTPException(
                    status_code=409,
                    detail="Only future APPROVED promotions can be reverted",
                )
            db.execute(
                "UPDATE promotion SET status='SAVED',approved_by=NULL,approved_at=NULL,version=version+1 WHERE id=?",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "APPROVED", "SAVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "REVERT",
                user["email"],
                before={"status": "APPROVED"},
                after={"status": "SAVED"},
            )
    return {"status": "SAVED"}
