"""Background scheduler for inactive-user deactivation."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta

from app.config import logger
from app.db import DB_LOCK, connect
from app.services.audit import audit
from app.utils import utcnow


async def inactive_user_scheduler() -> None:
    while True:
        try:
            now = utcnow()
            inactive_before = (now - timedelta(days=30)).isoformat()
            with DB_LOCK, connect() as db:
                inactive_users = db.execute(
                    "SELECT id,email,last_login_at FROM app_user "
                    "WHERE active=1 AND last_login_at IS NOT NULL AND last_login_at<?",
                    (inactive_before,),
                ).fetchall()
                if inactive_users:
                    with db:
                        for inactive_user in inactive_users:
                            db.execute(
                                "UPDATE app_user SET active=0 WHERE id=? AND active=1",
                                (inactive_user["id"],),
                            )
                            if db.execute("SELECT changes()").fetchone()[0]:
                                audit(
                                    db,
                                    "app_user",
                                    str(inactive_user["id"]),
                                    "AUTO_DEACTIVATE_INACTIVE",
                                    "scheduler@arba.local",
                                    before={
                                        "active": True,
                                        "last_login_at": inactive_user["last_login_at"],
                                    },
                                    after={"active": False},
                                )
        except sqlite3.Error:
            logger.exception("Inactive-user scheduler database error")
        await asyncio.sleep(20)
