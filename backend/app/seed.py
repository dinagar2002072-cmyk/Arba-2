"""Application reference data and initial users loaded on first run."""

from __future__ import annotations

import os
import secrets
import sqlite3

from app.config import MARKETS
from app.security import password_hash


def seed_database(db: sqlite3.Connection) -> None:
    db.executemany(
        "INSERT INTO market(code,name,plan_mode,p10_sales_org,horizon_weeks) VALUES(?,?,?,?,52)",
        MARKETS,
    )
    initial_password = os.getenv("ARBA_INITIAL_PASSWORD")
    if not initial_password:
        initial_password = secrets.token_urlsafe(15)
        print(
            f"\nArBa first-run password (admin@arba.local): {initial_password}\n",
            flush=True,
        )
        print(
            "Set ARBA_INITIAL_PASSWORD to choose a first-run password.",
            flush=True,
        )
    if len(initial_password) < 12:
        raise ValueError("ARBA_INITIAL_PASSWORD must contain at least 12 characters")
    users = (
        ("admin@arba.local", "ArBa Administrator", "ADMIN"),
        ("planner@arba.local", "Demo Planner", "PLANNER"),
        ("approver@arba.local", "Demo Approver", "APPROVER"),
        ("viewer@arba.local", "Demo Viewer", "VIEWER"),
    )
    user_ids: dict[str, int] = {}
    for email, name, role in users:
        cursor = db.execute(
            "INSERT INTO app_user(email,name,role,password_hash,is_seed) VALUES(?,?,?,?,1)",
            (email, name, role, password_hash(initial_password)),
        )
        user_ids[role] = int(cursor.lastrowid)
    for role in ("PLANNER", "APPROVER", "VIEWER"):
        db.executemany(
            "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
            [(user_ids[role], sales_org) for _, _, _, sales_org in MARKETS],
        )
    db.commit()
