"""Google OAuth login provider tests (DECISIONS.md D19).

Google's endpoints are mocked via httpx.MockTransport — no real network calls, and the
flow stays deterministic for CI.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.api.app import create_app
from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings
from assistant.identity.oauth import GoogleOAuthError, GoogleOAuthProvider
from assistant.identity.resolver import IdentityResolver

# Read live from the seed rather than hardcoding a literal — keeps this test correct
# (and free of any real person's email in the test source) regardless of who "mark" is
# mapped to in seeds/people.json.
_MARK_EMAIL = IdentityResolver.from_seed().by_id("mark").email


def _make_app(tmp_path: Path, transport: httpx.MockTransport) -> tuple[FastAPI, AppServices]:
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings = Settings(
        database_url=db_url,
        auth_mode="oauth",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost:8000/auth/google/callback",
    )
    app = create_app(settings)
    services = build_app_services(settings)
    provider = GoogleOAuthProvider(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
        client=httpx.Client(transport=transport),
    )
    services = replace(services, oauth_provider=provider)
    app.state.services = services
    app.state.orchestrator = services.orchestrator
    return app, services


def _handler_success(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        return httpx.Response(200, json={"access_token": "fake-access-token"})
    if request.url.path == "/v1/userinfo":
        return httpx.Response(200, json={"email": _MARK_EMAIL, "email_verified": True})
    raise AssertionError(f"unexpected request to {request.url}")


# ------------------------------------------------------------------ /auth/google/login


def test_google_login_redirects_to_google_with_state_cookie(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, httpx.MockTransport(lambda r: httpx.Response(404)))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    assert client.cookies.get("oauth_state") is not None


def test_google_login_disabled_in_dev_mode(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path}/test.db"
    app = create_app(Settings(database_url=db_url, auth_mode="dev"))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 403


def test_google_login_disabled_when_not_configured(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path}/test.db"
    app = create_app(Settings(database_url=db_url, auth_mode="oauth"))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 403


# ------------------------------------------------------------------ /auth/google/callback


def test_google_callback_success_issues_session_for_matching_person(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, httpx.MockTransport(_handler_success))
    client = TestClient(app, raise_server_exceptions=True)

    # Drive the real /auth/google/login redirect first so the state cookie is one the
    # server actually issued (matches domain/scoping — a hand-set client-side cookie
    # wouldn't be replaced by the callback's delete_cookie the same way a real browser's
    # would).
    login_resp = client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    resp = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert client.cookies.get("session") is not None
    assert client.cookies.get("oauth_state") is None


def test_google_callback_state_mismatch_rejected_no_session(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, httpx.MockTransport(_handler_success))
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set("oauth_state", "expected-state")
    resp = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": "wrong-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "expired or invalid" in resp.text.lower()
    assert client.cookies.get("session") is None


def test_google_callback_unregistered_email_refused_no_session(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-access-token"})
        if request.url.path == "/v1/userinfo":
            return httpx.Response(
                200, json={"email": "stranger@example.com", "email_verified": True}
            )
        raise AssertionError(f"unexpected request to {request.url}")

    app, _ = _make_app(tmp_path, httpx.MockTransport(handler))
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set("oauth_state", "the-state")
    resp = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": "the-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "not registered" in resp.text.lower()
    assert client.cookies.get("session") is None


def test_google_callback_unverified_email_refused(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-access-token"})
        if request.url.path == "/v1/userinfo":
            return httpx.Response(200, json={"email": _MARK_EMAIL, "email_verified": False})
        raise AssertionError(f"unexpected request to {request.url}")

    app, _ = _make_app(tmp_path, httpx.MockTransport(handler))
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set("oauth_state", "the-state")
    resp = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": "the-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "could not verify" in resp.text.lower()
    assert client.cookies.get("session") is None


def test_google_callback_denied_by_user_shows_message(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, httpx.MockTransport(lambda r: httpx.Response(404)))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(
        "/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "cancelled or denied" in resp.text.lower()
    assert client.cookies.get("session") is None


def test_google_callback_disabled_in_dev_mode(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path}/test.db"
    app = create_app(Settings(database_url=db_url, auth_mode="dev"))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get(
        "/auth/google/callback", params={"code": "x", "state": "y"}, follow_redirects=False
    )
    assert resp.status_code == 403


# ------------------------------------------------------------------ login page rendering


def test_login_page_shows_google_button_when_configured(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path, httpx.MockTransport(lambda r: httpx.Response(404)))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "/auth/google/login" in resp.text
    assert "not configured yet" not in resp.text


def test_login_page_shows_placeholder_when_not_configured(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path}/test.db"
    app = create_app(Settings(database_url=db_url, auth_mode="oauth"))
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "not configured yet" in resp.text


# ------------------------------------------------------------------ GoogleOAuthProvider (unit)


def test_authorization_url_contains_required_params() -> None:
    provider = GoogleOAuthProvider(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8000/auth/google/callback",
    )
    url = provider.authorization_url("state123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url
    assert "state=state123" in url
    assert "redirect_uri=" in url
    assert "scope=openid" in url


def test_new_state_is_unguessable_and_unique() -> None:
    a = GoogleOAuthProvider.new_state()
    b = GoogleOAuthProvider.new_state()
    assert a != b
    assert len(a) > 16


def test_resolve_login_email_success() -> None:
    provider = GoogleOAuthProvider(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8000/auth/google/callback",
        client=httpx.Client(transport=httpx.MockTransport(_handler_success)),
    )
    assert provider.resolve_login_email("some-code") == _MARK_EMAIL


def test_exchange_code_failure_raises_google_oauth_error() -> None:
    provider = GoogleOAuthProvider(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8000/auth/google/callback",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400))),
    )
    with pytest.raises(GoogleOAuthError):
        provider.resolve_login_email("bad-code")


def test_userinfo_failure_raises_google_oauth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "fake-access-token"})
        return httpx.Response(500)

    provider = GoogleOAuthProvider(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8000/auth/google/callback",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GoogleOAuthError):
        provider.resolve_login_email("some-code")
