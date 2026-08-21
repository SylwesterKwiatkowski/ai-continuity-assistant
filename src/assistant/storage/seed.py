"""One-time database seeding from JSON files (idempotent — checks before writing)."""

from __future__ import annotations

import json
from pathlib import Path

from assistant.domain.models import Person
from assistant.identity.connections import Connection
from assistant.permissions.policies import MailboxAccessPolicy, TeamsAccessPolicy
from assistant.storage.db import Database
from assistant.storage.repositories import (
    SqliteConnectionStore,
    SqlitePersonRepository,
    SqlitePolicyStore,
)


def initialize_database(db: Database, seeds_dir: Path) -> None:
    """Seed the database from JSON files if the relevant tables are empty."""
    person_repo = SqlitePersonRepository(db)
    if not person_repo.all():
        people_path = seeds_dir / "people.json"
        if people_path.exists():
            data = json.loads(people_path.read_text(encoding="utf-8"))
            for item in data:
                person_repo.upsert(Person.model_validate(item))

    conn_store = SqliteConnectionStore(db)
    if not conn_store.all():
        connections_path = seeds_dir / "connections.json"
        if connections_path.exists():
            data = json.loads(connections_path.read_text(encoding="utf-8"))
            for item in data:
                conn_store.upsert(Connection.model_validate(item))

    policy_store = SqlitePolicyStore(db)
    if not policy_store.load_mailbox() and not policy_store.load_teams():
        policies_path = seeds_dir / "policies.json"
        if policies_path.exists():
            raw = json.loads(policies_path.read_text(encoding="utf-8"))
            mailbox = [MailboxAccessPolicy.model_validate(p) for p in raw.get("mailbox", [])]
            teams = [TeamsAccessPolicy.model_validate(p) for p in raw.get("teams", [])]
            policy_store.save_mailbox(mailbox)
            policy_store.save_teams(teams)
