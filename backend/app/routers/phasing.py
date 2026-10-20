"""Configuration endpoints for account-specific promotion uplift phasing."""

from __future__ import annotations

import json
import math
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, require_access_administrator
from app.schemas import PromotionPhasingPayload
from app.services.audit import audit
from app.utils import utcnow

router = APIRouter(tags=["phasing"])


def _visible_sales_orgs(user: dict[str, Any]) -> list[str] | None:
    if user["role"] == "ADMIN":
        return None
    return user.get("admin_sales_org_access", [])


@router.get(f"{API_PREFIX}/admin/phasing")
async def get_phasing(user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    visible_sales_orgs = _visible_sales_orgs(user)
    with DB_LOCK, connect() as db:
        markets_query = (
            "SELECT code,name,p10_sales_org FROM market WHERE active=1"
        )
        accounts_query = (
            "SELECT m.code AS market_code,m.p10_sales_org AS sales_org,"
            "c.id AS customer_id,c.name AS customer_name "
            "FROM market m JOIN customer_l04 c ON c.market_code=m.code "
            "WHERE m.active=1 AND c.active=1"
        )
        profiles_query = (
            "SELECT ph.sales_org,ph.customer_id,ph.duration_weeks,"
            "ph.percentages_json,ph.updated_at,m.code AS market_code,c.name AS customer_name "
            "FROM promotion_phasing ph JOIN customer_l04 c ON c.id=ph.customer_id "
            "JOIN market m ON m.code=c.market_code WHERE m.active=1 AND c.active=1"
        )
        if visible_sales_orgs is not None:
            if not visible_sales_orgs:
                return {"markets": [], "accounts": [], "profiles": []}
            placeholders = ",".join("?" for _ in visible_sales_orgs)
            sales_filter = f" AND p10_sales_org IN ({placeholders})"
            markets = [
                dict(row)
                for row in db.execute(markets_query + sales_filter + " ORDER BY name", visible_sales_orgs)
            ]
            accounts = [
                dict(row)
                for row in db.execute(
                    accounts_query + f" AND m.p10_sales_org IN ({placeholders}) ORDER BY m.name,c.name",
                    visible_sales_orgs,
                )
            ]
            profiles_rows = db.execute(
                profiles_query + f" AND ph.sales_org IN ({placeholders}) ORDER BY m.name,c.name,ph.duration_weeks",
                visible_sales_orgs,
            ).fetchall()
        else:
            markets = [
                dict(row)
                for row in db.execute(markets_query + " ORDER BY name")
            ]
            accounts = [
                dict(row)
                for row in db.execute(accounts_query + " ORDER BY m.name,c.name")
            ]
            profiles_rows = db.execute(
                profiles_query + " ORDER BY m.name,c.name,ph.duration_weeks"
            ).fetchall()
        profiles = [
            {
                "market_code": row["market_code"],
                "sales_org": row["sales_org"],
                "customer_id": row["customer_id"],
                "customer_name": row["customer_name"],
                "duration_weeks": row["duration_weeks"],
                "percentages": json.loads(row["percentages_json"]),
                "updated_at": row["updated_at"],
            }
            for row in profiles_rows
        ]
    return {"markets": markets, "accounts": accounts, "profiles": profiles}


@router.put(f"{API_PREFIX}/admin/phasing")
async def save_phasing(
    payload: PromotionPhasingPayload, user: CurrentUser
) -> dict[str, Any]:
    require_access_administrator(user)
    if len(payload.percentages) != payload.duration_weeks:
        raise HTTPException(
            status_code=422,
            detail=f"A {payload.duration_weeks}-week profile must contain exactly {payload.duration_weeks} percentages",
        )
    if not all(math.isfinite(value) and 0 <= value <= 100 for value in payload.percentages):
        raise HTTPException(
            status_code=422,
            detail="Each weekly percentage must be between 0 and 100",
        )
    if not math.isclose(sum(payload.percentages), 100.0, abs_tol=0.01):
        raise HTTPException(
            status_code=422,
            detail="Weekly percentages must total 100%",
        )

    with DB_LOCK, connect() as db:
        with db:
            account = db.execute(
                "SELECT c.id,c.name,m.code AS market_code,m.p10_sales_org AS sales_org "
                "FROM customer_l04 c JOIN market m ON m.code=c.market_code "
                "WHERE c.id=? AND c.market_code=? AND c.active=1 AND m.active=1",
                (payload.customer_id, payload.market_code),
            ).fetchone()
            if account is None:
                raise HTTPException(status_code=404, detail="Plan account not found for this market")
            allowed_sales_orgs = _visible_sales_orgs(user)
            if (
                allowed_sales_orgs is not None
                and account["sales_org"] not in allowed_sales_orgs
            ):
                raise HTTPException(
                    status_code=403,
                    detail="You cannot manage phasing for this sales organization",
                )
            key = (
                account["sales_org"],
                payload.customer_id,
                payload.duration_weeks,
            )
            existing = db.execute(
                "SELECT percentages_json FROM promotion_phasing "
                "WHERE sales_org=? AND customer_id=? AND duration_weeks=?",
                key,
            ).fetchone()
            before = json.loads(existing["percentages_json"]) if existing else None
            percentages = [float(value) for value in payload.percentages]
            updated_at = utcnow().isoformat()
            db.execute(
                "INSERT INTO promotion_phasing(sales_org,customer_id,duration_weeks,"
                "percentages_json,updated_by,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(sales_org,customer_id,duration_weeks) DO UPDATE SET "
                "percentages_json=excluded.percentages_json,updated_by=excluded.updated_by,"
                "updated_at=excluded.updated_at",
                (*key, json.dumps(percentages), user["email"], updated_at),
            )
            profile = {
                "market_code": account["market_code"],
                "sales_org": account["sales_org"],
                "customer_id": account["id"],
                "customer_name": account["name"],
                "duration_weeks": payload.duration_weeks,
                "percentages": percentages,
                "updated_at": updated_at,
            }
            audit(
                db,
                "promotion_phasing",
                f"{account['sales_org']}:{account['id']}:{payload.duration_weeks}",
                "UPSERT",
                user["email"],
                before=before,
                after=profile,
            )
    return {"profile": profile}
