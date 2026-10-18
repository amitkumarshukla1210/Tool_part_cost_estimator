"""The costing database: one SQLite file for all costing data.

    master_data/costing_db.sqlite
        mould & die tables     (mould_db.py)
        setup tables           (costing_setup.py: countries, machines, labour grades, cost formulas)
        rate library           (rates.py: versioned country rates and forex)
        settings               (approver name, review threshold)

Set COSTING_DB_PATH to use another file (the tests use a temporary copy).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "master_data" / "costing_db.sqlite"


def path() -> Path:
    return Path(os.environ.get("COSTING_DB_PATH", DEFAULT_PATH))


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return con
