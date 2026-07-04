"""Persistence tests: audit/approvals survive restarts, tokens encrypted at rest,
connections write through to SQLite."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from assistant.bootstrap import AppServices, build_app_services
from assistant.config import Settings
from assistant.storage import EncryptedTokenStore, database_from_url


def _make_services(
    tmp_path: Path,
    db_name: str = "a.db",
    clock: Callable[[], date] = lambda: date(2026, 7, 3),
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
    services = _make_services(tmp_path, clock=lambda: date(2026, 7, 15))
    services.orchestrator.search_email(
        "mark", "Anna", client="ClientCo", project="API Integration"
    )

    services2 = _make_services(tmp_path, clock=lambda: date(2026, 7, 15))
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
