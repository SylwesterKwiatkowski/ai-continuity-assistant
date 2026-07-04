"""Authentication tests: session cookies, login/logout, admin gate, dev-mode toggle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.api.app import create_app
from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings
from assistant.identity.sessions import SessionManager


def _make_app(tmp_path: Path, auth_mode: str = "dev") -> tuple[FastAPI, AppServices]:
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings = Settings(database_url=db_url, auth_mode=auth_mode)  # type: ignore[arg-type]
    app = create_app(settings)
    services = build_app_services(settings)
    app.state.services = services
    app.state.orchestrator = services.orchestrator
    return app, services


def login(client: TestClient, user: str = "mark") -> None:
    client.post("/login", data={"user": user}, follow_redirects=False)


# ------------------------------------------------------------------ unauthenticated access


def test_unauthenticated_get_index_redirects(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_unauthenticated_post_flows_email_redirects(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post(
        "/flows/email",
        data={"target": "Anna", "client": "ClientCo", "project": "API Integration"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # No audit events should exist
    assert services.orchestrator.audit.events == []


# ------------------------------------------------------------------ authenticated login


def test_login_as_mark_shows_mark(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "mark")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mark" in resp.text


# ------------------------------------------------------------------ forged/tampered sessions


def test_forged_session_cookie_treated_as_unauthenticated(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    # Get a valid token then tamper the signature
    sm = services.session_manager
    valid_token = sm.issue("mark")
    b64, sig = valid_token.rsplit(".", 1)
    tampered = f"{b64}.{sig[:-4]}XXXX"
    client.cookies.set("session", tampered)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303


def test_wrong_key_session_cookie_treated_as_unauthenticated(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    # Issue token with a different secret
    wrong_sm = SessionManager("wrong-secret")
    wrong_token = wrong_sm.issue("anna")
    client.cookies.set("session", wrong_token)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303


# ------------------------------------------------------------------ SessionManager unit tests


def test_session_manager_expired_token_returns_none() -> None:
    issue_now = datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC)
    sm = SessionManager("secret", ttl_hours=8, now=lambda: issue_now)
    token = sm.issue("mark")
    # Verify 9 hours later -> expired
    later_now = datetime(2026, 7, 3, 21, 0, 1, tzinfo=UTC)
    sm2 = SessionManager("secret", ttl_hours=8, now=lambda: later_now)
    assert sm2.verify(token) is None


def test_session_manager_verify_none_returns_none() -> None:
    sm = SessionManager("secret")
    assert sm.verify(None) is None


def test_session_manager_verify_garbage_returns_none() -> None:
    sm = SessionManager("secret")
    assert sm.verify("garbage") is None
    assert sm.verify("a.b.c") is None


def test_session_manager_verify_swapped_sig_returns_none() -> None:
    sm = SessionManager("secret")
    token = sm.issue("mark")
    b64, sig = token.rsplit(".", 1)
    # Swap last char
    swapped = f"{b64}.{sig[:-1]}{'X' if sig[-1] != 'X' else 'Y'}"
    assert sm.verify(swapped) is None


def test_session_manager_valid_token_returns_user() -> None:
    sm = SessionManager("secret")
    token = sm.issue("mark")
    assert sm.verify(token) == "mark"


# ------------------------------------------------------------------ admin access


def test_non_admin_mark_gets_403_on_admin(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "mark")
    resp = client.get("/admin")
    assert resp.status_code == 403


def test_admin_lucy_gets_200_on_admin(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "lucy")
    resp = client.get("/admin")
    assert resp.status_code == 200


# ------------------------------------------------------------------ dev login disabled


def test_dev_login_disabled_post_login_returns_403(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, auth_mode="oauth")
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post("/login", data={"user": "mark"})
    assert resp.status_code == 403


def test_dev_login_disabled_get_login_shows_no_form(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, auth_mode="oauth")
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "not configured" in resp.text
