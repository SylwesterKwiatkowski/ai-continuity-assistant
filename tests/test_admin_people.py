"""Admin people CRUD tests (DELIVERY_PLAN.md branch 2, DECISIONS.md D23)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.api.app import create_app
from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings
from assistant.identity import PersonNotFound


def _make_app(tmp_path: Path) -> tuple[FastAPI, AppServices]:
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings = Settings(database_url=db_url)
    app = create_app(settings)
    services = build_app_services(settings)
    app.state.services = services
    app.state.orchestrator = services.orchestrator
    return app, services


def login(client: TestClient, user: str = "lucy") -> None:
    client.post("/login", data={"user": user}, follow_redirects=False)


# ------------------------------------------------------------------ admin gate


def test_non_admin_cannot_list_people(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "anna")
    assert client.get("/admin/people").status_code == 403


def test_non_admin_cannot_create_person(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "anna")
    resp = client.post(
        "/admin/people/new", data={"person_id": "x", "name": "X", "email": "x@example.com"}
    )
    assert resp.status_code == 403


def test_non_admin_cannot_edit_person(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "anna")
    resp = client.post("/admin/people/mark/edit", data={"name": "X", "email": "x@example.com"})
    assert resp.status_code == 403


def test_non_admin_cannot_deactivate_person(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client, "anna")
    assert client.post("/admin/people/mark/deactivate").status_code == 403


# ------------------------------------------------------------------ list


def test_admin_people_list_shows_seeded_people(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.get("/admin/people")
    assert resp.status_code == 200
    assert "Mark Smith" in resp.text
    assert "Anna Nowak" in resp.text


# ------------------------------------------------------------------ create


def test_create_person_is_resolvable_immediately_and_persists(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/new",
        data={
            "person_id": "dana",
            "name": "Dana New",
            "email": "dana@example.com",
            "manager_id": "lucy",
            "backup_owners": "mark, anna",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # No restart needed — the "Done when" criterion, literally.
    assert services.resolver.by_id("dana").name == "Dana New"
    assert services.resolver.by_id("dana").backup_owners == ["mark", "anna"]

    # And it's actually persisted, not just in-process.
    _app2, services2 = _make_app(tmp_path)
    assert services2.resolver.by_id("dana").name == "Dana New"


def test_create_person_duplicate_id_rejected(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/new",
        data={"person_id": "mark", "name": "Someone Else", "email": "other@example.com"},
    )
    assert resp.status_code == 200
    assert "already exists" in resp.text.lower()


def test_create_person_duplicate_email_rejected(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    mark_email = services.resolver.by_id("mark").email
    resp = client.post(
        "/admin/people/new",
        data={"person_id": "newid", "name": "New Person", "email": mark_email},
    )
    assert resp.status_code == 200
    assert "already belongs to" in resp.text.lower()


def test_create_person_unknown_manager_rejected(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/new",
        data={
            "person_id": "newid",
            "name": "New Person",
            "email": "new@example.com",
            "manager_id": "nobody",
        },
    )
    assert resp.status_code == 200
    assert "does not match any person" in resp.text.lower()


def test_create_person_unknown_backup_owner_rejected(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/new",
        data={
            "person_id": "newid",
            "name": "New Person",
            "email": "new@example.com",
            "backup_owners": "mark, nobody",
        },
    )
    assert resp.status_code == 200
    assert "does not match any person" in resp.text.lower()


# ------------------------------------------------------------------ edit


def test_edit_person_get_form_shows_existing_values(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.get("/admin/people/mark/edit")
    assert resp.status_code == 200
    assert "Mark Smith" in resp.text


def test_edit_person_updates_fields_without_restart(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/mark/edit",
        data={
            "name": "Mark Updated",
            "email": "mark-updated@example.com",
            "manager_id": "lucy",
            "backup_owners": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    updated = services.resolver.by_id("mark")
    assert updated.name == "Mark Updated"
    assert updated.email == "mark-updated@example.com"
    assert updated.roles == ["admin"]  # this form doesn't touch roles (branch 3's job)


def test_edit_person_email_change_keeps_oauth_login_working(tmp_path: Path) -> None:
    """D19 dependency, called out explicitly in ROADMAP.md / DELIVERY_PLAN.md."""
    app, services = _make_app(tmp_path)
    old_email = services.resolver.by_id("mark").email
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    client.post(
        "/admin/people/mark/edit",
        data={"name": "Mark Smith", "email": "mark-new@example.com", "backup_owners": ""},
    )
    assert services.resolver.by_email("mark-new@example.com").id == "mark"
    with pytest.raises(PersonNotFound):
        services.resolver.by_email(old_email)


def test_edit_nonexistent_person_404s(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    resp = client.post(
        "/admin/people/ghost/edit", data={"name": "Ghost", "email": "ghost@example.com"}
    )
    assert resp.status_code == 404


# ------------------------------------------------------------------ deactivate/reactivate


def test_deactivate_then_reactivate_round_trip(tmp_path: Path) -> None:
    app, services = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)

    resp = client.post("/admin/people/mark/deactivate", follow_redirects=False)
    assert resp.status_code == 303
    assert services.resolver.by_id("mark").active is False

    list_page = client.get("/admin/people")
    assert "deactivated" in list_page.text.lower()

    resp2 = client.post("/admin/people/mark/reactivate", follow_redirects=False)
    assert resp2.status_code == 303
    assert services.resolver.by_id("mark").active is True


def test_deactivate_nonexistent_person_404s(tmp_path: Path) -> None:
    app, _ = _make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=True)
    login(client)
    assert client.post("/admin/people/ghost/deactivate").status_code == 404
