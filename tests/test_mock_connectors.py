"""M3 — functional checks on the mock connectors (flagship fixtures)."""

from __future__ import annotations

from datetime import date

from assistant.connectors import PermissionContext
from assistant.connectors.mock import (
    MockCalendarConnector,
    MockGmailConnector,
    MockJiraConnector,
    MockTeamsConnector,
)
from assistant.domain import ActionType, GmailAction, System, TeamsAction
from assistant.identity import Connection
from assistant.permissions import PermissionDecision


def _ctx(system: System, action: str, access: ActionType, owner: str) -> PermissionContext:
    return PermissionContext(
        active_user="mark",
        target_user="anna",
        system=system,
        action=action,
        access=access,
        decision=PermissionDecision(allowed=True, access_tier="delegated", reason="ok"),
        connection=Connection(user_id=owner, system=system, token_ref="t"),
    )


def test_gmail_search_returns_clientco_thread() -> None:
    ctx = _ctx(System.GMAIL, GmailAction.SEARCH_METADATA, ActionType.READ, "anna")
    threads = MockGmailConnector().search_email_metadata(ctx, query="clientco api")
    assert len(threads) == 1
    assert threads[0].subject == "API preparation details"
    assert {a.filename for a in threads[0].attachments} == {
        "ClientCo_API_Integration_Brief.pdf",
        "Webhook_Requirements.xlsx",
    }


def test_teams_search_finds_annas_thread() -> None:
    ctx = _ctx(System.TEAMS, TeamsAction.SEARCH_MESSAGES, ActionType.READ, "anna")
    threads = MockTeamsConnector().search_teams_messages(ctx, keywords=["endpoint"])
    assert threads[0].channel == "ClientCo Delivery"
    assert threads[0].related_client == "ClientCo"


def test_calendar_reports_anna_out_of_office() -> None:
    cal = MockCalendarConnector()
    assert cal.is_out_of_office("anna", on=date(2026, 8, 14)) is True
    assert cal.is_out_of_office("anna", on=date(2026, 9, 1)) is False
    assert cal.is_out_of_office("mark", on=date(2026, 8, 14)) is False


def test_get_blockers_with_today_overdue() -> None:
    ctx = _ctx(System.JIRA, "get_blockers", ActionType.READ, "mark")
    tasks = MockJiraConnector().get_blockers(ctx, today=date(2026, 8, 14))
    assert [t.id for t in tasks] == ["CRM-241"]


def test_get_blockers_with_today_not_yet_overdue() -> None:
    ctx = _ctx(System.JIRA, "get_blockers", ActionType.READ, "mark")
    tasks = MockJiraConnector().get_blockers(ctx, today=date(2026, 6, 1))
    assert tasks == []
