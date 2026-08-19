"""M5 — orchestrator end-to-end flows on mocks (Phase-6 #11, #12 + flagship)."""

from __future__ import annotations

from datetime import date

import pytest

from assistant.orchestrator import Orchestrator, build_default_orchestrator
from assistant.permissions import ApprovalAlreadyDecided, ApprovalNotFound

# Anna's OOO window is 2026-08-10..2026-08-24; pin "today" inside it for determinism.
INSIDE_OOO = date(2026, 8, 14)
AFTER_OOO = date(2026, 9, 5)


@pytest.fixture
def orch() -> Orchestrator:
    return build_default_orchestrator(clock=lambda: INSIDE_OOO)


# --- weekly tasks (delegated lower-sensitivity reads) ---

def test_weekly_tasks_summarizes_and_audits(orch: Orchestrator) -> None:
    resp = orch.weekly_tasks("mark", "Anna")
    assert resp.allowed
    assert "CRM-241" in resp.summary  # from Jira
    assert "Weekly data validation" in resp.summary  # from Sheets
    assert resp.audit_event_ids  # reads were logged


# --- delegated Gmail search: allowed in scope, and does NOT leak the raw body ---

def test_search_email_allowed_in_scope(orch: Orchestrator) -> None:
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed
    assert "API preparation details" in resp.summary
    assert any("mail.google.com" in s for s in resp.sources)


def test_search_email_does_not_expose_raw_body(orch: Orchestrator) -> None:
    # Phase-6 #12: the summary must not dump the full (sensitive) email body.
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in resp.summary
    assert "555-0100" not in resp.summary  # unrelated personal content stays hidden


# --- delegated Gmail search: blocked out of scope / not OOO ---

def test_search_email_blocked_when_not_out_of_office() -> None:
    orch = build_default_orchestrator(clock=lambda: AFTER_OOO)  # Anna back in office
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is False
    assert resp.approval_required is not None
    assert "request approval" in resp.summary.lower()


def test_search_email_blocked_creates_approval_request() -> None:
    orch = build_default_orchestrator(clock=lambda: AFTER_OOO)  # Anna back in office
    resp = orch.search_email("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed is False
    assert resp.approval_id is not None
    pending = orch.approvals.pending()
    assert len(pending) == 1
    assert pending[0].requester == "mark"
    assert pending[0].target_user == "anna"


def test_search_email_blocked_out_of_scope(orch: Orchestrator) -> None:
    resp = orch.search_email("mark", "Anna", client="OtherCorp", project="Different")
    assert resp.allowed is False


# --- grant/deny (v0.4 / D20 / D21): decisions on a blocked delegated read ---


def _blocked_mark_approval_id(blocked_orch: Orchestrator) -> str:
    blocked = blocked_orch.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )
    approval_id = blocked.approval_id
    assert approval_id is not None
    return approval_id


def test_grant_approval_allows_the_previously_blocked_read() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)  # Anna back in office
    approval_id = _blocked_mark_approval_id(blocked_orch)

    # Anna is the nominated approver for her own mailbox — deciding her own request.
    decided = blocked_orch.grant_approval(approval_id, decided_by="anna")
    assert decided.status == "granted"
    assert decided.approver == "anna"  # nomination is untouched
    assert decided.decided_by == "anna"  # she decided it herself, no override
    assert decided.decided_at == AFTER_OOO

    # The identical request now succeeds — no restart needed.
    resp = blocked_orch.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )
    assert resp.allowed is True


def test_grant_approval_is_scoped_to_the_requester_only() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    approval_id = _blocked_mark_approval_id(blocked_orch)
    blocked_orch.grant_approval(approval_id, decided_by="anna")

    # Lucy herself never asked for access and wasn't granted any — still blocked.
    still_blocked = blocked_orch.search_email(
        "lucy", "Anna", client="ClientCo", project="API Integration"
    )
    assert still_blocked.allowed is False


def test_grant_approval_emits_an_auditable_decision() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    approval_id = _blocked_mark_approval_id(blocked_orch)
    blocked_orch.grant_approval(approval_id, decided_by="anna")

    grant_events = [e for e in blocked_orch.audit.events if e.action == "grant_delegated_access"]
    assert grant_events
    assert grant_events[0].active_user == "anna"
    assert grant_events[0].target_user == "anna"
    assert grant_events[0].approval_id == approval_id
    assert "OVERRIDE" not in (grant_events[0].reason or "")


def test_admin_grant_is_recorded_as_an_override() -> None:
    """D21: an admin deciding someone else's nominated request is a distinguishable override."""
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    approval_id = _blocked_mark_approval_id(blocked_orch)

    # Lucy is admin but NOT the nominated approver (anna is) — this is an override.
    decided = blocked_orch.grant_approval(approval_id, decided_by="lucy")
    assert decided.approver == "anna"  # nomination is preserved
    assert decided.decided_by == "lucy"  # lucy is who actually decided

    grant_events = [e for e in blocked_orch.audit.events if e.action == "grant_delegated_access"]
    assert grant_events
    assert grant_events[0].active_user == "lucy"
    assert "OVERRIDE" in (grant_events[0].reason or "")
    assert "anna" in (grant_events[0].reason or "")


def test_deny_approval_leaves_the_read_blocked() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    approval_id = _blocked_mark_approval_id(blocked_orch)

    decided = blocked_orch.deny_approval(approval_id, decided_by="anna", reason="not now")
    assert decided.status == "denied"
    assert decided.reason == "not now"
    assert decided.decided_by == "anna"

    resp = blocked_orch.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )
    assert resp.allowed is False


def test_grant_approval_unknown_id_raises_not_found() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    with pytest.raises(ApprovalNotFound):
        blocked_orch.grant_approval("does-not-exist", decided_by="anna")


def test_granting_an_already_decided_approval_raises() -> None:
    blocked_orch = build_default_orchestrator(clock=lambda: AFTER_OOO)
    approval_id = _blocked_mark_approval_id(blocked_orch)
    blocked_orch.grant_approval(approval_id, decided_by="anna")

    with pytest.raises(ApprovalAlreadyDecided):
        blocked_orch.grant_approval(approval_id, decided_by="anna")
    with pytest.raises(ApprovalAlreadyDecided):
        blocked_orch.deny_approval(approval_id, decided_by="anna")


# --- delegated Teams search ---

def test_search_teams_allowed_in_scope(orch: Orchestrator) -> None:
    resp = orch.search_teams(
        "mark", "Anna", client="ClientCo", project="API Integration",
        channels=["ClientCo Delivery"], keywords=["endpoint"],
    )
    assert resp.allowed
    assert "ClientCo Delivery" in resp.summary


# --- write as active_user ---

def test_create_jira_task_runs_as_active_user(orch: Orchestrator) -> None:
    resp = orch.create_jira_task("mark", project="API", summary="Review requirements")
    assert resp.allowed
    assert any("as mark" in a for a in resp.actions_taken)
    assert "active_user" in resp.note


# --- flagship combined flow ---

def test_flagship_reads_then_writes_as_active_user(orch: Orchestrator) -> None:
    resp = orch.flagship("mark", "Anna", client="ClientCo", project="API Integration")
    assert resp.allowed
    # read summary present from both systems
    assert "API preparation details" in resp.summary
    assert "ClientCo Delivery" in resp.summary
    # a write happened, attributed to Mark, never Anna
    assert resp.actions_taken and all("as mark" in a for a in resp.actions_taken)
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in resp.summary
    # reads (gmail, teams) + write (jira) all audited
    assert len(resp.audit_event_ids) >= 3
