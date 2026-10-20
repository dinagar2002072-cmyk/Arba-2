"""P10 Arete weekly feed generation from P10 OSKU planning products."""

from __future__ import annotations

import math
import sqlite3
from datetime import timedelta

from fastapi import HTTPException

from app.services.planning import product_rows_for_account
from app.services.promotions import approved_uplift
from app.utils import future_weeks, week_monday


def build_p10_rows(
    db: sqlite3.Connection, market_code: str, customer_id: int | None = None
) -> list[dict[str, str]]:
    market = db.execute("SELECT * FROM market WHERE code=?", (market_code,)).fetchone()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    result = []
    weeks = future_weeks(int(market["horizon_weeks"]))
    customer_query = (
        "SELECT id,name FROM customer_l04 WHERE market_code=? AND active=1"
    )
    customer_parameters: list[str | int] = [market_code]
    if customer_id is not None:
        customer_query += " AND id=?"
        customer_parameters.append(customer_id)
    customers = db.execute(customer_query, customer_parameters)
    for customer in customers:
        products = product_rows_for_account(db, market_code, customer["id"])
        for product in products:
            for week in weeks:
                base_row = db.execute(
                    "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                    (market_code, customer["id"], product["code"], week),
                ).fetchone()
                base = math.floor(float(base_row["qty_cs"]) + 0.5) if base_row else 0
                lift = math.floor(
                    approved_uplift(db, market_code, customer["id"], product["code"], week) + 0.5
                )
                monday = week_monday(week)
                sunday = monday + timedelta(days=6)
                result.append(
                    {
                        "Start Date": f"{monday.isoformat()} 00:00:00",
                        "End Date": f"{sunday.isoformat()} 00:00:00",
                        "Plan Account": customer["name"],
                        "Material Number": product["code"],
                        "BaseVolume": str(base),
                        "LiftVolume": str(lift),
                        "TotalVolume": str(base + lift),
                        "PromoNumber": f"00{customer['name']}{product['code']}{monday:%Y%m%d}",
                        "Consumption Start": f"{monday.isoformat()} 00:00:00",
                        "Consumption End": f"{sunday.isoformat()} 00:00:00",
                        "Sales Org": market["p10_sales_org"],
                    }
                )
    return result


P10_COLUMNS = (
    "Start Date",
    "End Date",
    "Plan Account",
    "Material Number",
    "BaseVolume",
    "LiftVolume",
    "TotalVolume",
    "PromoNumber",
    "Consumption Start",
    "Consumption End",
    "Sales Org",
)
