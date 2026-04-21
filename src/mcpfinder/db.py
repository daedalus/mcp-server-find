"""SQLite database with FTS5 full-text search for MCP servers."""

import os
import sqlite3
from datetime import UTC
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS servers (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    registry_type TEXT,
    package_identifier TEXT,
    transport_type TEXT,
    repository_url TEXT,
    repository_source TEXT,
    published_at TEXT,
    updated_at TEXT,
    status TEXT DEFAULT 'active',
    popularity_score REAL DEFAULT 0,
    categories TEXT DEFAULT '[]',
    keywords TEXT DEFAULT '[]',
    remote_url TEXT,
    has_remote INTEGER DEFAULT 0,
    last_synced_at TEXT,
    sources TEXT DEFAULT '[]',
    raw_data TEXT,
    env_vars TEXT DEFAULT '[]',
    source TEXT DEFAULT 'official',
    use_count INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    icon_url TEXT,
    deprecated_npm INTEGER,
    archived_repo INTEGER
);

CREATE INDEX IF NOT EXISTS idx_servers_slug ON servers(slug);
CREATE INDEX IF NOT EXISTS idx_servers_popularity ON servers(popularity_score DESC);
CREATE INDEX IF NOT EXISTS idx_servers_updated ON servers(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status);

CREATE VIRTUAL TABLE IF NOT EXISTS servers_fts USING fts5(
    name,
    description,
    keywords,
    content=servers,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS servers_ai AFTER INSERT ON servers BEGIN
    INSERT INTO servers_fts(rowid, name, description, keywords)
    VALUES (new.rowid, new.name, new.description, new.keywords);
END;

CREATE TRIGGER IF NOT EXISTS servers_ad AFTER DELETE ON servers BEGIN
    INSERT INTO servers_fts(servers_fts, rowid, name, description, keywords)
    VALUES ('delete', old.rowid, old.name, old.description, old.keywords);
END;

CREATE TRIGGER IF NOT EXISTS servers_au AFTER UPDATE ON servers BEGIN
    INSERT INTO servers_fts(servers_fts, rowid, name, description, keywords)
    VALUES ('delete', old.rowid, old.name, old.description, old.keywords);
    INSERT INTO servers_fts(rowid, name, description, keywords)
    VALUES (new.rowid, new.name, new.description, new.keywords);
END;

CREATE TABLE IF NOT EXISTS sync_log (
    source TEXT PRIMARY KEY,
    last_synced_at TEXT NOT NULL,
    server_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok',
    error TEXT
);
"""


def get_data_dir() -> str:
    """Get the data directory for MCPfinder."""
    data_dir = os.environ.get("MCPFINDER_DATA_DIR")
    if data_dir:
        return data_dir
    home = os.path.expanduser("~")
    return os.path.join(home, ".mcpfinder")


def init_database(db_path: str | None = None) -> sqlite3.Connection:
    """Initialize and return a SQLite database with FTS5 schema."""
    if db_path is None:
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "data.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript(SCHEMA_SQL)
    conn.commit()

    return conn


def get_last_sync_timestamp(conn: sqlite3.Connection, source: str) -> str | None:
    """Get the last sync timestamp for a source."""
    cursor = conn.execute(
        "SELECT last_synced_at FROM sync_log WHERE source = ?", (source,)
    )
    row = cursor.fetchone()
    return row["last_synced_at"] if row else None


def update_sync_log(
    conn: sqlite3.Connection,
    source: str,
    server_count: int,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Update sync log for a source."""
    conn.execute(
        """INSERT OR REPLACE INTO sync_log
           (source, last_synced_at, server_count, status, error)
           VALUES (?, ?, ?, ?, ?)""",
        (source, _iso_now(), server_count, status, error),
    )
    conn.commit()


def _iso_now() -> str:
    """Get current ISO timestamp."""
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a dictionary."""
    return dict(row)


def get_server_count(conn: sqlite3.Connection) -> int:
    """Get total server count in the database."""
    cursor = conn.execute("SELECT COUNT(*) as count FROM servers")
    row = cursor.fetchone()
    return row["count"] if row else 0


def is_sync_needed(conn: sqlite3.Connection, max_age_minutes: int = 15) -> bool:
    """Check if sync is needed."""
    last_sync = get_last_sync_timestamp(conn, "official")
    if not last_sync:
        return True

    from datetime import datetime

    last_sync_date = datetime.fromisoformat(last_sync)
    now = datetime.now(UTC)
    diff_minutes = (now - last_sync_date).total_seconds() / 60

    return diff_minutes >= max_age_minutes
