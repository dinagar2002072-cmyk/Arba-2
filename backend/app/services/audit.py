"""Audit log and promotion status history writers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.utils import utcnow


def audit(
    db: sqlite3.Connection,
    entity: str,
    entity_id: str,
    action: str,
    user: str,
    before: Any = None,
    after: Any = None,
) -> None:
    db.execute(
        "INSERT INTO audit_log(entity,entity_id,action,user,ts,before_json,after_json) VALUES(?,?,?,?,?,?,?)",
        (
            entity,
            entity_id,
            action,
            user,
            utcnow().isoformat(),
            json.dumps(before, default=str) if before is not None else None,
            json.dumps(after, default=str) if after is not None else None,
        ),
    )


def promotion_snapshot(db: sqlite3.Connection, promotion_id: int) -> dict[str, Any]:
    promotion = db.execute(
        "SELECT description,start_date,end_date,cons_start,cons_end,tactic,"
        "incentive_type,incentive_value,comments,status "
        "FROM promotion WHERE id=?",
        (promotion_id,),
    ).fetchone()
    if promotion is None:
        raise ValueError(f"Promotion {promotion_id} does not exist")
    snapshot = dict(promotion)
    snapshot["products"] = {
        row["p09_code"]: float(row["total_cs"])
        for row in db.execute(
            "SELECT p09_code,total_cs FROM promotion_item WHERE promotion_id=?",
            (promotion_id,),
        )
    }
    return snapshot


def audit_promotion_changes(
    db: sqlite3.Connection,
    promotion_id: int,
    user: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> None:
    if before is None:
        audit(
            db,
            "promotion",
            str(promotion_id),
            "CREATE_ENTRY",
            user,
            after={"change": "Promotion created"},
        )
        return

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
    changes = [
        field_names[field]
        for field in field_names
        if before.get(field) != after.get(field)
    ]
    if changes:
        audit(
            db,
            "promotion",
            str(promotion_id),
            "FIELD_CHANGE",
            user,
            before=before,
            after={"changes": changes},
        )


def log_status(db: sqlite3.Connection, promo_id: int, user: str, old: str | None, new: str) -> None:
    db.execute(
        "INSERT INTO promotion_status_log(promotion_id,ts,user,old_status,new_status) VALUES(?,?,?,?,?)",
        (promo_id, utcnow().isoformat(), user, old, new),
    )
