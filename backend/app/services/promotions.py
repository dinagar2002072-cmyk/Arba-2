"""Promotion calculations: baseline over promo weeks, uplift, JSON shape."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, timedelta
from typing import Any

from app.utils import iso_week, week_monday


def promotion_baseline(
    db: sqlite3.Connection,
    market: str,
    customer_id: int,
    product: str,
    start: date,
    end: date,
) -> float:
    cursor = start - timedelta(days=start.weekday())
    final = end - timedelta(days=end.weekday())
    total = 0.0
    while cursor <= final:
        week = iso_week(cursor)
        row = db.execute(
            "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
            (market, customer_id, product, week),
        ).fetchone()
        total += float(row["qty_cs"]) if row else 0.0
        cursor += timedelta(weeks=1)
    return total


def promotion_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    items = []
    for item in db.execute(
        "SELECT pi.p09_code,pi.total_cs,p.description FROM promotion_item pi "
        "JOIN product_p09 p ON p.code=pi.p09_code "
        "JOIN listing l ON l.p09_code=pi.p09_code AND l.market_code=? AND l.customer_id=? "
        "WHERE pi.promotion_id=? ORDER BY p.description",
        (row["market_code"], row["customer_id"], row["id"]),
    ):
        baseline = promotion_baseline(
            db,
            row["market_code"],
            row["customer_id"],
            item["p09_code"],
            date.fromisoformat(row["start_date"]),
            date.fromisoformat(row["end_date"]),
        )
        total = float(item["total_cs"])
        actual = 0.0
        if date.fromisoformat(row["end_date"]) < date.today():
            actual = float(
                db.execute(
                    "SELECT COALESCE(SUM(qty_cs),0) AS q FROM actual_sellin "
                    "WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week BETWEEN ? AND ?",
                    (
                        row["market_code"],
                        row["customer_id"],
                        item["p09_code"],
                        iso_week(date.fromisoformat(row["start_date"])),
                        iso_week(date.fromisoformat(row["end_date"])),
                    ),
                ).fetchone()["q"]
            )
        items.append(
            {
                "product": item["p09_code"],
                "description": item["description"],
                "baseline": baseline,
                "total": total,
                "uplift": total - baseline,
                "actual": actual,
            }
        )
    return {
        **dict(row),
        "incentive_configured": bool(row["incentive_configured"]),
        "items": items,
        "baseline": sum(i["baseline"] for i in items),
        "total": sum(i["total"] for i in items),
        "uplift": sum(i["uplift"] for i in items),
        "actual": sum(i["actual"] for i in items),
    }


def next_promo_number(db: sqlite3.Connection, market_name: str) -> str:
    prefix = "".join(character for character in market_name.upper() if character.isalpha())[:2]
    if len(prefix) != 2:
        raise ValueError("Market name must contain at least two letters for promotion numbering")
    row = db.execute(
        "SELECT MAX(CAST(SUBSTR(promo_number,3) AS INTEGER)) AS n FROM promotion "
        "WHERE SUBSTR(promo_number,1,2)=? "
        "AND LENGTH(promo_number) IN (7,8) "
        "AND SUBSTR(promo_number,3) NOT GLOB '*[^0-9]*'",
        (prefix,),
    ).fetchone()
    sequence = int(row["n"] or 0) + 1
    if sequence > 999_999:
        raise ValueError(f"Promotion number sequence for {prefix} has reached its six-digit limit")
    return f"{prefix}{sequence:06d}"


def approved_uplift(
    db: sqlite3.Connection, market: str, customer: int, product: str, week: str
) -> float:
    monday = week_monday(week)
    sunday = monday + timedelta(days=6)
    total = 0.0
    rows = db.execute(
        "SELECT pr.start_date,pr.end_date,pi.total_cs,m.p10_sales_org AS sales_org "
        "FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id "
        "JOIN market m ON m.code=pr.market_code "
        "WHERE pr.market_code=? AND pr.customer_id=? AND pr.status='APPROVED' AND pi.p09_code=? "
        "AND pr.start_date<=? AND pr.end_date>=?",
        (market, customer, product, sunday.isoformat(), monday.isoformat()),
    )
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        first_monday = start - timedelta(days=start.weekday())
        last_monday = end - timedelta(days=end.weekday())
        week_count = ((last_monday - first_monday).days // 7) + 1
        base = promotion_baseline(db, market, customer, product, start, end)
        uplift = max(0.0, float(row["total_cs"]) - base)
        phase = None
        if week_count in {2, 3, 4}:
            phase = db.execute(
                "SELECT ph.percentages_json FROM promotion_phasing ph "
                "JOIN customer_l04 c ON c.id=ph.customer_id "
                "JOIN market m ON m.code=c.market_code "
                "WHERE m.code=? AND m.p10_sales_org=? AND c.id=? AND ph.sales_org=? "
                "AND ph.duration_weeks=?",
                (market, row["sales_org"], customer, row["sales_org"], week_count),
            ).fetchone()
        if phase:
            percentages = json.loads(phase["percentages_json"])
            if (
                len(percentages) != week_count
                or not all(math.isfinite(value) and value >= 0 for value in percentages)
                or not math.isclose(sum(percentages), 100.0, abs_tol=0.01)
            ):
                raise RuntimeError(
                    f"Invalid {week_count}-week phasing profile for Sales Org "
                    f"{row['sales_org']} and plan account {customer}"
                )
            week_offset = (monday - first_monday).days // 7
            if 0 <= week_offset < week_count:
                total += uplift * percentages[week_offset] / 100
        else:
            total += uplift / week_count
    return total
