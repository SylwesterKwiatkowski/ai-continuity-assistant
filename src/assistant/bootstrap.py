"""Application service factory (v0.2 — persistent SQLite backend).

:func:`build_app_services` is the single entry point that wires together all
layers.  :func:`build_default_orchestrator` in ``orchestrator/service.py`` is
kept untouched so existing unit tests continue to work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import cast

from assistant.audit.log import AuditLog
from assistant.config import SEEDS_DIR, Settings
from assistant.connectors.mock import build_mock_registry
from assistant.connectors.protocols import CalendarPort
from assistant.domain.enums import System
from assistant.identity.connections import ConnectionRegistry
from assistant.identity.oauth import GoogleOAuthProvider
from assistant.identity.resolver import IdentityResolver
from assistant.identity.sessions import SessionManager
from assistant.orchestrator.service import Orchestrator, _CalendarAbsence  # noqa: PLC2701
from assistant.permissions.engine import PermissionEngine
from assistant.storage import (
    Database,
    EncryptedTokenStore,
    SqliteApprovalRepository,
    SqliteAuditRepository,
    SqliteConnectionStore,
    SqlitePolicyStore,
    database_from_url,
    initialize_database,
)
from assistant.summarizer.stub import StubSummarizer


@dataclass
class AppServices:
    """Bag of wired-up application services passed to the FastAPI app state."""

    orchestrator: Orchestrator
    session_manager: SessionManager
    resolver: IdentityResolver
    settings: Settings
    policy_store: SqlitePolicyStore
    oauth_provider: GoogleOAuthProvider | None


def build_app_services(
    settings: Settings,
    clock: Callable[[], date] = date.today,
) -> AppServices:
    """Wire all layers together, seeding the DB on first run."""
    db: Database = database_from_url(settings.database_url)
    initialize_database(db, SEEDS_DIR)

    token_store = EncryptedTokenStore(db, settings.token_store_key)
    conn_store = SqliteConnectionStore(db)

    # Mock-era placeholder: seed stub tokens for any connection that is stored
    # but whose token hasn't been encrypted yet (happens on first boot or after
    # a token_store_key rotation).  Real OAuth will replace this loop.
    for conn in conn_store.all():
        try:
            token_store.get_token(conn.token_ref)
        except KeyError:
            token_store.put_token(conn.token_ref, f"stub-secret::{conn.token_ref}")

    registry = ConnectionRegistry(store=conn_store, token_store=token_store)

    resolver = IdentityResolver.from_seed()
    policy_store = SqlitePolicyStore(db)
    connectors = build_mock_registry()
    calendar = cast(CalendarPort, connectors[System.CALENDAR])
    engine = PermissionEngine(
        resolver=resolver,
        mailbox_policies=policy_store.load_mailbox(),
        teams_policies=policy_store.load_teams(),
        absence_provider=_CalendarAbsence(calendar, clock),
        clock=clock,
    )

    audit = AuditLog(repository=SqliteAuditRepository(db))
    approvals = SqliteApprovalRepository(db)

    orchestrator = Orchestrator(
        resolver=resolver,
        registry=registry,
        engine=engine,
        connectors=connectors,
        summarizer=StubSummarizer(),
        audit=audit,
        approvals=approvals,
        policy_store=policy_store,
        clock=clock,
    )

    session_manager = SessionManager(settings.session_secret, settings.session_ttl_hours)

    oauth_provider = None
    if settings.google_client_id and settings.google_client_secret:
        oauth_provider = GoogleOAuthProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
        )

    return AppServices(
        orchestrator=orchestrator,
        session_manager=session_manager,
        resolver=resolver,
        settings=settings,
        policy_store=policy_store,
        oauth_provider=oauth_provider,
    )
