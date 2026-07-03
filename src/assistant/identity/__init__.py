"""Identity layer — person resolution and per-user connections (credential rule, D6)."""

from assistant.identity.connections import (
    Connection,
    ConnectionRegistry,
    InMemoryTokenStore,
    TokenStore,
)
from assistant.identity.errors import (
    AmbiguousPerson,
    ConnectionNotFound,
    IdentityError,
    PersonNotFound,
)
from assistant.identity.resolver import IdentityResolver

__all__ = [
    "AmbiguousPerson",
    "Connection",
    "ConnectionNotFound",
    "ConnectionRegistry",
    "IdentityError",
    "IdentityResolver",
    "InMemoryTokenStore",
    "PersonNotFound",
    "TokenStore",
]
