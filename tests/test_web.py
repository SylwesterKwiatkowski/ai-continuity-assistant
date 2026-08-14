"""Web layer tests (Part C).

Uses FastAPI TestClient against create_app() with a per-test tmp SQLite database and a
pinned services clock (2026-08-14 — inside Anna's OOO window, before policy expiry) so
all delegated flows work deterministically regardless of real today.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.api.app import create_app
from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings


def login(client: TestClient, user: str = "mark") -> None:
    client.post("/login", data={"user": user}, follow_redirects=False)


@pytest.fixture()
def app(tmp_path: Path) -> FastAPI:
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings = Settings(database_url=db_url)
    application = create_app(settings)
    # Overwrite services with a pinned clock so tests don't depend on real date.
    services: AppServices = build_app_services(settings, clock=lambda: date(2026, 8, 14))
    application.state.services = services
    application.state.orchestrator = services.orchestrator
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ------------------------------------------------------------------ 1. GET /


def test_index_returns_200_with_weekly_tasks(client: TestClient) -> None:
    login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Weekly tasks" in resp.text


# ------------------------------------------------------------------ 2. POST /flows/email


def test_email_flow_allowed_contains_summary(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    assert resp.status_code == 200
    assert "allowed" in resp.text
    assert "API preparation details" in resp.text
    assert "SENTINEL_FULL_BODY_DO_NOT_LEAK" not in resp.text


# ------------------------------------------------------------------ 3. POST /flows/jira no confirm


def test_jira_without_confirm_blocked_no_write_audit(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/flows/jira",
        data={"project": "API Integration", "summary": "Test task"},
    )
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "require explicit confirmation" in body

    # Admin must show no write audit event from this flow (admin requires lucy)
    login(client, "lucy")
    admin_resp = client.get("/admin")
    assert admin_resp.status_code == 200
    assert "create_jira_issue" not in admin_resp.text


# ------------------------------------------------------------------ 4. POST /flows/jira + confirm


def test_jira_with_confirm_shows_actor(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/flows/jira",
        data={"project": "API Integration", "summary": "Test task", "confirm": "on"},
    )
    assert resp.status_code == 200
    assert "mark" in resp.text


# ------------------------------------------------------------------ 5. GET /connections + toggle


def test_connections_page_lists_gmail(client: TestClient) -> None:
    login(client)
    resp = client.get("/connections")
    assert resp.status_code == 200
    assert "gmail" in resp.text


def test_connections_toggle_anna_jira(client: TestClient, app: FastAPI) -> None:
    """Toggle Anna's Jira connection on, then off."""
    login(client, "anna")
    registry = app.state.orchestrator.connections_registry

    # Anna starts with no jira connection (not in seeds)
    from assistant.domain.enums import System

    assert registry.get("anna", System.JIRA) is None

    # First toggle: connect
    resp1 = client.post(
        "/connections/toggle",
        data={"system": "jira"},
        follow_redirects=False,
    )
    assert resp1.status_code == 303
    assert registry.get("anna", System.JIRA) is not None

    # Second toggle: disconnect
    resp2 = client.post(
        "/connections/toggle",
        data={"system": "jira"},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    assert registry.get("anna", System.JIRA) is None


# ------------------------------------------------------------------ 6. GET /admin after flows


def test_admin_shows_audit_row_after_flow(client: TestClient) -> None:
    # Run a flow to generate at least one audit event
    login(client)
    client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    login(client, "lucy")
    resp = client.get("/admin")
    assert resp.status_code == 200
    # Table headers
    assert "Active user" in resp.text or "active_user" in resp.text or "Timestamp" in resp.text
    # At least one gmail audit row
    assert "gmail" in resp.text


# ------------------------------------------------------------------ 7. lucy (no policy) → blocked


def test_lucy_no_policy_email_blocked(client: TestClient) -> None:
    login(client, "lucy")
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    assert resp.status_code == 200
    assert "blocked" in resp.text


# ------------------------------------------------------------------ 8. admin grant/deny


def _blocked_lucy_approval_id(client: TestClient) -> str:
    login(client, "lucy")
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    assert "blocked" in resp.text
    match = re.search(r"Approval request <strong>(\S+)</strong>", resp.text)
    assert match, resp.text
    return match.group(1)


def test_non_admin_cannot_grant_approval(client: TestClient) -> None:
    approval_id = _blocked_lucy_approval_id(client)
    login(client, "anna")  # anna has no admin role
    resp = client.post(f"/admin/approvals/{approval_id}/grant")
    assert resp.status_code == 403


def test_admin_grant_makes_the_blocked_read_succeed(client: TestClient, app: FastAPI) -> None:
    approval_id = _blocked_lucy_approval_id(client)

    login(client, "mark")  # also admin (post-D19 identity mapping)
    resp = client.post(f"/admin/approvals/{approval_id}/grant", follow_redirects=False)
    assert resp.status_code == 303

    approval = app.state.orchestrator.approvals.get(approval_id)
    assert approval is not None
    assert approval.status == "granted"
    assert approval.approver == "mark"

    # The identical request from lucy now succeeds, no restart needed.
    login(client, "lucy")
    resp2 = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    assert "allowed" in resp2.text


def test_admin_deny_leaves_the_read_blocked(client: TestClient, app: FastAPI) -> None:
    approval_id = _blocked_lucy_approval_id(client)

    login(client, "mark")
    resp = client.post(
        f"/admin/approvals/{approval_id}/deny",
        data={"reason": "not right now"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    approval = app.state.orchestrator.approvals.get(approval_id)
    assert approval is not None
    assert approval.status == "denied"
    assert approval.reason == "not right now"

    login(client, "lucy")
    resp2 = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
    )
    assert "blocked" in resp2.text
