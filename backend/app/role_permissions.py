"""Role permission defaults and validation helpers."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

SCREEN_ACTIONS: dict[str, tuple[str, ...]] = {
    "weekly": ("view", "edit", "import", "export"),
    "promotions": ("view", "edit", "approve"),
    "calendar": ("view",),
    "history": ("view", "export"),
    "report": ("view",),
    "listing": ("view", "edit"),
    "configuration": ("view", "edit"),
}

ADMIN_PERMISSIONS = {
    screen: list(actions) for screen, actions in SCREEN_ACTIONS.items()
}


def ensure_default_roles(db: sqlite3.Connection) -> None:
    permissions = json.dumps(ADMIN_PERMISSIONS, sort_keys=True)
    db.execute(
        "INSERT OR IGNORE INTO role_definition(name,system_key,base_role,permissions_json,active) "
        "VALUES('ADMIN','ADMIN','ADMIN',?,1)",
        (permissions,),
    )
    db.execute(
        "UPDATE role_definition SET permissions_json=?,active=1 WHERE system_key='ADMIN'",
        (permissions,),
    )
    db.execute(
        "UPDATE role_definition SET active=0 WHERE system_key IN ('PLANNER','APPROVER','VIEWER')"
    )
    db.execute(
        "UPDATE app_user SET role_definition_id=("
        "SELECT id FROM role_definition WHERE system_key='ADMIN' AND active=1"
        ") WHERE role='ADMIN' AND role_definition_id IS NULL"
    )


def validated_permissions(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("Permissions must be a screen-to-actions object")
    unknown_screens = set(value) - set(SCREEN_ACTIONS)
    if unknown_screens:
        raise ValueError(f"Unknown screen: {sorted(unknown_screens)[0]}")
    result: dict[str, list[str]] = {}
    for screen, actions in value.items():
        if not isinstance(actions, list):
            raise ValueError(f"Permissions for {screen} must be a list")
        allowed = set(SCREEN_ACTIONS[screen])
        if any(not isinstance(action, str) or action not in allowed for action in actions):
            raise ValueError(f"Invalid permission for {screen}")
        if set(actions) - {"view"} and "view" not in actions:
            raise ValueError(f"Grant view access before other permissions for {screen}")
        normalized = sorted(set(actions), key=SCREEN_ACTIONS[screen].index)
        if normalized:
            result[screen] = normalized
    return result


def user_role_data(
    db: sqlite3.Connection, role_definition_id: int | None, base_role: str
) -> dict[str, Any]:
    role = None
    if role_definition_id is not None:
        role = db.execute(
            "SELECT id,name,base_role,permissions_json FROM role_definition "
            "WHERE id=? AND active=1",
            (role_definition_id,),
        ).fetchone()
    if role is None:
        role = db.execute(
            "SELECT id,name,base_role,permissions_json FROM role_definition "
            "WHERE system_key=? AND active=1",
            (base_role,),
        ).fetchone()
    if role is None:
        return {
            "role": base_role,
            "base_role": base_role,
            "role_definition_id": None,
            "permissions": ADMIN_PERMISSIONS if base_role == "ADMIN" else {},
        }
    return {
        "role": role["name"],
        "base_role": role["base_role"],
        "role_definition_id": role["id"],
        "permissions": json.loads(role["permissions_json"]),
    }


def validate_role_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{1,39}", normalized):
        raise ValueError("Role name must be 2-40 characters and start with a letter")
    return normalized
