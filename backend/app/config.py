"""Application settings, file paths, and reference constants."""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

APP_TITLE = "ArBa Advanced Volume Planner"


API_PREFIX = "/api/v1"


MARKETS = (
    ("DE", "Germany", "VOL", "DE10"),
    ("ES", "Spain", "VOL", "ES10"),
    ("PT", "Portugal", "VOL", "PT10"),
    ("CH", "Switzerland", "PROMO", "CH10"),
    ("NL", "Netherlands", "PROMO", "NL10"),
    ("AT", "Austria", "PROMO", "AT10"),
    ("BE", "Belgium", "PROMO", "BE10"),
)

CUSTOMER_MASTER_SALES_ORG_MARKET_MAP = {"1750": "AT"}


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


logger = logging.getLogger("arba")


PROJECT_ROOT = Path(__file__).resolve().parents[2]


DB_PATH = Path(os.getenv("ARBA_DB_PATH", PROJECT_ROOT / "data" / "arba_volume_planner.sqlite3"))


FILE_ROOT = Path(os.getenv("ARBA_FILES_DIR", DB_PATH.parent / "arba_files"))


INBOUND_QUEUE_DIR = FILE_ROOT / "Inbound Queue"


INBOUND_PROCESSED_DIR = FILE_ROOT / "Inbound Processed"


OUTBOUND_DIR = FILE_ROOT / "Outbound"


SIGNING_SECRET = os.getenv("ARBA_SECRET", "")


if not SIGNING_SECRET:
    SIGNING_SECRET = secrets.token_urlsafe(48)


SSO_STATE_COOKIE = "arba_sso_state"


SSO_SCOPES = "openid profile email User.Read"


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
