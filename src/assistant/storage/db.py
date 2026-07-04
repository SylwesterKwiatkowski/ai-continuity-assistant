"""Thin SQLite wrapper with per-connection locking (thread-safe)."""

from __future__ import annotations

import sqlite3
import threading


class Database:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript("""
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
        """)
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
