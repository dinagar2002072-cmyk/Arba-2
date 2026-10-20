"""Market-scoped tactic configuration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, require_access_administrator
from app.schemas import TacticPayload
from app.services.audit import audit

router = APIRouter(tags=["tactics"])


def _visible_market(db: Any, user: dict[str, Any], market_code: str) -> dict[str, Any]:
    market = db.execute(
        "SELECT code,name,p10_sales_org FROM market WHERE code=? AND active=1",
        (market_code,),
    ).fetchone()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    if (
        user["role"] != "ADMIN"
        and market["p10_sales_org"] not in user.get("admin_sales_org_access", [])
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot manage tactics for this sales organization",
        )
    return dict(market)


@router.get(f"{API_PREFIX}/admin/tactics")
async def get_tactics(user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    with DB_LOCK, connect() as db:
        markets = db.execute(
            "SELECT code,name,p10_sales_org FROM market WHERE active=1 ORDER BY name"
        ).fetchall()
        visible_markets = [
            dict(market)
            for market in markets
            if user["role"] == "ADMIN"
            or market["p10_sales_org"] in user.get("admin_sales_org_access", [])
        ]
        market_codes = [market["code"] for market in visible_markets]
        tactics: list[dict[str, Any]] = []
        if market_codes:
            placeholders = ",".join("?" for _ in market_codes)
            tactics = [
                dict(row)
                for row in db.execute(
                    "SELECT market_code,name,incentive_type,created_by FROM tactic "
                    f"WHERE active=1 AND market_code IN ({placeholders}) ORDER BY name",
                    market_codes,
                )
            ]
    return {"markets": visible_markets, "tactics": tactics}


@router.post(f"{API_PREFIX}/admin/tactics", status_code=201)
async def create_tactic(payload: TacticPayload, user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tactic name cannot be empty")
    with DB_LOCK, connect() as db:
        with db:
            market = _visible_market(db, user, payload.market_code)
            existing = db.execute(
                "SELECT name,active FROM tactic WHERE market_code=? AND name=? COLLATE NOCASE",
                (payload.market_code, name),
            ).fetchone()
            if existing and existing["active"]:
                raise HTTPException(
                    status_code=409,
                    detail="A tactic with this name already exists for this market",
                )
            if existing:
                db.execute(
                    "UPDATE tactic SET active=1,incentive_type=?,created_by=? "
                    "WHERE market_code=? AND name=?",
                    (
                        payload.incentive_type,
                        user["email"],
                        payload.market_code,
                        existing["name"],
                    ),
                )
                name = existing["name"]
            else:
                db.execute(
                    "INSERT INTO tactic(market_code,name,incentive_type,created_by) "
                    "VALUES(?,?,?,?)",
                    (payload.market_code, name, payload.incentive_type, user["email"]),
                )
            tactic = {
                "market_code": payload.market_code,
                "market_name": market["name"],
                "sales_org": market["p10_sales_org"],
                "name": name,
                "incentive_type": payload.incentive_type,
            }
            audit(
                db,
                "tactic",
                f"{payload.market_code}:{name}",
                "CREATE",
                user["email"],
                after=tactic,
            )
    return {"tactic": tactic}
