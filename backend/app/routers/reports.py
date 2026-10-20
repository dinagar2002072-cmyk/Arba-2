"""Sales Data, Volume Report and Promo Calendar screens."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, check_assignment
from app.services.p10_feed import build_p10_rows
from app.services.planning import product_rows_for_account
from app.services.promotions import approved_uplift
from app.services.xlsx import build_xlsx
from app.utils import future_weeks, historical_weeks, iso_week, week_monday

router = APIRouter(tags=['reports'])


@router.get(f"{API_PREFIX}/history")
async def sales_history(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    first_year = today.year - 2
    last_year = today.year + 1
    week = date(first_year, 1, 1) - timedelta(days=date(first_year, 1, 1).weekday())
    last_monday = date(last_year, 12, 31) - timedelta(
        days=date(last_year, 12, 31).weekday()
    )
    weeks: list[str] = []
    while week <= last_monday:
        thursday = week + timedelta(days=3)
        if first_year <= thursday.year <= last_year:
            weeks.append(iso_week(week))
        week += timedelta(weeks=1)

    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        products = product_rows_for_account(db, market, customer_id)
        result = []
        for product in products:
            actual_lookup = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            baseline_lookup = {
                r["iso_week"]: float(r["qty_cs"])
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM baseline "
                    "WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            values = []
            for iso_week_value in weeks:
                monday = week_monday(iso_week_value)
                if monday < current_monday:
                    values.append(float(actual_lookup.get(iso_week_value, 0)))
                else:
                    values.append(
                        baseline_lookup.get(iso_week_value, 0)
                        + approved_uplift(
                            db,
                            market,
                            customer_id,
                            product["code"],
                            iso_week_value,
                        )
                    )
            result.append({**dict(product), "values": values})
    return {
        "weeks": weeks,
        "forecast_from": iso_week(current_monday),
        "products": result,
    }


@router.get(f"{API_PREFIX}/history/p10-export")
async def export_p10_arete_data(
    market: str, customer_id: int, user: CurrentUser
) -> Response:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        customer = db.execute(
            "SELECT name FROM customer_l04 "
            "WHERE market_code=? AND id=? AND active=1",
            (market, customer_id),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Plan account not found")
        feed_rows = build_p10_rows(db, market, customer_id)
        rows = [
            {
                "Start Date": entry["Start Date"][:10],
                "End Date": entry["End Date"][:10],
                "Week Number": str(
                    date.fromisoformat(entry["Start Date"][:10]).isocalendar().week
                ),
                "Plan Account": entry["Plan Account"],
                "Material Number": entry["Material Number"],
                "Base Volume": entry["BaseVolume"],
                "Uplift Volume": entry["LiftVolume"],
                "Total Volume": entry["TotalVolume"],
                "Sales Organization": entry["Sales Org"],
            }
            for entry in feed_rows
        ]
    columns = (
        "Start Date",
        "End Date",
        "Week Number",
        "Plan Account",
        "Material Number",
        "Base Volume",
        "Uplift Volume",
        "Total Volume",
        "Sales Organization",
    )
    return Response(
        build_xlsx(rows, columns),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="p10_arete_{market}_{customer_id}.xlsx"'
            )
        },
    )


@router.get(f"{API_PREFIX}/report")
async def volume_report(
    user: CurrentUser, market: str, year: int, customer_id: int | None = None
) -> dict[str, Any]:
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=422, detail="Year must be between 2000 and 2100")
    with DB_LOCK, connect() as db:
        market_row = db.execute("SELECT plan_mode FROM market WHERE code=?", (market,)).fetchone()
        if not market_row:
            raise HTTPException(status_code=404, detail="Market not found")
        if customer_id:
            check_assignment(db, user, market, customer_id)
        else:
            assigned = {
                r["customer_id"]
                for r in db.execute(
                    "SELECT customer_id FROM user_assignment WHERE user_id=? AND market_code=?",
                    (user["id"], market),
                )
            }
            if user["role"] != "ADMIN" and not assigned:
                raise HTTPException(status_code=403, detail="Market is not assigned")
        params: list[Any] = [market]
        query = "SELECT id,name FROM customer_l04 WHERE market_code=? AND active=1"
        if customer_id:
            query += " AND id=?"
            params.append(customer_id)
        elif user["role"] != "ADMIN":
            marks = ",".join("?" for _ in assigned)
            query += f" AND id IN ({marks})"
            params.extend(sorted(assigned))
        customers = db.execute(query, params).fetchall()
        results = []
        for customer in customers:
            products = product_rows_for_account(db, market, customer["id"])
            for product in products:
                months = [0.0] * 12
                for week in future_weeks(52) + historical_weeks(52):
                    monday = week_monday(week)
                    thursday = monday + timedelta(days=3)
                    if thursday.year != year:
                        continue
                    actual = db.execute(
                        "SELECT qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                        (market, customer["id"], product["code"], week),
                    ).fetchone()
                    if monday < date.today() - timedelta(days=date.today().weekday()):
                        qty = float(actual["qty_cs"]) if actual else 0
                    else:
                        base = db.execute(
                            "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                            (market, customer["id"], product["code"], week),
                        ).fetchone()
                        qty = float(base["qty_cs"]) if base else 0
                        if market_row["plan_mode"] == "PROMO":
                            qty += approved_uplift(
                                db, market, customer["id"], product["code"], week
                            )
                    months[thursday.month - 1] += qty
                results.append(
                    {
                        "customer": customer["name"],
                        "customer_id": customer["id"],
                        "product": product["code"],
                        "description": product["description"],
                        "brand": product["brand"],
                        "months": months,
                        "total": sum(months),
                    }
                )
    return {
        "year": year,
        "market": market,
        "rows": results,
        "month_names": [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
    }


@router.get(f"{API_PREFIX}/calendar")
async def promo_calendar(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT horizon_weeks FROM market WHERE code=? AND active=1", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        rows = db.execute(
            "SELECT pr.id,pr.promo_number,pr.start_date,pr.end_date,pr.tactic,pr.status,"
            "c.name AS customer_name,p.sub_brand,COUNT(DISTINCT pi.p09_code) AS product_count "
            "FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id "
            "JOIN product_p09 p ON p.code=pi.p09_code "
            "JOIN listing l ON l.market_code=pr.market_code AND l.customer_id=pr.customer_id "
            "AND l.p09_code=pi.p09_code "
            "JOIN customer_l04 c ON c.id=pr.customer_id AND c.active=1 "
            "WHERE pr.market_code=? AND pr.customer_id=? AND pr.status IN ('SAVED','CHANGED','APPROVED') "
            "GROUP BY pr.id,p.sub_brand "
            "ORDER BY pr.start_date,pr.promo_number,p.sub_brand",
            (market, customer_id),
        ).fetchall()
        promotions = [dict(row) for row in rows]
        weeks = future_weeks(int(market_row["horizon_weeks"]))
    first_week = week_monday(weeks[0])
    last_week = week_monday(weeks[-1])
    if promotions:
        first_week = min(
            first_week,
            min(week_monday(iso_week(date.fromisoformat(row["start_date"]))) for row in promotions),
        )
        last_week = max(
            last_week,
            max(week_monday(iso_week(date.fromisoformat(row["end_date"]))) for row in promotions),
        )
    calendar_weeks = []
    week = first_week
    while week <= last_week:
        calendar_weeks.append(iso_week(week))
        week += timedelta(weeks=1)
    return {"weeks": calendar_weeks, "promotions": promotions}
