"""M2 — Audit logging tests (maps to Phase-6 security items 7, 8 + transparency hook)."""

from __future__ import annotations

from datetime import UTC, datetime

from assistant.audit import AuditEvent, AuditLog, InMemoryAuditRepository
from assistant.domain import ActionType, System


class _RecordingNotifier:
    def __init__(self) -> None:
        self.notified: list[AuditEvent] = []

    def notify(self, event: AuditEvent) -> None:
        self.notified.append(event)


def make_log(notifier: _RecordingNotifier | None = None) -> AuditLog:
    return AuditLog(
        repository=InMemoryAuditRepository(),
        notifier=notifier,
        now=lambda: datetime(2026, 7, 3, 10, 30, tzinfo=UTC),
        id_factory=lambda: "fixed-id",
    )


# --- Phase-6 #7: audit events created for sensitive reads ---

def test_read_event_recorded() -> None:
    log = make_log()
    event = log.record_read(
        active_user="mark",
        target_user="anna",
        system=System.GMAIL,
        action="read_thread",
        permission_policy_used="MailboxAccessPolicy[anna]",
        reason="Anna OOO; Mark backup owner",
    )
    assert event.action_type == ActionType.READ
    assert len(log.events) == 1
    assert log.events[0].target_user == "anna"


# --- Phase-6 #8: audit events created for writes, actor = active_user ---

def test_write_event_records_actor_as_active_user() -> None:
    log = make_log()
    event = log.record_write(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="created Jira issue",
    )
    assert event.action_type == ActionType.WRITE
    assert event.actor_for_write_action == "mark"  # never the target
    assert event.target_user == "anna"


# --- transparency-to-target hook fires for delegated reads only ---

def test_transparency_hook_fires_for_delegated_read() -> None:
    notifier = _RecordingNotifier()
    log = make_log(notifier)
    log.record_read(active_user="mark", target_user="anna", system=System.GMAIL)
    assert len(notifier.notified) == 1
    assert notifier.notified[0].target_user == "anna"


def test_transparency_hook_silent_for_self_read() -> None:
    notifier = _RecordingNotifier()
    log = make_log(notifier)
    log.record_read(active_user="mark", target_user="mark", system=System.GMAIL)
    assert notifier.notified == []


def test_transparency_hook_silent_on_denied_read() -> None:
    notifier = _RecordingNotifier()
    log = make_log(notifier)
    log.record_read(
        active_user="mark", target_user="anna", system=System.GMAIL, result_status="denied"
    )
    assert notifier.notified == []
