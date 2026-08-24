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


class PersonDeactivated(IdentityError):
    """Raised where a deactivated Person is used somewhere only an active one may be
    (login, a request's active_user/target_user, naming them in a new policy) — D23.

    Deactivate, never hard-delete: the person still resolves by id/email/name, but every
    enforcement point (login, PermissionEngine.check, Orchestrator.grant_approval, the
    dev-login picker) refuses them.
    """

    def __init__(self, person_id: str) -> None:
        super().__init__(f"Person {person_id!r} is deactivated")
        self.person_id = person_id


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
