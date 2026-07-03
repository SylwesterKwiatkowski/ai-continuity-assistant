"""Web UI routes — server-rendered Jinja2 + HTMX (with plain form POST fallback).

Active user is read from the "active_user" cookie (default: "mark").
This is an MVP identity stub — real authentication replaces the cookie mechanism.

The web layer must NOT call connectors, registry internals, or the engine directly;
all data goes through Orchestrator methods only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.templating import _TemplateResponse

from assistant.domain.enums import System
from assistant.orchestrator.responses import AssistantResponse
from assistant.orchestrator.service import Orchestrator

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

_ALL_SYSTEMS = list(System)


def _get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator  # type: ignore[no-any-return]


def _active_user(active_user: str | None) -> str:
    return active_user or "mark"


def _render(
    request: Request,
    template: str,
    ctx: dict[str, Any],
) -> _TemplateResponse:
    """Render a Jinja2 template."""
    return templates.TemplateResponse(request, template, ctx)


# ------------------------------------------------------------------ user switcher


@router.post("/user")
def set_user(
    response: Response,  # noqa: ARG001
    user: str = Form(...),
) -> RedirectResponse:
    """Set the active user cookie and redirect back to index."""
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie("active_user", user, httponly=True, samesite="lax")
    return redirect


# ------------------------------------------------------------------ index


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    return _render(
        request,
        "index.html",
        {"active_user": _active_user(active_user), "response": None},
    )


# ------------------------------------------------------------------ flows


@router.post("/flows/weekly", response_class=HTMLResponse)
def flow_weekly(
    request: Request,
    target: str = Form(default="Anna"),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    resp = orch.weekly_tasks(user, target)
    return _render(request, "index.html", {"active_user": user, "response": resp})


@router.post("/flows/email", response_class=HTMLResponse)
def flow_email(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    resp = orch.search_email(user, target, client=client, project=project)
    return _render(request, "index.html", {"active_user": user, "response": resp})


@router.post("/flows/teams", response_class=HTMLResponse)
def flow_teams(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
    channels: str = Form(default="ClientCo Delivery"),
    keywords: str = Form(default="endpoint"),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    resp = orch.search_teams(
        user, target, client=client, project=project,
        channels=channel_list, keywords=keyword_list,
    )
    return _render(request, "index.html", {"active_user": user, "response": resp})


@router.post("/flows/project", response_class=HTMLResponse)
def flow_project(
    request: Request,
    project: str = Form(default="API Integration"),
    client: str = Form(default="ClientCo"),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    resp = orch.project_detail(user, project=project, client=client)
    return _render(request, "index.html", {"active_user": user, "response": resp})


@router.post("/flows/jira", response_class=HTMLResponse)
def flow_jira(
    request: Request,
    project: str = Form(default="API Integration"),
    summary: str = Form(default=""),
    confirm: str | None = Form(default=None),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    # Confirmation checkbox is required for all write actions.
    if not confirm:
        error_resp = AssistantResponse(
            allowed=False,
            summary="Write actions require explicit confirmation.",
            access_reason="User did not confirm the write action.",
        )
        return _render(
            request, "index.html", {"active_user": user, "response": error_resp}
        )
    orch = _get_orchestrator(request)
    resp = orch.create_jira_task(user, project=project, summary=summary)
    return _render(request, "index.html", {"active_user": user, "response": resp})


@router.post("/flows/flagship", response_class=HTMLResponse)
def flow_flagship(
    request: Request,
    target: str = Form(default="Anna"),
    client: str = Form(default="ClientCo"),
    project: str = Form(default="API Integration"),
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    resp = orch.flagship(user, target, client=client, project=project)
    return _render(request, "index.html", {"active_user": user, "response": resp})


# ------------------------------------------------------------------ connections


@router.get("/connections", response_class=HTMLResponse)
def connections_page(
    request: Request,
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    registry = orch.connections_registry
    user_conns = {c.system: c for c in registry.list_for_user(user)}
    rows: list[dict[str, Any]] = [
        {
            "system": sys,
            "connected": sys in user_conns and user_conns[sys].is_connected,
        }
        for sys in _ALL_SYSTEMS
    ]
    return _render(request, "connections.html", {"active_user": user, "rows": rows})


@router.post("/connections/toggle")
def connections_toggle(
    request: Request,
    system: str = Form(...),
    active_user: str | None = Cookie(default=None),
) -> RedirectResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)
    registry = orch.connections_registry
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


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    active_user: str | None = Cookie(default=None),
) -> _TemplateResponse:
    user = _active_user(active_user)
    orch = _get_orchestrator(request)

    # Audit events: newest first
    events = list(reversed(orch.audit.events))

    # Pending approvals
    pending = orch.approvals.pending()

    # Seed policies summary — read directly from seeds/policies.json
    from assistant.config import SEEDS_DIR  # noqa: PLC0415

    policies_path = SEEDS_DIR / "policies.json"
    policies_data: dict[str, Any] = {}
    if policies_path.exists():
        policies_data = json.loads(policies_path.read_text(encoding="utf-8"))

    mailbox_policies = policies_data.get("mailbox", [])
    teams_policies = policies_data.get("teams", [])

    return _render(
        request,
        "admin.html",
        {
            "active_user": user,
            "events": events,
            "pending": pending,
            "mailbox_policies": mailbox_policies,
            "teams_policies": teams_policies,
        },
    )
