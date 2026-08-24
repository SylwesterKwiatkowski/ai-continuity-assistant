"""The Permission & Policy Engine (spec §7.4, §10.3).

Default-deny. Validates READ (on the target's data) and WRITE (as the active_user)
independently. Delegated reads of sensitive systems (Gmail, Teams) require a matching,
in-scope, in-condition, non-expired policy; anything ambiguous or missing is blocked and
an approval is offered.

The engine only *decides*. Credential resolution happens in the Connection Registry and
audit is written by the orchestrator — this keeps the decision logic pure and testable.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from assistant.config import SEEDS_DIR
from assistant.domain.enums import AccessTier, ActionType, System
from assistant.identity.resolver import IdentityResolver
from assistant.permissions.policies import (
    ApprovalRequest,
    ApprovalType,
    MailboxAccessPolicy,
    PermissionDecision,
    PermissionRequest,
    TeamsAccessPolicy,
)
from assistant.permissions.scope import mailbox_scope_matches, teams_scope_matches

# Systems whose delegated reads require an explicit policy. Others (Calendar, Jira,
# HubSpot, Sheets, Drive) are lower-sensitivity work context — delegated reads are allowed
# within tier rules and still audited. See DECISIONS.md D15.
SENSITIVE_SYSTEMS: frozenset[System] = frozenset({System.GMAIL, System.TEAMS})

KNOWN_CONDITIONS: frozenset[str] = frozenset({"only_when_out_of_office"})


@runtime_checkable
class AbsenceProvider(Protocol):
    """Tells the engine whether a user is currently out of office."""

    def is_out_of_office(self, user_id: str) -> bool: ...


class _NeverOutOfOffice:
    """Safe default: assume present unless a real provider says otherwise."""

    def is_out_of_office(self, user_id: str) -> bool:  # noqa: ARG002
        return False


class PermissionEngine:
    def __init__(
        self,
        resolver: IdentityResolver | None = None,
        mailbox_policies: list[MailboxAccessPolicy] | None = None,
        teams_policies: list[TeamsAccessPolicy] | None = None,
        absence_provider: AbsenceProvider | None = None,
        clock: Callable[[], date] = date.today,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._resolver = resolver
        self._mailbox_policies = mailbox_policies or []
        self._teams_policies = teams_policies or []
        self._absence: AbsenceProvider = absence_provider or _NeverOutOfOffice()
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_seed(
        cls,
        path: Path | None = None,
        resolver: IdentityResolver | None = None,
        absence_provider: AbsenceProvider | None = None,
        clock: Callable[[], date] = date.today,
    ) -> PermissionEngine:
        path = path or (SEEDS_DIR / "policies.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        mailbox = [MailboxAccessPolicy.model_validate(p) for p in data.get("mailbox", [])]
        teams = [TeamsAccessPolicy.model_validate(p) for p in data.get("teams", [])]
        return cls(
            resolver=resolver,
            mailbox_policies=mailbox,
            teams_policies=teams,
            absence_provider=absence_provider,
            clock=clock,
        )

    # ------------------------------------------------------------------ live policy grants

    def add_mailbox_policy(self, policy: MailboxAccessPolicy) -> None:
        """Make a newly granted mailbox policy effective immediately (no restart needed)."""
        self._mailbox_policies.append(policy)

    def add_teams_policy(self, policy: TeamsAccessPolicy) -> None:
        """Make a newly granted Teams policy effective immediately (no restart needed)."""
        self._teams_policies.append(policy)

    # ------------------------------------------------------------------ public API

    def check(self, req: PermissionRequest) -> PermissionDecision:
        deactivation_denial = self._check_deactivation(req)
        if deactivation_denial is not None:
            return deactivation_denial
        if req.action_type == ActionType.WRITE:
            return self._check_write(req)
        return self._check_read(req)

    def _check_deactivation(self, req: PermissionRequest) -> PermissionDecision | None:
        """Deactivate, never hard-delete (ROADMAP.md v0.2.1 / DECISIONS.md D23): a
        deactivated active_user or target_user is denied everything, with no approval
        path offered — approving wouldn't fix a deactivated account. A no-op if this
        engine has no resolver wired (some tests construct one without it)."""
        if self._resolver is None:
            return None
        for label, person_id in (
            ("active_user", req.active_user),
            ("target_user", req.target_user),
        ):
            if person_id is None:
                continue
            try:
                person = self._resolver.by_id(person_id)
            except Exception:  # noqa: BLE001
                continue  # unknown person isn't this guard's problem
            if not person.active:
                return PermissionDecision(
                    allowed=False,
                    access_tier=self._tier_for(req),
                    reason=f"{label} {person_id!r} is deactivated",
                )
        return None

    def build_approval_request(
        self, req: PermissionRequest, decision: PermissionDecision
    ) -> ApprovalRequest:
        """Construct an ApprovalRequest for a blocked delegated read."""
        approver = self._suggest_approver(req, decision.required_approval)
        return ApprovalRequest(
            id=self._id_factory(),
            requester=req.active_user,
            target_user=req.target_user,
            approver=approver,
            approver_type=decision.required_approval,
            systems_requested=[req.system],
            scope=req.scope,
            reason=decision.reason,
        )

    # ------------------------------------------------------------------ writes

    def _check_write(self, req: PermissionRequest) -> PermissionDecision:
        # The one absolute rule: writes only as the active_user, never as anyone else.
        if req.resolved_actor != req.active_user:
            return PermissionDecision(
                allowed=False,
                access_tier=AccessTier.SELF,
                reason=(
                    f"write blocked: actor {req.resolved_actor!r} != active_user "
                    f"{req.active_user!r} (never impersonate the target user)"
                ),
            )
        return PermissionDecision(
            allowed=True,
            access_tier=AccessTier.SELF,
            allowed_actions=[req.action],
            scope=req.scope,
            reason=f"write permitted as active_user {req.active_user!r}",
        )

    # ------------------------------------------------------------------ reads

    def _check_read(self, req: PermissionRequest) -> PermissionDecision:
        tier = self._tier_for(req)

        if tier == AccessTier.SELF:
            return PermissionDecision(
                allowed=True,
                access_tier=tier,
                allowed_actions=[req.action],
                scope=req.scope,
                reason="self access: reading your own data",
            )

        # Delegated read of another person's data.
        if req.system in SENSITIVE_SYSTEMS:
            return self._check_delegated_sensitive_read(req)

        # Lower-sensitivity work context (Calendar/Jira/HubSpot/Sheets/Drive): allowed,
        # audited. Kept scoped to what the caller asked for.
        return PermissionDecision(
            allowed=True,
            access_tier=AccessTier.DELEGATED,
            allowed_actions=[req.action],
            scope=req.scope,
            reason=f"delegated read of lower-sensitivity system {req.system.value!r} (audited)",
        )

    def _tier_for(self, req: PermissionRequest) -> AccessTier:
        if req.target_user is None or req.target_user == req.active_user:
            return AccessTier.SELF
        return AccessTier.DELEGATED

    def _check_delegated_sensitive_read(self, req: PermissionRequest) -> PermissionDecision:
        assert req.target_user is not None  # DELEGATED tier guarantees this
        if req.system == System.GMAIL:
            policies = self._find_mailbox_policies(req.target_user)
            return self._evaluate_mailbox(req, policies)
        # Teams
        teams_policies = self._find_teams_policies(req.target_user)
        return self._evaluate_teams(req, teams_policies)

    # -- Gmail --

    def _find_mailbox_policies(self, target_user: str) -> list[MailboxAccessPolicy]:
        return [p for p in self._mailbox_policies if p.mailbox_owner == target_user]

    def _evaluate_mailbox(
        self, req: PermissionRequest, policies: list[MailboxAccessPolicy]
    ) -> PermissionDecision:
        """Several policies may cover the same owner (standing + one-off grants) — allow if
        any one of them authorizes the request; otherwise report the last denial reason."""
        if not policies:
            return self._deny_delegated(req, "no mailbox access policy exists for this target")
        decision = None
        for policy in policies:
            decision = self._evaluate_one_mailbox_policy(req, policy)
            if decision.allowed:
                return decision
        assert decision is not None
        return decision

    def _evaluate_one_mailbox_policy(
        self, req: PermissionRequest, policy: MailboxAccessPolicy
    ) -> PermissionDecision:
        if req.active_user not in policy.allowed_requesters:
            return self._deny_delegated(req, "requester is not an allowed requester")
        if req.action not in {a.value for a in policy.allowed_actions}:
            return self._deny_delegated(req, f"action {req.action!r} not in allowed_actions")
        ok, why = self._conditions_met(policy.conditions, req.target_user)
        if not ok:
            return self._deny_delegated(req, why)
        if self._expired(policy.expiry_date):
            return self._deny_delegated(req, "policy has expired")
        in_scope, why = mailbox_scope_matches(req.scope, policy.scope)
        if not in_scope:
            return self._deny_delegated(req, why)
        return PermissionDecision(
            allowed=True,
            access_tier=AccessTier.DELEGATED,
            allowed_actions=[a.value for a in policy.allowed_actions],
            scope=req.scope,
            reason="delegated Gmail read authorized by mailbox policy",
            permission_policy_used=f"MailboxAccessPolicy[{policy.mailbox_owner}]",
        )

    # -- Teams --

    def _find_teams_policies(self, target_user: str) -> list[TeamsAccessPolicy]:
        return [p for p in self._teams_policies if p.target_user == target_user]

    def _evaluate_teams(
        self, req: PermissionRequest, policies: list[TeamsAccessPolicy]
    ) -> PermissionDecision:
        """Same any-one-of-them-authorizes rule as mailbox policies — see its docstring."""
        if not policies:
            return self._deny_delegated(req, "no Teams access policy exists for this target")
        decision = None
        for policy in policies:
            decision = self._evaluate_one_teams_policy(req, policy)
            if decision.allowed:
                return decision
        assert decision is not None
        return decision

    def _evaluate_one_teams_policy(
        self, req: PermissionRequest, policy: TeamsAccessPolicy
    ) -> PermissionDecision:
        if req.active_user not in policy.allowed_requesters:
            return self._deny_delegated(req, "requester is not an allowed requester")
        if req.action not in {a.value for a in policy.allowed_actions}:
            return self._deny_delegated(req, f"action {req.action!r} not in allowed_actions")
        ok, why = self._conditions_met(policy.conditions, req.target_user)
        if not ok:
            return self._deny_delegated(req, why)
        if self._expired(policy.expiry_date):
            return self._deny_delegated(req, "policy has expired")
        in_scope, why = teams_scope_matches(req.scope, policy)
        if not in_scope:
            return self._deny_delegated(req, why)
        return PermissionDecision(
            allowed=True,
            access_tier=AccessTier.DELEGATED,
            allowed_actions=[a.value for a in policy.allowed_actions],
            scope=req.scope,
            reason="delegated Teams read authorized by Teams policy",
            permission_policy_used=f"TeamsAccessPolicy[{policy.target_user}]",
        )

    # ------------------------------------------------------------------ helpers

    def _conditions_met(self, conditions: list[str], target_user: str | None) -> tuple[bool, str]:
        for cond in conditions:
            if cond not in KNOWN_CONDITIONS:
                return False, f"unknown condition {cond!r} (default-deny)"
            if cond == "only_when_out_of_office":
                if target_user is None or not self._absence.is_out_of_office(target_user):
                    return False, "condition not met: target is not out of office"
        return True, ""

    def _expired(self, expiry: date | None) -> bool:
        return expiry is not None and expiry < self._clock()

    def _deny_delegated(self, req: PermissionRequest, reason: str) -> PermissionDecision:
        approval = (
            ApprovalType.MAILBOX_OWNER if req.system == System.GMAIL else ApprovalType.MANAGER
        )
        return PermissionDecision(
            allowed=False,
            access_tier=AccessTier.DELEGATED,
            reason=reason,
            required_approval=approval,
        )

    def _suggest_approver(
        self, req: PermissionRequest, approval_type: ApprovalType | None
    ) -> str | None:
        if req.target_user is None:
            return None
        if approval_type == ApprovalType.MAILBOX_OWNER:
            return req.target_user
        if approval_type == ApprovalType.MANAGER and self._resolver is not None:
            try:
                return self._resolver.by_id(req.target_user).manager_id
            except Exception:
                return None
        return None
