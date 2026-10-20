"""FastAPI dependencies: current user and authorisation checks."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from app.db import DB_LOCK, connect
from app.security import verify_session
from app.role_permissions import user_role_data


def get_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("arba_session")
    session = verify_session(token) if token else None
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    user_id, _ = session
    with DB_LOCK, connect() as db:
        row = db.execute(
            "SELECT id,email,name,role,role_definition_id,active FROM app_user WHERE id=?",
            (user_id,),
        ).fetchone()
        admin_sales_org_access = [
            item["sales_org"]
            for item in db.execute(
                "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                (user_id,),
            )
        ]
        if row is None or not row["active"]:
            raise HTTPException(status_code=401, detail="Account is inactive")
        role_data = user_role_data(db, row["role_definition_id"], row["role"])
    return {
        **dict(row),
        **role_data,
        "admin_sales_org_access": admin_sales_org_access,
    }


CurrentUser = Annotated[dict[str, Any], Depends(get_user)]


def require_role(user: dict[str, Any], *roles: str) -> None:
    base_role = user.get("base_role", user["role"])
    if base_role != "ADMIN" and base_role not in roles:
        raise HTTPException(status_code=403, detail="Your role cannot perform this action")


def require_permission(user: dict[str, Any], screen: str, action: str) -> None:
    if user.get("base_role", user["role"]) == "ADMIN":
        return
    permissions = user.get("permissions", {})
    if action not in permissions.get(screen, []):
        raise HTTPException(
            status_code=403,
            detail=f"Your role does not have {action} access to {screen}",
        )


def require_access_administrator(user: dict[str, Any]) -> None:
    require_permission(user, "configuration", "edit")


def require_configuration_view(user: dict[str, Any]) -> None:
    require_permission(user, "configuration", "view")


def check_assignment(
    db: sqlite3.Connection, user: dict[str, Any], market: str, customer: int
) -> None:
    if user.get("base_role", user["role"]) == "ADMIN":
        return
    market_row = db.execute(
        "SELECT p10_sales_org FROM market WHERE code=? AND active=1", (market,)
    ).fetchone()
    if market_row and market_row["p10_sales_org"] in user.get("admin_sales_org_access", []):
        return
    allowed = db.execute(
        "SELECT 1 FROM user_assignment ua "
        "JOIN market m ON m.code=ua.market_code "
        "JOIN user_sales_org so ON so.user_id=ua.user_id AND so.sales_org=m.p10_sales_org "
        "WHERE ua.user_id=? AND ua.market_code=? AND ua.customer_id=?",
        (user["id"], market, customer),
    ).fetchone()
    if not allowed:
        raise HTTPException(status_code=403, detail="Plan account is not assigned to your user")
