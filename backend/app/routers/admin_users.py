"""Configuration > Access Management (users) and audit log."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import (
    CurrentUser,
    require_access_administrator,
    require_configuration_view,
    require_role,
)
from app.schemas import AdminUserCreate, AdminUserUpdate
from app.security import password_hash
from app.services.access import validate_user_access
from app.services.audit import audit
from app.services.xlsx import build_xlsx
from app.utils import utcnow

router = APIRouter(tags=['admin_users'])

USER_AUDIT_COLUMNS = (
    "User Name",
    "Email address",
    "Actions (Changes Made)",
    "Arba Role",
    "Changed By",
    "Time stamp",
)


def _user_access_snapshot(db: Any, user_row: Any) -> dict[str, Any]:
    role = db.execute(
        "SELECT name FROM role_definition WHERE id=?",
        (user_row["role_definition_id"],),
    ).fetchone()
    return {
        "name": user_row["name"],
        "email": user_row["email"],
        "role": role["name"] if role else user_row["role"],
        "active": bool(user_row["active"]),
        "sales_org_access": [
            row["sales_org"]
            for row in db.execute(
                "SELECT sales_org FROM user_sales_org WHERE user_id=? ORDER BY sales_org",
                (user_row["id"],),
            )
        ],
        "admin_sales_org_access": [
            row["sales_org"]
            for row in db.execute(
                "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                (user_row["id"],),
            )
        ],
        "assignments": [
            f"{row['market_code']} · {row['customer_name']}"
            for row in db.execute(
                "SELECT ua.market_code,c.name AS customer_name "
                "FROM user_assignment ua JOIN customer_l04 c "
                "ON c.market_code=ua.market_code AND c.id=ua.customer_id "
                "WHERE ua.user_id=? ORDER BY ua.market_code,c.name",
                (user_row["id"],),
            )
        ],
    }


def _audit_change_description(action: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    if action in {"CREATE", "SIGN_UP", "SSO_SIGN_UP"}:
        role = after.get("role", "Unknown")
        return f"User created with {role} role; sales orgs: {', '.join(after.get('sales_org_access', [])) or 'none'}; plan accounts: {len(after.get('assignments', []))}"
    if action == "DELETE_USER":
        return "User deleted"
    changes = []
    if before.get("role") != after.get("role", after.get("role_id")):
        changes.append(f"Role: {before.get('role', 'Unknown')} → {after.get('role', after.get('role_id', 'Unknown'))}")
    if bool(before.get("active", True)) != bool(after.get("active", True)):
        changes.append("Account activated" if after.get("active") else "Account deactivated")
    for key, label in (
        ("sales_org_access", "Sales organization access"),
        ("admin_sales_org_access", "Administrator access"),
        ("assignments", "Plan account access"),
    ):
        old_values = before.get(key, [])
        new_values = after.get(key, [])
        if key == "assignments":
            old_values = [
                f"{item.get('market_code')} · {item.get('customer_id')}"
                if isinstance(item, dict) else str(item)
                for item in old_values
            ]
            new_values = [
                f"{item.get('market_code')} · {item.get('customer_id')}"
                if isinstance(item, dict) else str(item)
                for item in new_values
            ]
        added = sorted(set(new_values) - set(old_values))
        removed = sorted(set(old_values) - set(new_values))
        if added or removed:
            changes.append(
                f"{label}: "
                + "; ".join(
                    part for part in (
                        f"added {', '.join(added)}" if added else "",
                        f"removed {', '.join(removed)}" if removed else "",
                    ) if part
                )
            )
    return "; ".join(changes) or "User access updated"


@router.post(f"{API_PREFIX}/admin/users", status_code=201)
async def create_admin_user(payload: AdminUserCreate, user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    email = payload.email.strip().lower()
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="User name must contain at least 2 characters")
    with DB_LOCK, connect() as db:
        with db:
            role_definition = db.execute(
                "SELECT id,name,base_role FROM role_definition "
                "WHERE id=? AND active=1",
                (payload.role_id,),
            ).fetchone()
            if role_definition is None or role_definition["base_role"] == "ADMIN":
                raise HTTPException(status_code=422, detail="Select an assignable role")
            pairs = validate_user_access(db, payload.sales_org_access, payload.assignments)
            if db.execute(
                "SELECT 1 FROM app_user WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone():
                raise HTTPException(status_code=409, detail="A user with this email already exists")
            cursor = db.execute(
                "INSERT INTO app_user(email,name,role,role_definition_id,password_hash,active,last_login_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    email,
                    name,
                    role_definition["base_role"],
                    role_definition["id"],
                    password_hash(secrets.token_urlsafe(32)),
                    int(payload.active),
                    utcnow().isoformat(),
                ),
            )
            user_id = int(cursor.lastrowid)
            db.executemany(
                "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in sorted(set(payload.sales_org_access))],
            )
            db.executemany(
                "INSERT INTO user_assignment(user_id,market_code,customer_id) VALUES(?,?,?)",
                [(user_id, market_code, customer_id) for market_code, customer_id in pairs],
            )
            audit(
                db,
                "app_user",
                str(user_id),
                "CREATE",
                user["email"],
                after={
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "role": role_definition["name"],
                    "sales_org_access": payload.sales_org_access,
                    "assignments": pairs,
                    "admin_sales_org_access": [],
                },
            )
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": role_definition["name"],
        "role_id": role_definition["id"],
        "sales_org_access": sorted(set(payload.sales_org_access)),
        "admin_sales_org_access": [],
        "assignments": len(pairs),
    }


@router.get(f"{API_PREFIX}/admin/users")
async def admin_users(user: CurrentUser) -> dict[str, Any]:
    require_configuration_view(user)
    with DB_LOCK, connect() as db:
        users = []
        user_query = (
            "SELECT u.id,u.email,u.name,u.role AS base_role,u.role_definition_id,"
            "COALESCE(rd.name,u.role) AS role, u.active,u.last_login_at "
            "FROM app_user u LEFT JOIN role_definition rd ON rd.id=u.role_definition_id"
        )
        if user.get("base_role", user["role"]) != "ADMIN":
            user_query += " WHERE u.role<>'ADMIN'"
        user_query += " ORDER BY email"
        for row in db.execute(user_query):
            result = dict(row)
            result["sales_org_access"] = [
                item["sales_org"]
                for item in db.execute(
                    "SELECT sales_org FROM user_sales_org WHERE user_id=? ORDER BY sales_org",
                    (row["id"],),
                )
            ]
            result["admin_sales_org_access"] = [
                item["sales_org"]
                for item in db.execute(
                    "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                    (row["id"],),
                )
            ]
            users.append(result)
        assignments = [
            dict(r)
            for r in db.execute(
                "SELECT ua.user_id,u.email,ua.market_code,ua.customer_id,c.name AS customer_name "
                "FROM user_assignment ua JOIN app_user u ON u.id=ua.user_id "
                "JOIN customer_l04 c ON c.id=ua.customer_id ORDER BY u.email,ua.market_code,c.name"
            )
        ]
        sales_orgs = [
            dict(row)
            for row in db.execute(
                "SELECT p10_sales_org AS code,name FROM market WHERE active=1 ORDER BY p10_sales_org"
            )
        ]
        role_definitions = [
            dict(row)
            for row in db.execute(
                "SELECT id,name,base_role FROM role_definition "
                    "WHERE active=1 ORDER BY name"
            )
        ]
    return {
        "users": users,
        "assignments": assignments,
        "sales_orgs": sales_orgs,
        "role_definitions": role_definitions,
    }


@router.put(f"{API_PREFIX}/admin/users/{{user_id}}")
async def update_admin_user(
    user_id: int, payload: AdminUserUpdate, user: CurrentUser
) -> dict[str, Any]:
    require_access_administrator(user)
    with DB_LOCK, connect() as db:
        with db:
            role_definition = db.execute(
                "SELECT id,name,base_role FROM role_definition "
                "WHERE id=? AND active=1",
                (payload.role_id,),
            ).fetchone()
            if role_definition is None:
                raise HTTPException(status_code=422, detail="Select an assignable role")
            pairs = validate_user_access(db, payload.sales_org_access, payload.assignments)
            target = db.execute(
                "SELECT id,email,name,role,role_definition_id,active FROM app_user WHERE id=?",
                (user_id,),
            ).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="User not found")
            if user.get("base_role", user["role"]) != "ADMIN" and target["role"] == "ADMIN":
                raise HTTPException(
                    status_code=403,
                    detail="Only a system administrator can change a system administrator account",
                )
            if target["role"] == "ADMIN" and (
                role_definition["base_role"] != "ADMIN"
                or role_definition["id"] != target["role_definition_id"]
            ):
                raise HTTPException(status_code=403, detail="The system Admin role is fixed")
            if target["role"] != "ADMIN" and role_definition["base_role"] == "ADMIN":
                raise HTTPException(status_code=422, detail="The system Admin role cannot be assigned")
            for market_code, customer_id in pairs:
                assignment_exists = db.execute(
                    "SELECT 1 FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
                    (market_code, customer_id),
                ).fetchone()
                if assignment_exists is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid plan-account assignment: {market_code}/{customer_id}",
                    )
            before = _user_access_snapshot(db, target)
            db.execute(
                "UPDATE app_user SET role=?,role_definition_id=?,active=? WHERE id=?",
                (
                    role_definition["base_role"],
                    role_definition["id"],
                    int(payload.active),
                    user_id,
                ),
            )
            db.execute("DELETE FROM user_assignment WHERE user_id=?", (user_id,))
            db.executemany(
                "INSERT INTO user_assignment(user_id,market_code,customer_id) VALUES(?,?,?)",
                [(user_id, market_code, customer_id) for market_code, customer_id in pairs],
            )
            db.execute("DELETE FROM user_sales_org WHERE user_id=?", (user_id,))
            db.executemany(
                "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in sorted(set(payload.sales_org_access))],
            )
            db.execute("DELETE FROM user_sales_org_admin WHERE user_id=?", (user_id,))
            updated_target = db.execute(
                "SELECT id,email,name,role,role_definition_id,active FROM app_user WHERE id=?",
                (user_id,),
            ).fetchone()
            audit(
                db,
                "app_user",
                str(user_id),
                "UPDATE_ACCESS",
                user["email"],
                before=before,
                after=_user_access_snapshot(db, updated_target),
            )
    return {
        "id": user_id,
        "role": role_definition["name"],
        "role_id": role_definition["id"],
        "active": payload.active,
        "assignments": len(pairs),
        "admin_sales_org_access": [],
    }


@router.delete(f"{API_PREFIX}/admin/users/{{user_id}}")
async def delete_admin_user(user_id: int, user: CurrentUser) -> dict[str, str]:
    require_access_administrator(user)
    if user_id == user["id"]:
        raise HTTPException(status_code=409, detail="You cannot delete your own account")
    with DB_LOCK, connect() as db:
        with db:
            target = db.execute(
                "SELECT id,email,name,role,role_definition_id,active FROM app_user WHERE id=?",
                (user_id,),
            ).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="User not found")
            if target["role"] == "ADMIN":
                raise HTTPException(status_code=409, detail="System administrator accounts cannot be deleted")
            before = _user_access_snapshot(db, target)
            audit(
                db,
                "app_user",
                str(user_id),
                "DELETE_USER",
                user["email"],
                before=before,
            )
            db.execute("DELETE FROM user_assignment WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM user_sales_org WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM user_sales_org_admin WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM app_user WHERE id=?", (user_id,))
    return {"status": "deleted"}


@router.get(f"{API_PREFIX}/admin/audit")
async def admin_audit(user: CurrentUser, limit: int = 100) -> dict[str, Any]:
    require_role(user, "ADMIN")
    limit = max(1, min(limit, 500))
    with DB_LOCK, connect() as db:
        rows = [
            dict(r)
            for r in db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        ]
    return {"events": rows}


@router.get(f"{API_PREFIX}/admin/users/audit-export")
async def export_user_access_audit(user: CurrentUser) -> Response:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        audit_rows = db.execute(
            "SELECT id,entity_id,action,user,ts,before_json,after_json FROM audit_log "
            "WHERE entity='app_user' AND action IN "
            "('CREATE','SIGN_UP','SSO_SIGN_UP','UPDATE_ACCESS','DELETE_USER') "
            "ORDER BY ts DESC,id DESC"
        ).fetchall()
        rows: list[dict[str, str]] = []
        for entry in audit_rows:
            before = json.loads(entry["before_json"] or "{}")
            after = json.loads(entry["after_json"] or "{}")
            for snapshot in (before, after):
                legacy_role_id = snapshot.get("role_id", snapshot.get("role"))
                if isinstance(legacy_role_id, int):
                    role_row = db.execute(
                        "SELECT name FROM role_definition WHERE id=?", (legacy_role_id,)
                    ).fetchone()
                    if role_row:
                        snapshot["role"] = role_row["name"]
            identity = after if entry["action"] in {"CREATE", "SIGN_UP", "SSO_SIGN_UP"} else before
            if not identity.get("name") or not identity.get("email"):
                current = db.execute(
                    "SELECT name,email FROM app_user WHERE id=?",
                    (entry["entity_id"],),
                ).fetchone()
                if current:
                    identity = {**dict(current), **identity}
            timestamp = datetime.fromisoformat(entry["ts"]).strftime("%d%m%Y %H:%M:%S")
            rows.append(
                {
                    "User Name": str(identity.get("name", "")),
                    "Email address": str(identity.get("email", "")),
                    "Actions (Changes Made)": _audit_change_description(
                        entry["action"], before, after
                    ),
                    "Arba Role": str(after.get("role") or before.get("role") or ""),
                    "Changed By": entry["user"],
                    "Time stamp": timestamp,
                }
            )
    return Response(
        build_xlsx(rows, USER_AUDIT_COLUMNS),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="user_audit.xlsx"'},
    )
