"""Audit logging (spec §15).

`AuditLog` is the write-through entry point. It stamps id/timestamp, appends to an
append-only repository, and fires the transparency-to-target hook for delegated reads
(the affected person can be told their data was accessed). The hook is a no-op by default.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from assistant.audit.models import AuditEvent
from assistant.domain.enums import ActionType, System


@runtime_checkable
class AuditRepository(Protocol):
    """Append-only store for audit events, queryable for the admin dashboard (later)."""

    def append(self, event: AuditEvent) -> None: ...

    def all(self) -> list[AuditEvent]: ...


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def all(self) -> list[AuditEvent]:
        return list(self._events)


@runtime_checkable
class TargetNotifier(Protocol):
    """Notifies a target_user that their data was accessed (transparency-to-target)."""

    def notify(self, event: AuditEvent) -> None: ...


class _NoopNotifier:
    def notify(self, event: AuditEvent) -> None:  # noqa: ARG002
        return None


class AuditLog:
    def __init__(
        self,
        repository: AuditRepository | None = None,
        notifier: TargetNotifier | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._repo: AuditRepository = repository or InMemoryAuditRepository()
        self._notifier: TargetNotifier = notifier or _NoopNotifier()
        self._now = now
        self._id_factory = id_factory

    @property
    def events(self) -> list[AuditEvent]:
        return self._repo.all()

    def record_read(
        self,
        *,
        active_user: str,
        system: System,
        target_user: str | None = None,
        action: str | None = None,
        search_query: str | None = None,
        resource_ids: Iterable[str] = (),
        resource_type: str | None = None,
        attachments_accessed: Iterable[str] = (),
        files_accessed: Iterable[str] = (),
        permission_policy_used: str | None = None,
        approval_id: str | None = None,
        result_status: str = "allowed",
        reason: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=self._id_factory(),
            timestamp=self._now(),
            active_user=active_user,
            target_user=target_user,
            action_type=ActionType.READ,
            system_accessed=system,
            action=action,
            search_query=search_query,
            resource_ids=list(resource_ids),
            resource_type=resource_type,
            attachments_accessed=list(attachments_accessed),
            files_accessed=list(files_accessed),
            permission_policy_used=permission_policy_used,
            approval_id=approval_id,
            result_status=result_status,
            reason=reason,
        )
        self._repo.append(event)
        # Transparency: notify the target when someone else read their data.
        if target_user is not None and target_user != active_user and result_status == "allowed":
            self._notifier.notify(event)
        return event

    def record_write(
        self,
        *,
        active_user: str,
        system: System,
        action: str,
        target_user: str | None = None,
        resource_ids: Iterable[str] = (),
        resource_type: str | None = None,
        permission_policy_used: str | None = None,
        approval_id: str | None = None,
        result_status: str = "success",
        reason: str | None = None,
    ) -> AuditEvent:
        # The actor for a write is ALWAYS the active_user (never the target).
        event = AuditEvent(
            id=self._id_factory(),
            timestamp=self._now(),
            active_user=active_user,
            target_user=target_user,
            action_type=ActionType.WRITE,
            system_accessed=system,
            action=action,
            resource_ids=list(resource_ids),
            resource_type=resource_type,
            permission_policy_used=permission_policy_used,
            approval_id=approval_id,
            actor_for_write_action=active_user,
            result_status=result_status,
            reason=reason,
        )
        self._repo.append(event)
        return event
