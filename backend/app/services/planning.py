"""Shared planning queries (products for a plan account)."""

from __future__ import annotations

import sqlite3


def product_rows_for_account(
    db: sqlite3.Connection, market: str, customer_id: int
) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT p.code,p.description,p.brand,p.sub_brand,p.category,p.active
        FROM product_p09 p
        JOIN listing l ON l.p09_code=p.code
        WHERE l.market_code=? AND l.customer_id=?
        ORDER BY p.brand,p.description
        """,
        (market, customer_id),
    ).fetchall()
