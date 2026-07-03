"""M5 — orchestrator end-to-end flows on mocks (Phase-6 #11, #12 + flagship)."""

from __future__ import annotations

from datetime import date

import pytest

from assistant.orchestrator import Orchestrator, build_default_orchestrator

# Anna's OOO window is 2026-07-01..2026-07-10; pin "today" inside it for determinism.
INSIDE_OOO = date(2026, 7, 3)
AFTER_OOO = date(2026, 7, 15)


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
