"""Identity mapping: natural-language name / email / id -> Person, and per-system handles.

MVP loaded people from `seeds/people.json` only (DECISIONS.md D8); as of D22, that file
seeds the `people` table on first boot only (`storage/seed.py`) and the resolver is built
from the database (`from_repository`) at every subsequent run. `from_seed` remains for
tests and `build_default_orchestrator`, which have no database. Live directory sync is
still deferred.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from assistant.config import SEEDS_DIR
from assistant.domain.enums import System
from assistant.domain.models import Person
from assistant.identity.errors import AmbiguousPerson, PersonNotFound


@runtime_checkable
class PersonRepository(Protocol):
    """Persistence abstraction the resolver reads its initial population from (D22)."""

    def all(self) -> list[Person]: ...


class IdentityResolver:
    """Resolves people and their cross-system handles."""

    def __init__(self, people: list[Person]) -> None:
        self._by_id: dict[str, Person] = {p.id: p for p in people}
        # Name/email lookups are case-insensitive.
        self._by_email: dict[str, Person] = {p.email.lower(): p for p in people}

    @classmethod
    def from_seed(cls, path: Path | None = None) -> IdentityResolver:
        path = path or (SEEDS_DIR / "people.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        people = [Person.model_validate(item) for item in data]
        return cls(people)

    @classmethod
    def from_repository(cls, repo: PersonRepository) -> IdentityResolver:
        return cls(repo.all())

    @property
    def people(self) -> list[Person]:
        return list(self._by_id.values())

    def upsert(self, person: Person) -> None:
        """Add or update a person, effective immediately in this process — no restart.

        Mirrors the pattern DECISIONS.md D20 established for policies
        (`PermissionEngine.add_mailbox_policy`): mutate the shared instance in place, since
        `bootstrap.py` hands this same resolver to both the engine and the orchestrator.
        """
        existing = self._by_id.get(person.id)
        if existing is not None and existing.email.lower() != person.email.lower():
            del self._by_email[existing.email.lower()]
        self._by_id[person.id] = person
        self._by_email[person.email.lower()] = person

    def by_id(self, person_id: str) -> Person:
        person = self._by_id.get(person_id)
        if person is None:
            raise PersonNotFound(person_id)
        return person

    def by_email(self, email: str) -> Person:
        person = self._by_email.get(email.lower())
        if person is None:
            raise PersonNotFound(email)
        return person

    def by_name(self, name: str) -> Person:
        """Resolve a (possibly partial) name, case-insensitively.

        Raises PersonNotFound if nothing matches and AmbiguousPerson if more than one does.
        """
        needle = name.strip().lower()
        matches = [
            p for p in self._by_id.values()
            if needle == p.name.lower() or needle in p.name.lower()
        ]
        # Prefer an exact match if present (avoids "Anna" matching "Anna-Maria" ambiguously).
        exact = [p for p in matches if p.name.lower() == needle]
        if exact:
            return exact[0]
        if not matches:
            raise PersonNotFound(name)
        if len(matches) > 1:
            raise AmbiguousPerson(name, [p.name for p in matches])
        return matches[0]

    def handle_for(self, person: Person, system: System) -> str | None:
        return person.handle_for(system)
