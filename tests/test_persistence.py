"""Persistence tests: audit/approvals survive restarts, tokens encrypted at rest,
connections write through to SQLite."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings
from assistant.storage import (
    EncryptedTokenStore,
    SqlitePersonRepository,
    database_from_url,
    initialize_database,
)


def _make_services(
    tmp_path: Path,
    db_name: str = "a.db",
    clock: Callable[[], date] = lambda: date(2026, 8, 14),
) -> AppServices:
    db_url = f"sqlite:///{tmp_path}/{db_name}"
    settings = Settings(database_url=db_url)
    return build_app_services(settings, clock=clock)


# ------------------------------------------------------------------ audit survives restart


def test_audit_survives_restart(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    services.orchestrator.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )

    # Rebuild services from the same DB
    services2 = _make_services(tmp_path)
    gmail_events = [
        e
        for e in services2.orchestrator.audit.events
        if "gmail" in str(e.system_accessed).lower()
    ]
    assert gmail_events, "expected gmail audit event after restart"


# ------------------------------------------------------------------ approvals survive restart


def test_approvals_survive_restart(tmp_path: Path) -> None:
    # Use a date after Anna's OOO window so access is blocked and an approval is requested
    services = _make_services(tmp_path, clock=lambda: date(2026, 9, 5))
    services.orchestrator.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )

    services2 = _make_services(tmp_path, clock=lambda: date(2026, 9, 5))
    pending = services2.orchestrator.approvals.pending()
    assert pending, "expected pending approvals after restart"


# ------------------------------------------------------------------ encrypted tokens


def test_encrypted_token_round_trip(tmp_path: Path) -> None:
    db = database_from_url(f"sqlite:///{tmp_path}/tokens.db")
    store = EncryptedTokenStore(db, "my-secret-key")
    store.put_token("ref1", "my-plaintext-secret")
    assert store.get_token("ref1") == "my-plaintext-secret"


def test_encrypted_token_unknown_raises_key_error(tmp_path: Path) -> None:
    db = database_from_url(f"sqlite:///{tmp_path}/tokens.db")
    store = EncryptedTokenStore(db, "my-secret-key")
    with pytest.raises(KeyError):
        store.get_token("nonexistent")


def test_encrypted_token_ciphertext_does_not_contain_plaintext(tmp_path: Path) -> None:
    db = database_from_url(f"sqlite:///{tmp_path}/tokens.db")
    store = EncryptedTokenStore(db, "my-secret-key")
    plaintext = "super-secret-token-value"
    store.put_token("ref1", plaintext)
    rows = db.query("SELECT ciphertext FROM tokens WHERE token_ref = 'ref1'")
    ciphertext = rows[0][0]
    assert isinstance(ciphertext, bytes)
    assert plaintext.encode() not in ciphertext


# ------------------------------------------------------------------ connections write-through


def test_connections_write_through_persist_across_rebuild(tmp_path: Path) -> None:
    from assistant.domain.enums import System

    services = _make_services(tmp_path)
    # Connect lucy to gmail
    services.orchestrator.connections_registry.connect(
        "lucy", System.GMAIL, token_ref="tok-lucy-gmail"
    )

    # Rebuild and check
    services2 = _make_services(tmp_path)
    conn = services2.orchestrator.connections_registry.get("lucy", System.GMAIL)
    assert conn is not None
    assert conn.is_connected


def test_connections_disconnect_persists_across_rebuild(tmp_path: Path) -> None:
    from assistant.domain.enums import System

    services = _make_services(tmp_path)
    # Disconnect mark from gmail (he has it in seeds)
    services.orchestrator.connections_registry.disconnect("mark", System.GMAIL)

    # Rebuild and check
    services2 = _make_services(tmp_path)
    conn = services2.orchestrator.connections_registry.get("mark", System.GMAIL)
    assert conn is None


# --- supervisor findings: audit append-only + admin reads persisted policies ---

def test_audit_append_rejects_duplicate_id(tmp_path: Path) -> None:
    import sqlite3

    from assistant.audit.models import AuditEvent
    from assistant.domain.enums import ActionType, System
    from assistant.storage import database_from_url
    from assistant.storage.repositories import SqliteAuditRepository

    db = database_from_url(f"sqlite:///{tmp_path}/audit.db")
    repo = SqliteAuditRepository(db)
    event = AuditEvent(
        id="fixed-id",
        timestamp=datetime(2026, 7, 4, tzinfo=UTC),
        active_user="mark",
        action_type=ActionType.READ,
        system_accessed=System.GMAIL,
    )
    repo.append(event)
    with pytest.raises(sqlite3.IntegrityError):
        repo.append(event)  # same id must never overwrite history
    assert len(repo.all()) == 1


def test_admin_page_reads_policies_from_store(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from assistant.api.app import create_app
    from assistant.config import Settings
    from assistant.permissions.policies import MailboxAccessPolicy, MailboxScope

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/web.db"))
    services = app.state.services
    # Add a policy that exists ONLY in the persisted store, not in seed JSON.
    extra = MailboxAccessPolicy(
        mailbox_owner="zzz-store-only",
        allowed_requesters=["lucy"],
        scope=MailboxScope(client="StoreCo", project="StoreProj"),
    )
    services.policy_store.save_mailbox([*services.policy_store.load_mailbox(), extra])

    client = TestClient(app)
    client.post("/login", data={"user": "lucy"}, follow_redirects=False)
    page = client.get("/admin")
    assert page.status_code == 200
    assert "zzz-store-only" in page.text  # proves read-through to SQLite, not seeds


# ------------------------------------------------------------------ D22: people persistence


def test_people_survive_restart(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    assert services.resolver.by_id("mark").name == "Mark Smith"

    services2 = _make_services(tmp_path)
    assert services2.resolver.by_id("mark").name == "Mark Smith"


def test_person_added_directly_is_resolvable_without_restart(tmp_path: Path) -> None:
    from assistant.domain.models import Person

    services = _make_services(tmp_path)
    new_person = Person(id="dana", name="Dana New", email="dana@example.com")

    # The "Done when" criterion, literally: persist + make it live in-process, no restart.
    services.person_repo.upsert(new_person)
    services.resolver.upsert(new_person)

    assert services.resolver.by_id("dana").name == "Dana New"
    # The orchestrator shares this exact resolver instance — prove it end-to-end: a flow
    # resolving "Dana New" by name must not raise PersonNotFound.
    resp = services.orchestrator.weekly_tasks("mark", "Dana New")
    assert resp.allowed is True


def test_people_seed_from_json_is_first_boot_path_only(tmp_path: Path) -> None:
    """seeds/people.json only seeds an empty table — mirrors connections.json/policies.json.
    Uses a throwaway seeds dir; never touches the real seeds/people.json."""
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "people.json").write_text(
        json.dumps([{"id": "p1", "name": "Person One", "email": "p1@example.com"}])
    )

    db_path = f"sqlite:///{tmp_path}/people.db"
    db = database_from_url(db_path)
    initialize_database(db, seeds_dir)
    repo = SqlitePersonRepository(db)
    assert [p.id for p in repo.all()] == ["p1"]

    # Edit the seed file after first boot — a rebuild must NOT pick this up. The database,
    # not the JSON file, is now the source of truth.
    (seeds_dir / "people.json").write_text(
        json.dumps([{"id": "p2", "name": "Person Two", "email": "p2@example.com"}])
    )
    db2 = database_from_url(db_path)
    initialize_database(db2, seeds_dir)
    repo2 = SqlitePersonRepository(db2)
    assert [p.id for p in repo2.all()] == ["p1"]


# ------------------------------------------------------------------ D22: schema migrations


def test_fresh_database_applies_all_migrations(tmp_path: Path) -> None:
    db = database_from_url(f"sqlite:///{tmp_path}/fresh.db")
    versions = {row[0] for row in db.query("SELECT version FROM schema_migrations")}
    assert versions == {1, 2}
    db.query("SELECT * FROM people")  # does not raise -> table exists


def test_migrations_are_safe_on_a_pre_migration_database(tmp_path: Path) -> None:
    """Simulates the deployed host's file: the original 5 tables exist (created before
    migrations existed), with no schema_migrations table and no people table. Migration 1
    must be a safe no-op that doesn't touch existing rows; migration 2 must add `people`
    cleanly. This is ROADMAP.md's Operational-debt Risk 1, made concrete."""
    import sqlite3

    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE audit_events (id TEXT PRIMARY KEY, ts TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE approvals (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE policies (
            kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (kind, key)
        );
        CREATE TABLE connections (
            user_id TEXT NOT NULL, system TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (user_id, system)
        );
        CREATE TABLE tokens (token_ref TEXT PRIMARY KEY, ciphertext BLOB NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO audit_events (id, ts, data) VALUES (?, ?, ?)",
        ("evt-1", "2026-01-01T00:00:00+00:00", '{"pre":"existing"}'),
    )
    conn.commit()
    conn.close()

    db = database_from_url(f"sqlite:///{path}")  # opens the "legacy" file with the new code

    # Pre-existing data survived untouched.
    rows = db.query("SELECT data FROM audit_events WHERE id = 'evt-1'")
    assert rows and rows[0][0] == '{"pre":"existing"}'

    # Both migrations are now recorded as applied, and the new table exists.
    versions = {row[0] for row in db.query("SELECT version FROM schema_migrations")}
    assert versions == {1, 2}
    db.query("SELECT * FROM people")  # does not raise


def test_migrations_do_not_reapply_on_reopen(tmp_path: Path) -> None:
    path = f"sqlite:///{tmp_path}/reopen.db"
    db1 = database_from_url(path)
    applied_at = db1.query("SELECT applied_at FROM schema_migrations WHERE version = 1")[0][0]

    db2 = database_from_url(path)  # reopen the same file
    applied_at_again = db2.query(
        "SELECT applied_at FROM schema_migrations WHERE version = 1"
    )[0][0]
    assert applied_at == applied_at_again  # migration 1 ran exactly once
