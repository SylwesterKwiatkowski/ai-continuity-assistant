"""Thin SQLite wrapper with per-connection locking (thread-safe) and schema migrations.

DECISIONS.md D22: schema changes are versioned migrations, not edits to a single
executescript. `CREATE TABLE IF NOT EXISTS` inside a migration makes it safe to run
against a database that already has the table (e.g. the deployed host's pre-migration
file) — applying it just records the version, without touching existing rows.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime

# Each migration is (version, sql). Append-only: never edit a shipped migration — add a
# new one instead, even to fix a mistake, so a database that already applied the old
# version doesn't silently diverge from one that hasn't.
_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS policies (
            kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (kind, key)
        );
        CREATE TABLE IF NOT EXISTS connections (
            user_id TEXT NOT NULL, system TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (user_id, system)
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token_ref TEXT PRIMARY KEY, ciphertext BLOB NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS people (
            id TEXT PRIMARY KEY, data TEXT NOT NULL
        );
        """,
    ),
]


class Database:
    def __init__(
        self, path: str, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._now = now
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        self._conn.commit()
        self._run_migrations()

    def _run_migrations(self) -> None:
        applied = {
            row[0] for row in self._conn.execute("SELECT version FROM schema_migrations")
        }
        for version, sql in _MIGRATIONS:
            if version in applied:
                continue
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, self._now().isoformat()),
            )
            self._conn.commit()

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def database_from_url(url: str) -> Database:
    """Construct a Database from a sqlite:///path or bare path."""
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    else:
        path = url
    return Database(path)
