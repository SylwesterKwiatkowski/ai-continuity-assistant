"""Web UI routes — server-rendered Jinja2 + HTMX (with plain form POST fallback).

Authentication is handled via signed session cookies (see identity/sessions.py).
In ``auth_mode=dev`` a user-picker form lets you choose any person; in
``auth_mode=oauth`` only an OAuth placeholder is shown.

The web layer must NOT call connectors, registry internals, or the engine directly;
all data goes through Orchestrator methods only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.templating import _TemplateResponse

from assistant.domain.enums import System
from assistant.identity.oauth import GoogleOAuthError, GoogleOAuthProvider
from assistant.identity.sessions import SessionManager
from assistant.orchestrator.responses import AssistantResponse
from assistant.orchestrator.service import Orchestrator
from assistant.permissions.approvals import ApprovalAlreadyDecided, ApprovalNotFound

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

_ALL_SYSTEMS = list(System)
_OAUTH_STATE_COOKIE = "oauth_state"  # noqa: S105 (cookie name, not a secret)


# ------------------------------------------------------------------ helpers


def _get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator  # type: ignore[no-any-return]


def _get_session_manager(request: Request) -> SessionManager:
    return request.app.state.services.session_manager  # type: ignore[no-any-return]


def _get_oauth_provider(request: Request) -> GoogleOAuthProvider | None:
    return request.app.state.services.oauth_provider  # type: ignore[no-any-return]


def _session_user(request: Request) -> str | None:
    """Return the authenticated user_id from the session cookie, or None."""
    token = request.cookies.get("session")
    return _get_session_manager(request).verify(token)


def _require_user(request: Request) -> str | RedirectResponse:
    """Return the user_id or a redirect to /login if unauthenticated."""
    user = _session_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return user


def _render(
    request: Request,
    template: str,
    ctx: dict[str, Any],
) -> _TemplateResponse:
    """Render a Jinja2 template."""
    return templates.TemplateResponse(request, template, ctx)


def _user_ctx(request: Request, user: str) -> dict[str, Any]:
    """Build the common template context for an authenticated user."""
    resolver = request.app.state.services.resolver
    person = resolver.by_id(user)
    return {
        "active_user": user,
        "active_user_name": person.name,
        "is_admin": "admin" in person.roles,
    }


# ------------------------------------------------------------------ login / logout


def _login_ctx(request: Request, error: str | None = None) -> dict[str, Any]:
    settings = request.app.state.settings
    resolver = request.app.state.services.resolver
    return {
        "auth_mode": settings.auth_mode,
        "people": resolver.people,
        "error": error,
        "google_oauth_configured": _get_oauth_provider(request) is not None,
        "active_user": None,
        "active_user_name": None,
        "is_admin": False,
    }


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> _TemplateResponse:
    return _render(request, "login.html", _login_ctx(request))


@router.post("/login")
def login_post(
    request: Request,
    user: str = Form(...),
) -> Response:
    settings = request.app.state.settings
    if settings.auth_mode != "dev":
        return Response("dev login disabled", status_code=403)
    resolver = request.app.state.services.resolver
    try:
        person = resolver.by_id(user)
    except Exception:  # noqa: BLE001
        return _render(request, "login.html", _login_ctx(request, error=f"Unknown user: {user!r}"))
    sm = _get_session_manager(request)
    token = sm.issue(person.id)
    redirect = RedirectResponse("/", status_code=303)
    redirect.set_cookie(
        "session", token, httponly=True, samesite="lax", secure=settings.is_prod
    )
    return redirect


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:  # noqa: ARG001
    redirect = RedirectResponse("/login", status_code=303)
    redirect.delete_cookie("session")
    return redirect


# ------------------------------------------------------------------ Google OAuth login


@router.get("/auth/google/login")
def google_login(request: Request) -> Response:
    """Redirect to Google's consent screen. Only active in auth_mode=oauth."""
    settings = request.app.state.settings
    provider = _get_oauth_provider(request)
    if settings.auth_mode != "oauth" or provider is None:
        return Response("Google OAuth is not configured", status_code=403)
    state = provider.new_state()
    redirect = RedirectResponse(provider.authorization_url(state), status_code=302)
    redirect.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=settings.is_prod,
        max_age=600,
    )
    return redirect


@router.get("/auth/google/callback", response_class=HTMLResponse, response_model=None)
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Complete the code exchange and grant a session — only for a pre-registered Person.

    A verified Google account that doesn't match a seeded Person's email is refused, not
    auto-provisioned: this system's whole permission model is keyed to known identities
    (DECISIONS.md D8), so an unregistered Google account cannot gain access just by
    existing.
    """
    settings = request.app.state.settings
    provider = _get_oauth_provider(request)
    if settings.auth_mode != "oauth" or provider is None:
        return Response("Google OAuth is not configured", status_code=403)

    def _login_error(message: str) -> _TemplateResponse:
        return _render(request, "login.html", _login_ctx(request, error=message))

    if error:
        return _login_error("Google sign-in was cancelled or denied.")

    expected_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not state or not expected_state or state != expected_state:
        return _login_error("Sign-in session expired or invalid — please try again.")
    if not code:
        return _login_error("Google did not return an authorization code.")

    try:
        email = provider.resolve_login_email(code)
    except GoogleOAuthError:
        return _login_error("Could not verify your Google account. Please try again.")

    resolver = request.app.state.services.resolver
    try:
        person = resolver.by_email(email)
    except Exception:  # noqa: BLE001
        return _login_error("This Google account is not registered for this assistant.")

    sm = _get_session_manager(request)
    token = sm.issue(person.id)
    redirect = RedirectResponse("/", status_code=303)
    redirect.set_cookie(
        "session", token, httponly=True, samesite="lax", secure=settings.is_prod
    )
    redirect.delete_cookie(_OAUTH_STATE_COOKIE)
    return redirect


# ------------------------------------------------------------------ index


@router.get("/", response_class=HTMLResponse, response_model=None)
def index(request: Request) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    return _render(request, "index.html", {**ctx, "response": None})


# ------------------------------------------------------------------ flows


@router.post("/flows/weekly", response_class=HTMLResponse, response_model=None)
def flow_weekly(
    request: Request,
    target: str = Form(default="Anna"),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    resp = _get_orchestrator(request).weekly_tasks(result, target)
    return _render(request, "index.html", {**ctx, "response": resp})


@router.post("/flows/email", response_class=HTMLResponse, response_model=None)
def flow_email(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    resp = _get_orchestrator(request).search_email(result, target, client=client, project=project)
    return _render(request, "index.html", {**ctx, "response": resp})


@router.post("/flows/teams", response_class=HTMLResponse, response_model=None)
def flow_teams(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
    channels: str = Form(default="ClientCo Delivery"),
    keywords: str = Form(default="endpoint"),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    resp = _get_orchestrator(request).search_teams(
        result, target,
        client=client, project=project,
        channels=channel_list, keywords=keyword_list,
    )
    return _render(request, "index.html", {**ctx, "response": resp})


@router.post("/flows/project", response_class=HTMLResponse, response_model=None)
def flow_project(
    request: Request,
    project: str = Form(default="API Integration"),
    client: str = Form(default="ClientCo"),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    resp = _get_orchestrator(request).project_detail(result, project=project, client=client)
    return _render(request, "index.html", {**ctx, "response": resp})


@router.post("/flows/jira", response_class=HTMLResponse, response_model=None)
def flow_jira(
    request: Request,
    project: str = Form(default="API Integration"),
    summary: str = Form(default=""),
    confirm: str | None = Form(default=None),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    if not confirm:
        error_resp = AssistantResponse(
            allowed=False,
            summary="Write actions require explicit confirmation.",
            access_reason="User did not confirm the write action.",
        )
        return _render(request, "index.html", {**ctx, "response": error_resp})
    resp = _get_orchestrator(request).create_jira_task(result, project=project, summary=summary)
    return _render(request, "index.html", {**ctx, "response": resp})


@router.post("/flows/flagship", response_class=HTMLResponse, response_model=None)
def flow_flagship(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    resp = _get_orchestrator(request).flagship(result, target, client=client, project=project)
    return _render(request, "index.html", {**ctx, "response": resp})


# ------------------------------------------------------------------ connections


@router.get("/connections", response_class=HTMLResponse, response_model=None)
def connections_page(request: Request) -> _TemplateResponse | RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    registry = _get_orchestrator(request).connections_registry
    user_conns = {c.system: c for c in registry.list_for_user(result)}
    rows: list[dict[str, Any]] = [
        {
            "system": sys,
            "connected": sys in user_conns and user_conns[sys].is_connected,
        }
        for sys in _ALL_SYSTEMS
    ]
    return _render(request, "connections.html", {**ctx, "rows": rows})


@router.post("/connections/toggle")
def connections_toggle(
    request: Request,
    system: str = Form(...),
) -> RedirectResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    user = result
    registry = _get_orchestrator(request).connections_registry
    try:
        sys_enum = System(system)
    except ValueError:
        return RedirectResponse(url="/connections", status_code=303)
    existing = registry.get(user, sys_enum)
    if existing and existing.is_connected:
        registry.disconnect(user, sys_enum)
    else:
        registry.connect(user, sys_enum, token_ref=f"tok-{user}-{system}")
    return RedirectResponse(url="/connections", status_code=303)


# ------------------------------------------------------------------ admin


def _require_admin(request: Request) -> str | RedirectResponse | HTMLResponse:
    """Return the user_id if authenticated AND admin; else a redirect/403 response."""
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    resolver = request.app.state.services.resolver
    person = resolver.by_id(result)
    if "admin" not in person.roles:
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Admin access required.</p>", status_code=403
        )
    return result


@router.get("/admin", response_class=HTMLResponse, response_model=None)
def admin_page(request: Request) -> _TemplateResponse | RedirectResponse | HTMLResponse:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    user = result

    ctx = _user_ctx(request, user)
    orch = _get_orchestrator(request)

    # Audit events: newest first
    events = list(reversed(orch.audit.events))

    # Pending approvals
    pending = orch.approvals.pending()

    # Policies — read through the persisted store (source of truth), not seed JSON.
    policy_store = request.app.state.services.policy_store
    mailbox_policies = policy_store.load_mailbox()
    teams_policies = policy_store.load_teams()

    return _render(
        request,
        "admin.html",
        {
            **ctx,
            "events": events,
            "pending": pending,
            "mailbox_policies": mailbox_policies,
            "teams_policies": teams_policies,
        },
    )


@router.post("/admin/approvals/{approval_id}/grant")
def admin_grant_approval(request: Request, approval_id: str) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    try:
        _get_orchestrator(request).grant_approval(approval_id, admin_user=result)
    except (ApprovalNotFound, ApprovalAlreadyDecided):
        pass  # stale page / double-submit — fall through to the current admin state
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/approvals/{approval_id}/deny")
def admin_deny_approval(
    request: Request, approval_id: str, reason: str = Form(default="")
) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    try:
        _get_orchestrator(request).deny_approval(approval_id, admin_user=result, reason=reason)
    except (ApprovalNotFound, ApprovalAlreadyDecided):
        pass
    return RedirectResponse(url="/admin", status_code=303)
