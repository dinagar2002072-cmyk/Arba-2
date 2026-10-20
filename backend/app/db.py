"""SQLite connection helper and schema creation / lightweight migrations."""

from __future__ import annotations

import sqlite3
import threading

from app.config import DB_PATH
from app.seed import seed_database
from app.utils import utcnow

DB_LOCK = threading.RLock()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def create_schema_and_seed() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS market (
                code TEXT PRIMARY KEY, name TEXT NOT NULL,
                plan_mode TEXT NOT NULL CHECK(plan_mode IN ('VOL','PROMO')),
                p10_sales_org TEXT NOT NULL, horizon_weeks INTEGER NOT NULL DEFAULT 52,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS customer_l04 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, market_code TEXT NOT NULL REFERENCES market(code),
                name TEXT NOT NULL, parent_l03 TEXT, active INTEGER NOT NULL DEFAULT 1,
                source_updated_at TEXT, external_code TEXT, UNIQUE(market_code,name), UNIQUE(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS product_hierarchy (
                node_id TEXT PRIMARY KEY, parent_id TEXT REFERENCES product_hierarchy(node_id),
                level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 10), code TEXT NOT NULL, text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_p09 (
                code TEXT PRIMARY KEY, description TEXT NOT NULL, brand TEXT NOT NULL,
                sub_brand TEXT NOT NULL, category TEXT NOT NULL,
                hierarchy_node_id TEXT NOT NULL REFERENCES product_hierarchy(node_id),
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tactic (
                market_code TEXT NOT NULL REFERENCES market(code), name TEXT NOT NULL,
                incentive_type TEXT NOT NULL CHECK(incentive_type IN ('FIXED_LUMPSUM','VARIABLE')),
                created_by TEXT,
                active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(market_code,name)
            );
            CREATE TABLE IF NOT EXISTS app_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('PLANNER','APPROVER','ADMIN','VIEWER')),
                password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                is_seed INTEGER NOT NULL DEFAULT 0,
                sso_subject TEXT, last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS role_definition (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                system_key TEXT UNIQUE,
                base_role TEXT NOT NULL CHECK(base_role IN ('PLANNER','APPROVER','VIEWER','ADMIN')),
                permissions_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS user_assignment (
                user_id INTEGER NOT NULL REFERENCES app_user(id), market_code TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                PRIMARY KEY(user_id,market_code,customer_id),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS user_sales_org (
                user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                sales_org TEXT NOT NULL, PRIMARY KEY(user_id,sales_org)
            );
            CREATE TABLE IF NOT EXISTS user_sales_org_admin (
                user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                sales_org TEXT NOT NULL,
                PRIMARY KEY(user_id,sales_org)
            );
            CREATE TABLE IF NOT EXISTS listing (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS baseline (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                iso_week TEXT NOT NULL, qty_cs REAL NOT NULL CHECK(qty_cs >= 0),
                source TEXT NOT NULL CHECK(source IN ('MANUAL','UPLOAD')),
                changed_by TEXT NOT NULL, changed_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code,iso_week),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS actual_sellin (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                iso_week TEXT NOT NULL, qty_cs REAL NOT NULL CHECK(qty_cs >= 0), loaded_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code,iso_week),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS promotion (
                id INTEGER PRIMARY KEY AUTOINCREMENT, promo_number TEXT UNIQUE NOT NULL,
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL, cons_start TEXT NOT NULL, cons_end TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', comments TEXT NOT NULL DEFAULT '',
                tactic TEXT NOT NULL, incentive_type TEXT NOT NULL DEFAULT 'VARIABLE'
                    CHECK(incentive_type IN ('FIXED_LUMPSUM','VARIABLE')),
                incentive_value REAL NOT NULL DEFAULT 0 CHECK(incentive_value >= 0),
                incentive_configured INTEGER NOT NULL DEFAULT 0 CHECK(incentive_configured IN (0,1)),
                status TEXT NOT NULL CHECK(status IN ('NEW','SAVED','CHANGED','APPROVED')),
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT,
                version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                CHECK(end_date >= start_date), CHECK(cons_end >= cons_start),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id),
                FOREIGN KEY(market_code,tactic) REFERENCES tactic(market_code,name)
            );
            CREATE TABLE IF NOT EXISTS promotion_item (
                promotion_id INTEGER NOT NULL REFERENCES promotion(id) ON DELETE CASCADE,
                p09_code TEXT NOT NULL REFERENCES product_p09(code),
                total_cs REAL NOT NULL CHECK(total_cs >= 0), PRIMARY KEY(promotion_id,p09_code)
            );
            CREATE TABLE IF NOT EXISTS promotion_phasing (
                sales_org TEXT NOT NULL, customer_id INTEGER NOT NULL REFERENCES customer_l04(id),
                duration_weeks INTEGER NOT NULL CHECK(duration_weeks IN (2,3,4)),
                percentages_json TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(sales_org,customer_id,duration_weeks)
            );
            CREATE TABLE IF NOT EXISTS promotion_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, promotion_id INTEGER NOT NULL REFERENCES promotion(id),
                ts TEXT NOT NULL, user TEXT NOT NULL, old_status TEXT, new_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
                action TEXT NOT NULL, user TEXT NOT NULL, ts TEXT NOT NULL,
                before_json TEXT, after_json TEXT
            );
            CREATE TABLE IF NOT EXISTS managed_file (
                id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL,
                category TEXT NOT NULL, original_name TEXT NOT NULL, stored_path TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL,
                processed_at TEXT, row_count INTEGER NOT NULL DEFAULT 0, message TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_baseline_market_customer_week
                ON baseline(market_code,customer_id,iso_week);
            CREATE INDEX IF NOT EXISTS ix_actual_market_customer_week
                ON actual_sellin(market_code,customer_id,iso_week);
            CREATE INDEX IF NOT EXISTS ix_promotion_account_dates
                ON promotion(market_code,customer_id,start_date,end_date);
            """
        )
        hierarchy_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='product_hierarchy'"
        ).fetchone()["sql"]
        if "between 1 and 9" in hierarchy_sql.lower():
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE product_hierarchy_v10 ("
                "node_id TEXT PRIMARY KEY,parent_id TEXT REFERENCES product_hierarchy_v10(node_id),"
                "level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 10),code TEXT NOT NULL,text TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO product_hierarchy_v10(node_id,parent_id,level,code,text) "
                "SELECT node_id,parent_id,level,code,text FROM product_hierarchy"
            )
            db.execute("DROP TABLE product_hierarchy")
            db.execute("ALTER TABLE product_hierarchy_v10 RENAME TO product_hierarchy")
            db.commit()
            db.execute("PRAGMA foreign_keys=ON")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Product hierarchy migration produced invalid references")
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(app_user)")}
        if "sso_subject" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN sso_subject TEXT")
        if "is_seed" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN is_seed INTEGER NOT NULL DEFAULT 0")
        if "last_login_at" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN last_login_at TEXT")
        db.execute(
            "UPDATE app_user SET last_login_at=? WHERE last_login_at IS NULL",
            (utcnow().isoformat(),),
        )
        db.execute(
            "UPDATE app_user SET is_seed=1 WHERE email IN "
            "('admin@arba.local','planner@arba.local','approver@arba.local','viewer@arba.local')"
        )
        customer_columns = {row["name"] for row in db.execute("PRAGMA table_info(customer_l04)")}
        if "external_code" not in customer_columns:
            db.execute("ALTER TABLE customer_l04 ADD COLUMN external_code TEXT")
        tactic_columns = {row["name"] for row in db.execute("PRAGMA table_info(tactic)")}
        if "incentive_type" not in tactic_columns:
            db.execute(
                "ALTER TABLE tactic ADD COLUMN incentive_type TEXT NOT NULL DEFAULT 'VARIABLE'"
            )
        if "created_by" not in tactic_columns:
            db.execute("ALTER TABLE tactic ADD COLUMN created_by TEXT")
        db.execute("UPDATE tactic SET active=0 WHERE created_by IS NULL")
        promotion_columns = {row["name"] for row in db.execute("PRAGMA table_info(promotion)")}
        promotion_migrations = {
            "description": "TEXT NOT NULL DEFAULT ''",
            "comments": "TEXT NOT NULL DEFAULT ''",
            "incentive_type": "TEXT NOT NULL DEFAULT 'VARIABLE'",
            "incentive_value": "REAL NOT NULL DEFAULT 0",
            "incentive_configured": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in promotion_migrations.items():
            if column not in promotion_columns:
                db.execute(f"ALTER TABLE promotion ADD COLUMN {column} {definition}")
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(app_user)")}
        if "role_definition_id" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN role_definition_id INTEGER")
        from app.role_permissions import ensure_default_roles

        ensure_default_roles(db)
        db.execute(
            "INSERT OR IGNORE INTO user_sales_org(user_id,sales_org) "
            "SELECT DISTINCT ua.user_id,m.p10_sales_org FROM user_assignment ua "
            "JOIN market m ON m.code=ua.market_code"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_app_user_sso_subject "
            "ON app_user(sso_subject) WHERE sso_subject IS NOT NULL"
        )
        db.execute(
            "UPDATE customer_l04 SET active=0 "
            "WHERE source_updated_at IS NULL "
            "AND parent_l03=market_code || '-L03-01'"
        )
        db.execute(
            "UPDATE product_p09 SET active=0 "
            "WHERE hierarchy_node_id=code"
        )
        if db.execute("SELECT 1 FROM market LIMIT 1").fetchone():
            return
        seed_database(db)
        ensure_default_roles(db)
