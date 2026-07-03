"""Connector SDK — the uniform contract every system connector implements.

Two guarantees are enforced here, at the connector boundary:

1. **No connector method runs without an approved PermissionDecision.** Every method calls
   `self._guard(...)`, which raises unless the decision is `allowed` and matches this system,
   action, and access type. This is the structural backstop for Phase-6 #11
   (the orchestrator can never reach data without permission validation).

2. **The credential rule (D6) is re-checked at the boundary.** Reads must carry the *target's*
   connection; writes must carry the *active_user's* own connection — never the target's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from assistant.domain.enums import ActionType, System
from assistant.identity.connections import Connection
from assistant.permissions.policies import PermissionDecision

# Per-user private stores: a delegated READ uses the TARGET's connection. Every other
# (shared) system is read with the active_user's own connection, filtered by the target.
TARGET_CREDENTIAL_SYSTEMS: frozenset[System] = frozenset({System.GMAIL, System.TEAMS})


class Capability(BaseModel):
    """One method a connector exposes, with its security metadata."""

    system: System
    action: str
    access: ActionType
    sensitivity: str = "normal"  # "sensitive" for Gmail/Teams content
    requires_scope: bool = False


class WriteResult(BaseModel):
    """Result of a write action, always attributed to the acting user."""

    system: System
    action: str
    actor: str  # the active_user; never the target
    resource_id: str | None = None
    detail: str = ""


class PermissionContext(BaseModel):
    """Proof-of-authorization handed to every connector call.

    Constructed by the orchestrator only from a successful Permission Engine decision plus
    the connection resolved by the Connection Registry.
    """

    active_user: str
    system: System
    action: str
    access: ActionType
    decision: PermissionDecision
    connection: Connection
    target_user: str | None = None


class UnauthorizedConnectorCall(Exception):
    """Raised when a connector method is invoked without valid authorization."""


class BaseConnector(ABC):
    """Base class for all connectors. Subclasses set `system` and implement `manifest()`."""

    system: ClassVar[System]

    @abstractmethod
    def manifest(self) -> list[Capability]:
        """Declare the methods this connector exposes and their security metadata."""

    def _guard(self, ctx: PermissionContext, action: str, access: ActionType) -> Connection:
        """Authorize one call. Returns the connection to use, or raises."""
        if not ctx.decision.allowed:
            raise UnauthorizedConnectorCall(
                f"{self.system.value}.{action}: permission not granted "
                f"({ctx.decision.reason!r})"
            )
        if ctx.system != self.system:
            raise UnauthorizedConnectorCall(
                f"context system {ctx.system.value!r} != connector {self.system.value!r}"
            )
        if ctx.action != action or ctx.access != access:
            raise UnauthorizedConnectorCall(
                f"context authorizes {ctx.access.value}:{ctx.action!r}, "
                f"not {access.value}:{action!r}"
            )
        self._check_credential(ctx, action, access)
        return ctx.connection

    def _check_credential(
        self, ctx: PermissionContext, action: str, access: ActionType
    ) -> None:
        """Re-assert the credential rule: reads→target, writes→active_user only."""
        if access == ActionType.WRITE:
            expected = ctx.active_user
            if ctx.connection.user_id != expected:
                raise UnauthorizedConnectorCall(
                    f"write {action!r} must use the active_user's connection "
                    f"({expected!r}), not {ctx.connection.user_id!r} — never impersonate"
                )
        elif self.system in TARGET_CREDENTIAL_SYSTEMS:
            # Private store: read must use the target's own connection.
            expected = ctx.target_user or ctx.active_user
            if ctx.connection.user_id != expected:
                raise UnauthorizedConnectorCall(
                    f"read {action!r} on {self.system.value} must use the target's connection "
                    f"({expected!r}), not {ctx.connection.user_id!r}"
                )
        else:
            # Shared system: read uses the active_user's own connection.
            if ctx.connection.user_id != ctx.active_user:
                raise UnauthorizedConnectorCall(
                    f"read {action!r} on {self.system.value} must use the active_user's "
                    f"connection ({ctx.active_user!r}), not {ctx.connection.user_id!r}"
                )
        if ctx.connection.system != self.system:
            raise UnauthorizedConnectorCall(
                f"connection is for {ctx.connection.system.value!r}, not {self.system.value!r}"
            )
