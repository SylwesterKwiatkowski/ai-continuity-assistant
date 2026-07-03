"""M1 — identity resolution tests."""

from __future__ import annotations

import pytest

from assistant.domain import System
from assistant.identity import IdentityResolver, PersonNotFound


@pytest.fixture
def resolver() -> IdentityResolver:
    return IdentityResolver.from_seed()


def test_resolve_by_name_case_insensitive(resolver: IdentityResolver) -> None:
    anna = resolver.by_name("anna")
    assert anna.id == "anna"
    assert anna.name == "Anna Nowak"


def test_resolve_by_email(resolver: IdentityResolver) -> None:
    assert resolver.by_email("MARK@acme.com").id == "mark"


def test_unknown_name_raises(resolver: IdentityResolver) -> None:
    with pytest.raises(PersonNotFound):
        resolver.by_name("Nobody")


def test_per_system_handles(resolver: IdentityResolver) -> None:
    anna = resolver.by_name("Anna")
    # Google systems keyed by email; others by per-system id.
    assert resolver.handle_for(anna, System.GMAIL) == "anna@acme.com"
    assert resolver.handle_for(anna, System.CALENDAR) == "anna@acme.com"
    assert resolver.handle_for(anna, System.TEAMS) == "teams-anna"
    assert resolver.handle_for(anna, System.JIRA) == "jira-anna"
    assert resolver.handle_for(anna, System.HUBSPOT) == "hs-anna"


def test_backup_owner_mapping(resolver: IdentityResolver) -> None:
    anna = resolver.by_name("Anna")
    assert anna.backup_owners == ["mark"]
