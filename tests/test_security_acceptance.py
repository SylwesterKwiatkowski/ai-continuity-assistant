"""Phase-6 security acceptance gate — 12 named invariant tests (P6-01 … P6-12).

Fixed dates:
  - Anna OOO window: 2026-08-10..2026-08-24 (mock calendar)
  - Seed policies expire: 2026-10-31
  - INSIDE_OOO (allowed scenario): 2026-08-14
  - AFTER_OOO ("not OOO" scenario): 2026-09-05
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from assistant.audit.log import AuditLog
from assistant.connectors import PermissionContext, UnauthorizedConnectorCall
from assistant.connectors.mock import MockGmailConnector, MockJiraConnector, build_mock_registry
from assistant.domain import ActionType, GmailAction, System
from assistant.identity import Connection
from assistant.identity.connections import ConnectionRegistry
from assistant.identity.resolver import IdentityResolver
from assistant.orchestrator import Orchestrator, build_default_orchestrator
from assistant.orchestrator.service import _CalendarAbsence  # noqa: PLC2701 — needed for wiring
from assistant.permissions import (
    PermissionEngine,
    PermissionRequest,
    RequestedScope,
)
from assistant.permissions.policies import PermissionDecision
from assistant.summarizer.stub import StubSummarizer

INSIDE_OOO = date(2026, 8, 14)   # clock inside Anna's OOO window → allowed
AFTER_OOO = date(2026, 9, 5)   # clock after OOO → not OOO → denied


# ---------------------------------------------------------------------------
# Local absence stubs (avoid depending on private _CalendarAbsence directly)
# ---------------------------------------------------------------------------

class _AnaOOOStub:
    """Anna is always out of office."""

    def is_out_of_office(self, user_id: str) -> bool:
        return user_id == "anna"


class _NobodyOOOStub:
    """Nobody is out of office."""

    def is_out_of_office(self, user_id: str) -> bool:  # noqa: ARG002
        return False


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_engine(*, anna_ooo: bool = True, today: date = INSIDE_OOO) -> PermissionEngine:
    stub = _AnaOOOStub() if anna_ooo else _NobodyOOOStub()
    return PermissionEngine.from_seed(
        resolver=IdentityResolver.from_seed(),
        absence_provider=stub,
        clock=lambda: today,
    )


def _gmail_read_req(active_user: str = "mark", **extra: object) -> PermissionRequest:
    return PermissionRequest(
        active_user=active_user,
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        action_type=ActionType.READ,
        scope=RequestedScope(
            client="ClientCo",
            project="API Integration",
            domain="clientco.com",
            **extra,  # type: ignore[arg-type]
        ),
    )


def _denied_decision() -> PermissionDecision:
    return PermissionDecision(allowed=False, access_tier="delegated", reason="blocked")


def _allowed_decision() -> PermissionDecision:
    return PermissionDecision(allowed=True, access_tier="delegated", reason="ok")


def _build_orchestrator_with_audit(
    *, anna_ooo: bool = True, today: date = INSIDE_OOO
) -> tuple[Orchestrator, AuditLog]:
    """Build an orchestrator wired to a held AuditLog, mirroring build_default_orchestrator."""
    resolver = IdentityResolver.from_seed()
    registry = ConnectionRegistry.from_seed()
    connectors = build_mock_registry()
    from assistant.connectors.protocols import CalendarPort
    calendar = cast(CalendarPort, connectors[System.CALENDAR])
    absence = _CalendarAbsence(calendar, lambda: today)
    engine = PermissionEngine.from_seed(
        resolver=resolver,
        absence_provider=absence,
        clock=lambda: today,
    )
    audit = AuditLog()
    orch = Orchestrator(
        resolver=resolver,
        registry=registry,
        engine=engine,
        connectors=connectors,
        summarizer=StubSummarizer(),
        audit=audit,
    )
    return orch, audit


# ===========================================================================
# P6-01: a user cannot read another user's Gmail without permission
# ===========================================================================

def test_p6_01_unauthorized_user_cannot_read_another_gmail() -> None:
    engine = _make_engine()
    req = PermissionRequest(
        active_user="lucy",      # lucy is NOT an allowed requester on Anna's mailbox
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        action_type=ActionType.READ,
        scope=RequestedScope(client="ClientCo", project="API Integration"),
    )
    decision = engine.check(req)
    assert decision.allowed is False


# ===========================================================================
# P6-02: scoped Gmail read allowed with a valid policy (mark, anna, inside OOO)
# ===========================================================================

def test_p6_02_scoped_gmail_read_allowed_with_valid_policy() -> None:
    orch = build_default_orchestrator(clock=lambda: INSIDE_OOO)
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is True


# ===========================================================================
# P6-03: Teams read outside allowed scope denied
# ===========================================================================

def test_p6_03_teams_read_outside_scope_denied() -> None:
    orch = build_default_orchestrator(clock=lambda: INSIDE_OOO)
    resp = orch.search_teams(
        "mark", "Anna",
        client="ClientCo",
        project="API Integration",
        channels=["Random Private Chat"],
    )
    assert resp.allowed is False


# ===========================================================================
# P6-04: Teams project context readable when permitted
# ===========================================================================

def test_p6_04_teams_project_context_readable_when_permitted() -> None:
    orch = build_default_orchestrator(clock=lambda: INSIDE_OOO)
    resp = orch.search_teams(
        "mark", "Anna",
        client="ClientCo",
        project="API Integration",
        channels=["ClientCo Delivery"],
        keywords=["endpoint"],
    )
    assert resp.allowed is True


# ===========================================================================
# P6-05: a write executes only as active_user
# ===========================================================================

def test_p6_05_write_executes_only_as_active_user() -> None:
    orch = build_default_orchestrator(clock=lambda: INSIDE_OOO)
    resp = orch.create_jira_task(
        "mark", project="API", summary="Review requirements"
    )
    assert resp.allowed is True
    assert resp.actions_taken, "expected at least one action_taken entry"
    assert all("as mark" in action for action in resp.actions_taken)


# ===========================================================================
# P6-06: a write is never executed as target_user (two layers)
# ===========================================================================

def test_p6_06_write_never_executed_as_target_user() -> None:
    # Layer (a): PermissionEngine blocks write with actor == target
    engine = _make_engine()
    req = PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="create_jira_issue",
        action_type=ActionType.WRITE,
        actor="anna",    # attempted impersonation
    )
    decision = engine.check(req)
    assert decision.allowed is False

    # Layer (b): connector-level guard blocks write when connection.user_id != active_user
    write_ctx = PermissionContext(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="create_jira_issue",
        access=ActionType.WRITE,
        decision=_allowed_decision(),
        connection=Connection(user_id="anna", system=System.JIRA, token_ref="t"),  # anna's token
    )
    with pytest.raises(UnauthorizedConnectorCall):
        MockJiraConnector().create_jira_issue_as_active_user(
            write_ctx, project="API", summary="impersonation attempt"
        )


# ===========================================================================
# P6-07: audit events created for sensitive reads
# ===========================================================================

def test_p6_07_audit_events_created_for_sensitive_reads() -> None:
    orch, audit = _build_orchestrator_with_audit(anna_ooo=True, today=INSIDE_OOO)
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is True

    gmail_read_events = [
        e for e in audit.events
        if e.system_accessed == System.GMAIL
        and e.action_type == ActionType.READ
        and e.result_status == "allowed"
        and e.active_user == "mark"
        and e.target_user == "anna"
    ]
    assert gmail_read_events, "expected at least one allowed gmail READ audit event"


# ===========================================================================
# P6-08: audit events created for writes
# ===========================================================================

def test_p6_08_audit_events_created_for_writes() -> None:
    orch, audit = _build_orchestrator_with_audit(today=INSIDE_OOO)
    resp = orch.create_jira_task("mark", project="API", summary="Audit write test")
    assert resp.allowed is True

    write_events = [
        e for e in audit.events
        if e.action_type == ActionType.WRITE
        and e.actor_for_write_action == "mark"
    ]
    assert write_events, "expected at least one WRITE audit event attributed to mark"


# ===========================================================================
# P6-09: permission denial returns a safe response (no sensitive data leaked)
# ===========================================================================

def test_p6_09_permission_denial_returns_safe_response() -> None:
    orch = build_default_orchestrator(clock=lambda: AFTER_OOO)   # Anna back in office → denied
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is False

    sensitive_strings = [
        "API preparation details",
        "SENTINEL_FULL_BODY_DO_NOT_LEAK",
        "mail.google.com",
    ]
    for sentinel in sensitive_strings:
        assert sentinel not in resp.summary, f"safe response must not contain {sentinel!r}"
        for src in resp.sources:
            assert sentinel not in src, f"safe response sources must not contain {sentinel!r}"


# ===========================================================================
# P6-10: ambiguous/missing permission triggers approval flow
# ===========================================================================

def test_p6_10_blocked_permission_triggers_approval_flow() -> None:
    orch = build_default_orchestrator(clock=lambda: AFTER_OOO)   # blocked → approval offered
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is False
    assert resp.approval_required is not None
    assert resp.approval_id is not None

    pending = orch.approvals.pending()
    assert len(pending) == 1
    assert pending[0].status == "pending"


# ===========================================================================
# P6-11: orchestrator does not call connectors without permission validation
# ===========================================================================

def test_p6_11_no_connector_call_without_permission() -> None:
    # Structural: connector raises when decision.allowed is False.
    denied_ctx = PermissionContext(
        active_user="mark",
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        access=ActionType.READ,
        decision=_denied_decision(),
        connection=Connection(user_id="anna", system=System.GMAIL, token_ref="t"),
    )
    with pytest.raises(UnauthorizedConnectorCall):
        MockGmailConnector().search_email_metadata(denied_ctx, query="test")

    # End-to-end: a blocked orchestrator flow must not produce any allowed READ audit event.
    # Use AFTER_OOO so the calendar-backed absence provider says Anna is not OOO → denied.
    orch, audit = _build_orchestrator_with_audit(today=AFTER_OOO)
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is False
    assert not resp.sources, "denied response must return no sources"

    allowed_gmail_events = [
        e for e in audit.events
        if e.system_accessed == System.GMAIL
        and e.result_status == "allowed"
    ]
    assert not allowed_gmail_events, (
        "audit log must not contain any allowed gmail READ event when access was denied"
    )


# ===========================================================================
# P6-12: summaries do not expose raw sensitive content
# ===========================================================================

def test_p6_12_summaries_do_not_expose_raw_sensitive_content() -> None:
    orch = build_default_orchestrator(clock=lambda: INSIDE_OOO)

    # search_email summary must not contain sentinel strings
    email_resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert email_resp.allowed is True
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in email_resp.summary
    assert "555-0100" not in email_resp.summary

    # flagship combined flow must not contain sentinel strings
    flagship_resp = orch.flagship("mark", "Anna", client="ClientCo", project="API Integration")
    assert flagship_resp.allowed is True
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in flagship_resp.summary
    assert "555-0100" not in flagship_resp.summary
