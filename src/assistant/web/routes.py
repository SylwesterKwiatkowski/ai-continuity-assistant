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
from assistant.domain.models import Person
from assistant.identity.oauth import GoogleOAuthError, GoogleOAuthProvider
from assistant.identity.resolver import IdentityResolver
from assistant.identity.sessions import SessionManager
from assistant.orchestrator.responses import AssistantResponse
from assistant.orchestrator.service import Orchestrator
from assistant.permissions.approvals import ApprovalAlreadyDecided
from assistant.permissions.policies import ApprovalRequest

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
    """Return the authenticated user_id from the session cookie, or None.

    A session naming a deactivated person is treated as unauthenticated (D23) — revoking
    someone must not wait for their session to expire on its own.
    """
    token = request.cookies.get("session")
    user_id = _get_session_manager(request).verify(token)
    if user_id is None:
        return None
    resolver = request.app.state.services.resolver
    try:
        person = resolver.by_id(user_id)
    except Exception:  # noqa: BLE001
        return None
    if not person.active:
        return None
    return user_id


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
        # Person pickers exclude deactivated people (D23) — the dev picker is the only
        # one that exists so far.
        "people": [p for p in resolver.people if p.active],
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
    if not person.active:
        return _render(
            request, "login.html", _login_ctx(request, error="This account is deactivated.")
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
    if not person.active:
        return _login_error("This account has been deactivated. Contact an admin.")

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


_SAFE_DECISION_REDIRECTS = frozenset({"/admin", "/approvals/mine"})


def _decision_redirect(redirect_to: str) -> RedirectResponse:
    target = redirect_to if redirect_to in _SAFE_DECISION_REDIRECTS else "/approvals/mine"
    return RedirectResponse(url=target, status_code=303)


def _require_approver_or_admin(
    request: Request, approval: ApprovalRequest
) -> str | RedirectResponse | HTMLResponse:
    """Return user_id if authenticated AND (the nominated approver OR admin) (D21).

    The engine already nominates who *should* decide (e.g. the mailbox owner) via
    `approval.approver`; an admin may still decide any request as an explicit, audited
    override — see `Orchestrator._override_note`.
    """
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    if result == approval.approver:
        return result
    resolver = request.app.state.services.resolver
    person = resolver.by_id(result)
    if "admin" in person.roles:
        return result
    return HTMLResponse(
        "<h1>403 Forbidden</h1><p>Only the nominated approver or an admin can decide this "
        "request.</p>",
        status_code=403,
    )


@router.post("/admin/approvals/{approval_id}/grant")
def admin_grant_approval(
    request: Request, approval_id: str, redirect_to: str = Form(default="/admin")
) -> Response:
    orch = _get_orchestrator(request)
    approval = orch.approvals.get(approval_id)
    if approval is None:
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    result = _require_approver_or_admin(request, approval)
    if not isinstance(result, str):
        return result
    try:
        orch.grant_approval(approval_id, decided_by=result)
    except ApprovalAlreadyDecided:
        pass  # stale page / double-submit — fall through to the current state
    return _decision_redirect(redirect_to)


@router.post("/admin/approvals/{approval_id}/deny")
def admin_deny_approval(
    request: Request,
    approval_id: str,
    reason: str = Form(default=""),
    redirect_to: str = Form(default="/admin"),
) -> Response:
    orch = _get_orchestrator(request)
    approval = orch.approvals.get(approval_id)
    if approval is None:
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    result = _require_approver_or_admin(request, approval)
    if not isinstance(result, str):
        return result
    try:
        orch.deny_approval(approval_id, decided_by=result, reason=reason)
    except ApprovalAlreadyDecided:
        pass
    return _decision_redirect(redirect_to)


@router.get("/approvals/mine", response_class=HTMLResponse, response_model=None)
def my_approvals(request: Request) -> _TemplateResponse | RedirectResponse:
    """Pending approval requests naming the current user as the nominated approver.

    Not admin-gated — this is precisely what lets someone who is *not* an admin (e.g. a
    mailbox owner) decide requests over their own data (D21).
    """
    result = _require_user(request)
    if isinstance(result, RedirectResponse):
        return result
    ctx = _user_ctx(request, result)
    orch = _get_orchestrator(request)
    mine = [a for a in orch.approvals.pending() if a.approver == result]
    return _render(request, "my_approvals.html", {**ctx, "pending": mine})


# ------------------------------------------------------------------ admin: people CRUD (D23)


def _validate_person_form(
    resolver: IdentityResolver,
    person_id: str,
    name: str,
    email: str,
    manager_id: str,
    backup_owners_raw: str,
    editing_id: str | None,
) -> str | None:
    """Server-side validation for the create/edit person form. None means valid.

    Every referenced id (manager, backup owners) is checked against the resolver —
    an owner-submitted grant is hostile input in v0.4.1's risk register (R2); an
    admin-submitted person id is lower-stakes but a typo here silently breaks policy
    matching later, so it's validated the same way.
    """
    if not person_id.strip():
        return "Id is required."
    if not name.strip():
        return "Name is required."
    if not email.strip():
        return "Email is required."
    if editing_id is None:
        try:
            resolver.by_id(person_id)
        except Exception:  # noqa: BLE001
            pass
        else:
            return f"A person with id {person_id!r} already exists."
    # An email must not silently take over a DIFFERENT person's login (resolver.upsert()
    # would otherwise leave the previous owner's by-email lookup broken).
    try:
        existing_by_email = resolver.by_email(email)
    except Exception:  # noqa: BLE001
        existing_by_email = None
    if existing_by_email is not None and existing_by_email.id != (editing_id or person_id):
        return f"Email {email!r} already belongs to {existing_by_email.id!r}."
    if manager_id.strip():
        try:
            resolver.by_id(manager_id.strip())
        except Exception:  # noqa: BLE001
            return f"Manager id {manager_id!r} does not match any person."
    for owner in (b.strip() for b in backup_owners_raw.split(",")):
        if owner and not _person_exists(resolver, owner):
            return f"Backup owner id {owner!r} does not match any person."
    return None


def _person_exists(resolver: IdentityResolver, person_id: str) -> bool:
    try:
        resolver.by_id(person_id)
    except Exception:  # noqa: BLE001
        return False
    return True


@router.get("/admin/people", response_class=HTMLResponse, response_model=None)
def admin_people_list(request: Request) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    ctx = _user_ctx(request, result)
    resolver = request.app.state.services.resolver
    people = sorted(resolver.people, key=lambda p: p.name.lower())
    return _render(request, "admin_people.html", {**ctx, "people": people})


@router.get("/admin/people/new", response_class=HTMLResponse, response_model=None)
def admin_people_new_form(request: Request) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    ctx = _user_ctx(request, result)
    return _render(request, "admin_person_form.html", {**ctx, "person": None, "error": None})


@router.post("/admin/people/new")
def admin_people_create(
    request: Request,
    person_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    teams_id: str = Form(default=""),
    jira_id: str = Form(default=""),
    hubspot_id: str = Form(default=""),
    manager_id: str = Form(default=""),
    backup_owners: str = Form(default=""),
) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    services = request.app.state.services
    resolver = services.resolver

    error = _validate_person_form(
        resolver, person_id, name, email, manager_id, backup_owners, editing_id=None
    )
    if error:
        ctx = _user_ctx(request, result)
        return _render(request, "admin_person_form.html", {**ctx, "person": None, "error": error})

    person = Person(
        id=person_id.strip(),
        name=name.strip(),
        email=email.strip(),
        teams_id=teams_id.strip() or None,
        jira_id=jira_id.strip() or None,
        hubspot_id=hubspot_id.strip() or None,
        manager_id=manager_id.strip() or None,
        backup_owners=[b.strip() for b in backup_owners.split(",") if b.strip()],
    )
    services.person_repo.upsert(person)
    resolver.upsert(person)
    return RedirectResponse(url="/admin/people", status_code=303)


@router.get("/admin/people/{person_id}/edit", response_class=HTMLResponse, response_model=None)
def admin_people_edit_form(request: Request, person_id: str) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    resolver = request.app.state.services.resolver
    try:
        person = resolver.by_id(person_id)
    except Exception:  # noqa: BLE001
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    ctx = _user_ctx(request, result)
    return _render(request, "admin_person_form.html", {**ctx, "person": person, "error": None})


@router.post("/admin/people/{person_id}/edit")
def admin_people_update(
    request: Request,
    person_id: str,
    name: str = Form(...),
    email: str = Form(...),
    teams_id: str = Form(default=""),
    jira_id: str = Form(default=""),
    hubspot_id: str = Form(default=""),
    manager_id: str = Form(default=""),
    backup_owners: str = Form(default=""),
) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    services = request.app.state.services
    resolver = services.resolver
    try:
        existing = resolver.by_id(person_id)
    except Exception:  # noqa: BLE001
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)

    error = _validate_person_form(
        resolver, person_id, name, email, manager_id, backup_owners, editing_id=person_id
    )
    if error:
        ctx = _user_ctx(request, result)
        return _render(
            request, "admin_person_form.html", {**ctx, "person": existing, "error": error}
        )

    # roles and active are deliberately not editable here — role changes get their own
    # audited, last-admin-guarded path (DELIVERY_PLAN.md branch 3); active is toggled only
    # via the dedicated deactivate/reactivate actions below.
    updated = existing.model_copy(
        update={
            "name": name.strip(),
            "email": email.strip(),
            "teams_id": teams_id.strip() or None,
            "jira_id": jira_id.strip() or None,
            "hubspot_id": hubspot_id.strip() or None,
            "manager_id": manager_id.strip() or None,
            "backup_owners": [b.strip() for b in backup_owners.split(",") if b.strip()],
        }
    )
    services.person_repo.upsert(updated)
    resolver.upsert(updated)
    return RedirectResponse(url="/admin/people", status_code=303)


@router.post("/admin/people/{person_id}/deactivate")
def admin_people_deactivate(request: Request, person_id: str) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    services = request.app.state.services
    resolver = services.resolver
    try:
        existing = resolver.by_id(person_id)
    except Exception:  # noqa: BLE001
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    updated = existing.model_copy(update={"active": False})
    services.person_repo.upsert(updated)
    resolver.upsert(updated)
    return RedirectResponse(url="/admin/people", status_code=303)


@router.post("/admin/people/{person_id}/reactivate")
def admin_people_reactivate(request: Request, person_id: str) -> Response:
    result = _require_admin(request)
    if not isinstance(result, str):
        return result
    services = request.app.state.services
    resolver = services.resolver
    try:
        existing = resolver.by_id(person_id)
    except Exception:  # noqa: BLE001
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    updated = existing.model_copy(update={"active": True})
    services.person_repo.upsert(updated)
    resolver.upsert(updated)
    return RedirectResponse(url="/admin/people", status_code=303)
