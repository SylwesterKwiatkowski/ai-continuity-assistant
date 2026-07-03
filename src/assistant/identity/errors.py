"""Identity-layer exceptions."""

from __future__ import annotations

from assistant.domain.enums import System


class IdentityError(Exception):
    """Base class for identity/connection resolution failures."""


class PersonNotFound(IdentityError):
    def __init__(self, query: str) -> None:
        super().__init__(f"No person matches {query!r}")
        self.query = query


class AmbiguousPerson(IdentityError):
    def __init__(self, query: str, matches: list[str]) -> None:
        super().__init__(f"{query!r} is ambiguous; matches: {', '.join(matches)}")
        self.query = query
        self.matches = matches


class ConnectionNotFound(IdentityError):
    """Raised when the required user has not connected the requested system.

    For a delegated read this means the *target* has not connected that app, so the
    read is simply impossible → honest refusal (never a fallback to someone else's
    credential).
    """

    def __init__(self, user_id: str, system: System) -> None:
        super().__init__(f"No connected {system.value!r} connection for user {user_id!r}")
        self.user_id = user_id
        self.system = system
