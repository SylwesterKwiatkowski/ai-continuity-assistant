"""Web layer tests (Part C).

Uses FastAPI TestClient against create_app() with a pinned orchestrator
clock (2026-07-03 — inside Anna's OOO window, before policy expiry) so
all delegated flows work deterministically regardless of real today.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from assistant.api.app import create_app
from assistant.orchestrator.service import build_default_orchestrator


@pytest.fixture()
def app():
    application = create_app()
    # Overwrite orchestrator with a pinned clock so tests don't depend on real date.
    application.state.orchestrator = build_default_orchestrator(
        clock=lambda: date(2026, 7, 3)
    )
    return application


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


# ------------------------------------------------------------------ 1. GET /


def test_index_returns_200_with_weekly_tasks(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Weekly tasks" in resp.text


# ------------------------------------------------------------------ 2. POST /flows/email


def test_email_flow_allowed_contains_summary(client: TestClient) -> None:
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
        cookies={"active_user": "mark"},
    )
    assert resp.status_code == 200
    assert "allowed" in resp.text
    assert "API preparation details" in resp.text
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in resp.text


# ------------------------------------------------------------------ 3. POST /flows/jira no confirm


def test_jira_without_confirm_blocked_no_write_audit(client: TestClient, app) -> None:
    resp = client.post(
        "/flows/jira",
        data={"project": "API Integration", "summary": "Test task"},
        cookies={"active_user": "mark"},
    )
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "require explicit confirmation" in body

    # Admin must show no write audit event from this flow
    admin_resp = client.get("/admin", cookies={"active_user": "mark"})
    assert admin_resp.status_code == 200
    # Any writes in audit would show action_type "write"; verify none from jira here
    # The simplest check: no jira write appeared (create_jira_issue not in audit)
    # Because no write was executed we check by seeing "create_jira_issue" NOT in audit yet
    assert "create_jira_issue" not in admin_resp.text


# ------------------------------------------------------------------ 4. POST /flows/jira + confirm


def test_jira_with_confirm_shows_actor(client: TestClient) -> None:
    resp = client.post(
        "/flows/jira",
        data={"project": "API Integration", "summary": "Test task", "confirm": "on"},
        cookies={"active_user": "mark"},
    )
    assert resp.status_code == 200
    assert "mark" in resp.text


# ------------------------------------------------------------------ 5. GET /connections + toggle


def test_connections_page_lists_gmail(client: TestClient) -> None:
    resp = client.get("/connections", cookies={"active_user": "mark"})
    assert resp.status_code == 200
    assert "gmail" in resp.text


def test_connections_toggle_anna_jira(client: TestClient, app) -> None:
    """Toggle Anna's Jira connection on, then off."""
    registry = app.state.orchestrator.connections_registry

    # Anna starts with no jira connection (not in seeds)
    from assistant.domain.enums import System
    assert registry.get("anna", System.JIRA) is None

    # First toggle: connect
    resp1 = client.post(
        "/connections/toggle",
        data={"system": "jira"},
        cookies={"active_user": "anna"},
        follow_redirects=False,
    )
    assert resp1.status_code == 303
    assert registry.get("anna", System.JIRA) is not None

    # Second toggle: disconnect
    resp2 = client.post(
        "/connections/toggle",
        data={"system": "jira"},
        cookies={"active_user": "anna"},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    assert registry.get("anna", System.JIRA) is None


# ------------------------------------------------------------------ 6. GET /admin after flows


def test_admin_shows_audit_row_after_flow(client: TestClient) -> None:
    # Run a flow to generate at least one audit event
    client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
        cookies={"active_user": "mark"},
    )
    resp = client.get("/admin", cookies={"active_user": "mark"})
    assert resp.status_code == 200
    # Table headers
    assert "Active user" in resp.text or "active_user" in resp.text or "Timestamp" in resp.text
    # At least one gmail audit row
    assert "gmail" in resp.text


# ------------------------------------------------------------------ 7. lucy (no policy) → blocked


def test_lucy_no_policy_email_blocked(client: TestClient) -> None:
    # Switch to lucy
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
        cookies={"active_user": "lucy"},
    )
    assert resp.status_code == 200
    assert "blocked" in resp.text
