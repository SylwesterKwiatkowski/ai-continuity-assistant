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
from assistant.identity.sessions import SessionManager
from assistant.orchestrator.responses import AssistantResponse
from assistant.orchestrator.service import Orchestrator

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

_ALL_SYSTEMS = list(System)


# ------------------------------------------------------------------ helpers


def _get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator  # type: ignore[no-any-return]


def _get_session_manager(request: Request) -> SessionManager:
    return request.app.state.services.session_manager  # type: ignore[no-any-return]


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


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> _TemplateResponse:
    settings = request.app.state.settings
    resolver = request.app.state.services.resolver
    return _render(
        request,
        "login.html",
        {
            "auth_mode": settings.auth_mode,
            "people": resolver.people,
            "error": None,
            "active_user": None,
            "active_user_name": None,
            "is_admin": False,
        },
    )


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
        return _render(
            request,
            "login.html",
            {
                "auth_mode": settings.auth_mode,
                "people": resolver.people,
                "error": f"Unknown user: {user!r}",
                "active_user": None,
                "active_user_name": None,
                "is_admin": False,
            },
        )
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


@router.get("/admin", response_class=HTMLResponse, response_model=None)
def admin_page(request: Request) -> _TemplateResponse | RedirectResponse | HTMLResponse:
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    user = result
    resolver = request.app.state.services.resolver
    person = resolver.by_id(user)
    if "admin" not in person.roles:
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Admin access required.</p>", status_code=403
        )

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
