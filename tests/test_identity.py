"""M1 — identity resolution tests."""

from __future__ import annotations

import pytest

from assistant.domain import Person, System
from assistant.identity import IdentityResolver, PersonNotFound


@pytest.fixture
def resolver() -> IdentityResolver:
    return IdentityResolver.from_seed()


def test_resolve_by_name_case_insensitive(resolver: IdentityResolver) -> None:
    anna = resolver.by_name("anna")
    assert anna.id == "anna"
    assert anna.name == "Anna Nowak"


def test_resolve_by_email(resolver: IdentityResolver) -> None:
    mark_email = resolver.by_id("mark").email
    assert resolver.by_email(mark_email.upper()).id == "mark"


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


# --- D22: resolver mutation (mirrors D20's engine.add_mailbox_policy pattern) ---


def test_upsert_adds_a_new_person_immediately(resolver: IdentityResolver) -> None:
    new_person = Person(id="newguy", name="New Guy", email="newguy@example.com")
    resolver.upsert(new_person)
    assert resolver.by_id("newguy").name == "New Guy"
    assert resolver.by_email("newguy@example.com").id == "newguy"
    assert resolver.by_name("New Guy").id == "newguy"


def test_upsert_updates_existing_person_email(resolver: IdentityResolver) -> None:
    mark = resolver.by_id("mark")
    old_email = mark.email
    updated = mark.model_copy(update={"email": "mark-new@example.com"})
    resolver.upsert(updated)

    assert resolver.by_id("mark").email == "mark-new@example.com"
    assert resolver.by_email("mark-new@example.com").id == "mark"
    with pytest.raises(PersonNotFound):
        resolver.by_email(old_email)  # stale email no longer resolves


def test_upsert_updating_email_to_itself_does_not_break_lookup(
    resolver: IdentityResolver,
) -> None:
    mark = resolver.by_id("mark")
    resolver.upsert(mark.model_copy(update={"name": "Mark Renamed"}))
    assert resolver.by_id("mark").name == "Mark Renamed"
    assert resolver.by_email(mark.email).name == "Mark Renamed"


def test_from_repository_loads_people() -> None:
    class _FakeRepo:
        def all(self) -> list[Person]:
            return [Person(id="x", name="X", email="x@example.com")]

    resolver = IdentityResolver.from_repository(_FakeRepo())
    assert resolver.by_id("x").name == "X"
