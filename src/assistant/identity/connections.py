"""Per-user, self-service connections and the credential-resolution rule (DECISIONS.md D6).

The "never impersonate" rule is enforced here, at the credential layer:

    reads  -> the TARGET's connection (policy-gated upstream by the Permission Engine)
    writes -> the ACTIVE_USER's own connection, always

A write is never resolved against anyone but the acting user.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from assistant.config import SEEDS_DIR
from assistant.domain.enums import System
from assistant.identity.errors import ConnectionNotFound

ConnectionStatus = str  # "connected" | "disconnected"


class Connection(BaseModel):
    """A single user's link to one system. Tokens are held indirectly via `token_ref`."""

    user_id: str
    system: System
    status: ConnectionStatus = "connected"
    token_ref: str
    scopes: list[str] = Field(default_factory=list)

    @property
    def is_connected(self) -> bool:
        return self.status == "connected"


class ConnectionStore(Protocol):
    """Persistence abstraction for connection records."""

    def upsert(self, conn: Connection) -> None: ...

    def delete(self, user_id: str, system: System) -> None: ...

    def all(self) -> list[Connection]: ...


@runtime_checkable
class TokenStore(Protocol):
    """Abstraction over encrypted secret storage. Stubbed in MVP (DECISIONS.md D6)."""

    def get_token(self, token_ref: str) -> str: ...

    def put_token(self, token_ref: str, secret: str) -> None: ...


class InMemoryTokenStore:
    """Non-persistent token store for tests/MVP. Never use in production."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get_token(self, token_ref: str) -> str:
        if token_ref not in self._tokens:
            raise KeyError(token_ref)
        return self._tokens[token_ref]

    def put_token(self, token_ref: str, secret: str) -> None:
        self._tokens[token_ref] = secret

    def has_token(self, token_ref: str) -> bool:
        return token_ref in self._tokens


class ConnectionRegistry:
    """Holds connections and resolves the correct credential per operation."""

    def __init__(
        self,
        connections: Iterable[Connection] = (),
        token_store: TokenStore | None = None,
        store: ConnectionStore | None = None,
    ) -> None:
        ts = token_store or InMemoryTokenStore()
        # If a persistent store is given, initialise from it (ignores `connections` arg).
        if store is not None:
            all_connections = store.all()
        else:
            all_connections = list(connections)
        self._conn_store: ConnectionStore | None = store
        self._by_key: dict[tuple[str, System], Connection] = {
            (c.user_id, c.system): c for c in all_connections
        }
        self._token_store: TokenStore = ts
        if isinstance(ts, InMemoryTokenStore):
            for c in all_connections:
                if not ts.has_token(c.token_ref):
                    ts.put_token(c.token_ref, f"stub-secret::{c.token_ref}")

    @classmethod
    def from_seed(
        cls,
        path: Path | None = None,
        token_store: TokenStore | None = None,
    ) -> ConnectionRegistry:
        path = path or (SEEDS_DIR / "connections.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        connections = [Connection.model_validate(item) for item in data]
        return cls(connections, token_store)

    # --- self-service management (surfaced via the /connections API later) ---

    def get(self, user_id: str, system: System) -> Connection | None:
        return self._by_key.get((user_id, system))

    def list_for_user(self, user_id: str) -> list[Connection]:
        return [c for (uid, _), c in self._by_key.items() if uid == user_id]

    def connect(
        self, user_id: str, system: System, token_ref: str, scopes: Iterable[str] = ()
    ) -> Connection:
        conn = Connection(
            user_id=user_id, system=system, token_ref=token_ref, scopes=list(scopes)
        )
        self._by_key[(user_id, system)] = conn
        if isinstance(self._token_store, InMemoryTokenStore):
            if not self._token_store.has_token(token_ref):
                self._token_store.put_token(token_ref, f"stub-secret::{token_ref}")
        if self._conn_store is not None:
            self._conn_store.upsert(conn)
        return conn

    def disconnect(self, user_id: str, system: System) -> None:
        self._by_key.pop((user_id, system), None)
        if self._conn_store is not None:
            self._conn_store.delete(user_id, system)

    # --- credential resolution (the enforced rule) ---

    def resolve_own(self, user_id: str, system: System) -> Connection:
        """Resolve a user's OWN connection (for writes and shared-system reads)."""
        conn = self.get(user_id, system)
        if conn is None or not conn.is_connected:
            raise ConnectionNotFound(user_id, system)
        return conn

    def resolve_for_read(self, target_user_id: str, system: System) -> Connection:
        """Delegated read of a private store uses the TARGET's connection.

        Missing/disconnected -> honest refusal (never a fallback to another credential).
        """
        return self.resolve_own(target_user_id, system)

    def resolve_for_write(self, active_user_id: str, system: System) -> Connection:
        """Writes ALWAYS use the active_user's own connection. Never anyone else's."""
        return self.resolve_own(active_user_id, system)

    def token_for(self, connection: Connection) -> str:
        return self._token_store.get_token(connection.token_ref)
