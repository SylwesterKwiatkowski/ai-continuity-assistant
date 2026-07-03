"""M3 — Connector SDK guard tests (Phase-6 #11: no connector call without authorization)."""

from __future__ import annotations

import pytest

from assistant.connectors import PermissionContext, UnauthorizedConnectorCall
from assistant.connectors.mock import (
    MockGmailConnector,
    MockJiraConnector,
    build_mock_registry,
)
from assistant.domain import ActionType, GmailAction, System
from assistant.identity import Connection
from assistant.permissions import PermissionDecision


def _allowed() -> PermissionDecision:
    return PermissionDecision(allowed=True, access_tier="delegated", reason="ok")


def _denied() -> PermissionDecision:
    return PermissionDecision(allowed=False, access_tier="delegated", reason="blocked")


def gmail_read_ctx(decision: PermissionDecision, owner: str = "anna") -> PermissionContext:
    return PermissionContext(
        active_user="mark",
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        access=ActionType.READ,
        decision=decision,
        connection=Connection(user_id=owner, system=System.GMAIL, token_ref="t"),
    )


def jira_write_ctx(connection_owner: str) -> PermissionContext:
    return PermissionContext(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="create_jira_issue",
        access=ActionType.WRITE,
        decision=_allowed(),
        connection=Connection(user_id=connection_owner, system=System.JIRA, token_ref="t"),
    )


# --- authorization backstop ---

def test_denied_decision_blocks_read() -> None:
    with pytest.raises(UnauthorizedConnectorCall):
        MockGmailConnector().search_email_metadata(gmail_read_ctx(_denied()), query="clientco")


def test_allowed_decision_permits_read() -> None:
    threads = MockGmailConnector().search_email_metadata(gmail_read_ctx(_allowed()), query="")
    assert threads and threads[0].mailbox_owner == "anna"


def test_action_mismatch_blocks() -> None:
    # Context authorizes SEARCH_METADATA but we call read_email_thread (READ_THREAD).
    ctx = gmail_read_ctx(_allowed())
    with pytest.raises(UnauthorizedConnectorCall):
        MockGmailConnector().read_email_thread(ctx, thread_id="thr-clientco-api")


def test_wrong_system_context_blocks() -> None:
    ctx = gmail_read_ctx(_allowed())  # a Gmail context
    with pytest.raises(UnauthorizedConnectorCall):
        MockJiraConnector().get_assigned_issues(ctx)  # used against Jira


# --- credential rule at the boundary (never impersonate) ---

def test_read_with_wrong_connection_owner_blocks() -> None:
    # Reading Anna's mail must use Anna's connection, not someone else's.
    ctx = gmail_read_ctx(_allowed(), owner="mark")
    with pytest.raises(UnauthorizedConnectorCall):
        MockGmailConnector().search_email_metadata(ctx, query="")


def test_write_must_use_active_user_connection() -> None:
    # A write attributed via the active_user's own connection succeeds.
    result = MockJiraConnector().create_jira_issue_as_active_user(
        jira_write_ctx("mark"), project="API", summary="Review ClientCo API requirements"
    )
    assert result.actor == "mark"


def test_write_with_target_connection_blocks() -> None:
    # Attempting a write with the target's (Anna's) connection is impersonation -> blocked.
    with pytest.raises(UnauthorizedConnectorCall):
        MockJiraConnector().create_jira_issue_as_active_user(
            jira_write_ctx("anna"), project="API", summary="x"
        )


# --- manifest coverage ---

def test_all_connectors_declare_consistent_manifests() -> None:
    registry = build_mock_registry()
    assert set(registry.keys()) == set(System)  # all seven systems present
    for system, connector in registry.items():
        manifest = connector.manifest()
        assert manifest, f"{system} has an empty manifest"
        assert all(cap.system == system for cap in manifest)
        # every connector exposes at least one read and one write capability
        accesses = {cap.access for cap in manifest}
        assert ActionType.READ in accesses and ActionType.WRITE in accesses
