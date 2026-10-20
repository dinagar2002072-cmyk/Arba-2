"""System administrator management of application roles and permissions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import API_PREFIX
from app.db import DB_LOCK, connect
from app.deps import CurrentUser, require_role
from app.schemas import RoleDefinitionPayload
from app.services.audit import audit
from app.role_permissions import validate_role_name, validated_permissions

router = APIRouter(tags=["role_definitions"])


def _role_json(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "system_key": row["system_key"],
        "base_role": row["base_role"],
        "permissions": json.loads(row["permissions_json"]),
        "is_system": row["system_key"] is not None,
    }


@router.get(f"{API_PREFIX}/admin/roles")
async def get_role_definitions(user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        roles = [
            _role_json(row)
            for row in db.execute(
                "SELECT id,name,system_key,base_role,permissions_json "
                "FROM role_definition WHERE active=1 ORDER BY "
                "CASE WHEN system_key IS NULL THEN 1 ELSE 0 END,name"
            )
        ]
    return {"roles": roles}


@router.post(f"{API_PREFIX}/admin/roles", status_code=201)
async def create_role_definition(
    payload: RoleDefinitionPayload, user: CurrentUser
) -> dict[str, Any]:
    require_role(user, "ADMIN")
    try:
        name = validate_role_name(payload.name)
        permissions = validated_permissions(payload.permissions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with DB_LOCK, connect() as db:
        with db:
            try:
                cursor = db.execute(
                    "INSERT INTO role_definition(name,system_key,base_role,permissions_json,active) "
                    "VALUES(?,NULL,'VIEWER',?,1)",
                    (name, json.dumps(permissions, sort_keys=True)),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(
                    status_code=409, detail="A role with this name already exists"
                ) from exc
            role_id = int(cursor.lastrowid)
            audit(
                db,
                "role_definition",
                str(role_id),
                "CREATE",
                user["email"],
                after={"name": name, "permissions": permissions},
            )
            row = db.execute(
                "SELECT id,name,system_key,base_role,permissions_json "
                "FROM role_definition WHERE id=?",
                (role_id,),
            ).fetchone()
    return {"role": _role_json(row)}


@router.put(f"{API_PREFIX}/admin/roles/{{role_id}}")
async def update_role_definition(
    role_id: int, payload: RoleDefinitionPayload, user: CurrentUser
) -> dict[str, Any]:
    require_role(user, "ADMIN")
    try:
        name = validate_role_name(payload.name)
        permissions = validated_permissions(payload.permissions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with DB_LOCK, connect() as db:
        with db:
            current = db.execute(
                "SELECT id,name,system_key,base_role,permissions_json "
                "FROM role_definition WHERE id=? AND active=1",
                (role_id,),
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Role not found")
            if current["system_key"] == "ADMIN":
                raise HTTPException(status_code=403, detail="The system Admin role is fixed")
            if current["system_key"] is not None and name != current["name"]:
                raise HTTPException(status_code=403, detail="Built-in role names are fixed")
            before = _role_json(current)
            try:
                db.execute(
                    "UPDATE role_definition SET name=?,permissions_json=? WHERE id=?",
                    (name, json.dumps(permissions, sort_keys=True), role_id),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(
                    status_code=409, detail="A role with this name already exists"
                ) from exc
            row = db.execute(
                "SELECT id,name,system_key,base_role,permissions_json "
                "FROM role_definition WHERE id=?",
                (role_id,),
            ).fetchone()
            audit(
                db,
                "role_definition",
                str(role_id),
                "UPDATE",
                user["email"],
                before=before,
                after=_role_json(row),
            )
    return {"role": _role_json(row)}


@router.delete(f"{API_PREFIX}/admin/roles/{{role_id}}")
async def delete_role_definition(role_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute(
                "SELECT id,name,system_key FROM role_definition WHERE id=? AND active=1",
                (role_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Role not found")
            if row["system_key"] is not None:
                raise HTTPException(status_code=409, detail="Built-in roles cannot be deleted")
            if db.execute(
                "SELECT 1 FROM app_user WHERE role_definition_id=? LIMIT 1",
                (role_id,),
            ).fetchone():
                raise HTTPException(
                    status_code=409, detail="Reassign users before deleting this role"
                )
            db.execute("UPDATE role_definition SET active=0 WHERE id=?", (role_id,))
            audit(
                db,
                "role_definition",
                str(role_id),
                "DELETE",
                user["email"],
                before={"name": row["name"]},
            )
    return {"status": "deleted"}
