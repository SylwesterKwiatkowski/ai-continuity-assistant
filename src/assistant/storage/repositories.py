"""SQLite-backed repository implementations for audit, approvals, connections, and policies."""

from __future__ import annotations

from assistant.audit.models import AuditEvent
from assistant.domain.enums import System
from assistant.identity.connections import Connection
from assistant.permissions.policies import (
    ApprovalRequest,
    MailboxAccessPolicy,
    TeamsAccessPolicy,
)
from assistant.storage.db import Database


class SqliteAuditRepository:
    """Append-only audit event store backed by SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, event: AuditEvent) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO audit_events (id, ts, data) VALUES (?, ?, ?)",
            (event.id, event.timestamp.isoformat(), event.model_dump_json()),
        )

    def all(self) -> list[AuditEvent]:
        rows = self._db.query("SELECT data FROM audit_events ORDER BY ts")
        return [AuditEvent.model_validate_json(row[0]) for row in rows]  # type: ignore[arg-type]


class SqliteApprovalRepository:
    """Approval request store backed by SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, req: ApprovalRequest) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO approvals (id, status, data) VALUES (?, ?, ?)",
            (req.id, req.status, req.model_dump_json()),
        )

    def get(self, approval_id: str) -> ApprovalRequest | None:
        rows = self._db.query("SELECT data FROM approvals WHERE id = ?", (approval_id,))
        if not rows:
            return None
        return ApprovalRequest.model_validate_json(rows[0][0])  # type: ignore[arg-type]

    def pending(self) -> list[ApprovalRequest]:
        rows = self._db.query("SELECT data FROM approvals WHERE status = 'pending'")
        return [ApprovalRequest.model_validate_json(row[0]) for row in rows]  # type: ignore[arg-type]


class SqliteConnectionStore:
    """Connection record store backed by SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, conn: Connection) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO connections (user_id, system, data) VALUES (?, ?, ?)",
            (conn.user_id, conn.system.value, conn.model_dump_json()),
        )

    def delete(self, user_id: str, system: System) -> None:
        self._db.execute(
            "DELETE FROM connections WHERE user_id = ? AND system = ?",
            (user_id, system.value),
        )

    def all(self) -> list[Connection]:
        rows = self._db.query("SELECT data FROM connections")
        return [Connection.model_validate_json(row[0]) for row in rows]  # type: ignore[arg-type]


class SqlitePolicyStore:
    """Policy store backed by SQLite (kind='mailbox'/'teams', key=owner/target_user)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save_mailbox(self, policies: list[MailboxAccessPolicy]) -> None:
        for p in policies:
            self._db.execute(
                "INSERT OR REPLACE INTO policies (kind, key, data) VALUES (?, ?, ?)",
                ("mailbox", p.mailbox_owner, p.model_dump_json()),
            )

    def save_teams(self, policies: list[TeamsAccessPolicy]) -> None:
        for p in policies:
            self._db.execute(
                "INSERT OR REPLACE INTO policies (kind, key, data) VALUES (?, ?, ?)",
                ("teams", p.target_user, p.model_dump_json()),
            )

    def load_mailbox(self) -> list[MailboxAccessPolicy]:
        rows = self._db.query("SELECT data FROM policies WHERE kind = 'mailbox'")
        return [MailboxAccessPolicy.model_validate_json(row[0]) for row in rows]  # type: ignore[arg-type]

    def load_teams(self) -> list[TeamsAccessPolicy]:
        rows = self._db.query("SELECT data FROM policies WHERE kind = 'teams'")
        return [TeamsAccessPolicy.model_validate_json(row[0]) for row in rows]  # type: ignore[arg-type]
