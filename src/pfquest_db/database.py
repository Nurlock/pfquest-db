"""Database connection and management utilities."""

import sqlite3
from pathlib import Path
from typing import Dict, Any

from .schema import init_database


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open or create a SQLite database with WAL and foreign key support."""
    path = Path(db_path)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Initialize a new database with tables, indexes, and views."""
    conn = get_connection(db_path)
    init_database(conn)
    return conn


def get_db_stats(conn: sqlite3.Connection) -> Dict[str, int]:
    """Return record counts for all major tables."""
    tables = [
        "quests",
        "units",
        "unit_spawns",
        "objects",
        "object_spawns",
        "items",
        "item_drops",
        "item_vendors",
        "zones",
        "areatriggers",
        "meta",
        "minimap",
        "professions",
    ]
    stats = {}
    for table in tables:
        try:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cur.fetchone()[0]
        except sqlite3.OperationalError:
            stats[table] = 0
    return stats
