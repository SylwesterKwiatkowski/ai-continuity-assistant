"""Identity mapping: natural-language name / email / id -> Person, and per-system handles.

MVP loads people from `seeds/people.json` (DECISIONS.md D8). Live directory sync is deferred.
"""

from __future__ import annotations

import json
from pathlib import Path

from assistant.config import SEEDS_DIR
from assistant.domain.enums import System
from assistant.domain.models import Person
from assistant.identity.errors import AmbiguousPerson, PersonNotFound


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

    @property
    def people(self) -> list[Person]:
        return list(self._by_id.values())

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
