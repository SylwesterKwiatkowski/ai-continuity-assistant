"""M2 — Permission Engine tests (maps to Phase-6 security items 1-6, 9, 10)."""

from __future__ import annotations

from datetime import date

from assistant.domain import ActionType, GmailAction, System, TeamsAction
from assistant.identity import IdentityResolver
from assistant.permissions import (
    ApprovalType,
    MailboxAccessPolicy,
    MailboxScope,
    PermissionEngine,
    PermissionRequest,
    RequestedScope,
    TeamsAccessPolicy,
)

FIXED_TODAY = date(2026, 8, 14)  # within the seed policies' 2026-10-31 expiry


class _AbsenceStub:
    def __init__(self, out_of_office: set[str]) -> None:
        self._out = out_of_office

    def is_out_of_office(self, user_id: str) -> bool:
        return user_id in self._out


def make_engine(
    *, anna_ooo: bool = True, today: date = FIXED_TODAY
) -> PermissionEngine:
    return PermissionEngine.from_seed(
        resolver=IdentityResolver.from_seed(),
        absence_provider=_AbsenceStub({"anna"} if anna_ooo else set()),
        clock=lambda: today,
    )


def gmail_read_req(**scope: object) -> PermissionRequest:
    return PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        action_type=ActionType.READ,
        scope=RequestedScope(
            client="ClientCo", project="API Integration", domain="clientco.com", **scope
        ),
    )


# --- Phase-6 #1: cannot read another user's Gmail without permission ---

def test_no_policy_denies_and_offers_approval() -> None:
    engine = make_engine()
    req = PermissionRequest(
        active_user="lucy",  # lucy is not an allowed requester on Anna's mailbox
        target_user="anna",
        system=System.GMAIL,
        action=GmailAction.SEARCH_METADATA,
        action_type=ActionType.READ,
        scope=RequestedScope(client="ClientCo", project="API Integration"),
    )
    decision = engine.check(req)
    assert decision.allowed is False
    assert decision.required_approval == ApprovalType.MAILBOX_OWNER


# --- Phase-6 #2: can read scoped Gmail when a valid policy exists ---

def test_valid_policy_in_scope_and_ooo_allows() -> None:
    decision = make_engine().check(gmail_read_req())
    assert decision.allowed is True
    assert "MailboxAccessPolicy[anna]" == decision.permission_policy_used
    assert GmailAction.READ_THREAD.value in decision.allowed_actions


def test_ooo_condition_not_met_denies() -> None:
    decision = make_engine(anna_ooo=False).check(gmail_read_req())
    assert decision.allowed is False
    assert "out of office" in decision.reason


def test_out_of_scope_client_denies() -> None:
    req = gmail_read_req()
    req.scope.client = "OtherCorp"
    decision = make_engine().check(req)
    assert decision.allowed is False
    assert "client out of scope" in decision.reason


def test_expired_policy_denies() -> None:
    decision = make_engine(today=date(2026, 11, 1)).check(gmail_read_req())
    assert decision.allowed is False
    assert "expired" in decision.reason


def test_action_not_allowed_denies() -> None:
    req = gmail_read_req()
    req.action = GmailAction.FULL_MAILBOX_ACCESS  # never granted
    decision = make_engine().check(req)
    assert decision.allowed is False
    assert "not in allowed_actions" in decision.reason


# --- Phase-6 #3 / #4: Teams scope enforcement ---

def teams_req(**scope: object) -> PermissionRequest:
    base = dict(client="ClientCo", project="API Integration", channels=["ClientCo Delivery"])
    base.update(scope)
    return PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.TEAMS,
        action=TeamsAction.SEARCH_MESSAGES,
        action_type=ActionType.READ,
        scope=RequestedScope(**base),  # type: ignore[arg-type]
    )


def test_teams_in_scope_allows() -> None:
    decision = make_engine().check(teams_req())
    assert decision.allowed is True
    assert decision.permission_policy_used == "TeamsAccessPolicy[anna]"


def test_teams_out_of_scope_channel_denies() -> None:
    decision = make_engine().check(teams_req(channels=["Random Private Chat"]))
    assert decision.allowed is False
    assert "channel" in decision.reason


def test_teams_date_range_mismatch_denies() -> None:
    decision = make_engine().check(teams_req(date_range="last_365_days"))
    assert decision.allowed is False
    assert "date range" in decision.reason


def test_teams_participants_out_of_scope_denies() -> None:
    decision = make_engine().check(teams_req(participants=["lucy"]))
    assert decision.allowed is False
    assert "participants" in decision.reason


# --- Phase-6 #5 / #6: writes only as active_user, never as target ---

def test_write_as_active_user_allowed() -> None:
    req = PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="create_jira_issue",
        action_type=ActionType.WRITE,
    )
    decision = make_engine().check(req)
    assert decision.allowed is True
    assert decision.access_tier == "self"


def test_write_as_target_is_blocked() -> None:
    req = PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="create_jira_issue",
        action_type=ActionType.WRITE,
        actor="anna",  # attempted impersonation
    )
    decision = make_engine().check(req)
    assert decision.allowed is False
    assert "never impersonate" in decision.reason


# --- tiers & lower-sensitivity systems ---

def test_self_read_allowed_without_policy() -> None:
    req = PermissionRequest(
        active_user="mark",
        target_user="mark",
        system=System.GMAIL,
        action=GmailAction.READ_THREAD,
        action_type=ActionType.READ,
    )
    decision = make_engine().check(req)
    assert decision.allowed is True
    assert decision.access_tier == "self"


def test_delegated_lower_sensitivity_read_allowed_and_audited() -> None:
    req = PermissionRequest(
        active_user="mark",
        target_user="anna",
        system=System.JIRA,
        action="get_assigned_issues",
        action_type=ActionType.READ,
    )
    decision = make_engine().check(req)
    assert decision.allowed is True
    assert decision.access_tier == "delegated"


# --- Phase-6 #10: ambiguous/blocked -> approval request object ---

# --- D23: deactivate, never hard-delete — the engine is one of four enforcement points ---


def _engine_with_deactivated(person_id: str) -> PermissionEngine:
    resolver = IdentityResolver.from_seed()
    resolver.upsert(resolver.by_id(person_id).model_copy(update={"active": False}))
    return PermissionEngine.from_seed(
        resolver=resolver, absence_provider=_AbsenceStub({"anna"}), clock=lambda: FIXED_TODAY
    )


def test_deactivated_active_user_denied() -> None:
    decision = _engine_with_deactivated("mark").check(gmail_read_req())
    assert decision.allowed is False
    assert "deactivated" in decision.reason
    assert "mark" in decision.reason


def test_deactivated_target_user_denied() -> None:
    decision = _engine_with_deactivated("anna").check(gmail_read_req())
    assert decision.allowed is False
    assert "deactivated" in decision.reason
    assert "anna" in decision.reason


def test_deactivated_person_denial_offers_no_approval() -> None:
    decision = _engine_with_deactivated("mark").check(gmail_read_req())
    assert decision.required_approval is None  # approving wouldn't fix a deactivated account


def test_deactivation_check_is_noop_without_resolver() -> None:
    engine = PermissionEngine(mailbox_policies=[], teams_policies=[], clock=lambda: FIXED_TODAY)
    req = PermissionRequest(
        active_user="ghost",
        target_user=None,
        system=System.JIRA,
        action="get_assigned_issues",
        action_type=ActionType.READ,
    )
    # No resolver wired -> the deactivation guard is a no-op -> normal self-tier logic runs.
    assert engine.check(req).allowed is True


def test_build_approval_request_targets_mailbox_owner() -> None:
    engine = make_engine(anna_ooo=False)
    req = gmail_read_req()
    decision = engine.check(req)
    approval = engine.build_approval_request(req, decision)
    assert approval.requester == "mark"
    assert approval.target_user == "anna"
    assert approval.approver == "anna"  # mailbox owner
    assert approval.status == "pending"


# --- Multiple policies per owner (DECISIONS.md D20): a new grant must not break the
# existing standing policy, and the engine must check every policy for that owner. ---

def test_added_mailbox_policy_grants_new_requester_without_breaking_existing() -> None:
    engine = make_engine()
    lucy_req = gmail_read_req()
    lucy_req.active_user = "lucy"
    assert engine.check(lucy_req).allowed is False
    assert engine.check(gmail_read_req()).allowed is True  # mark's baseline access

    engine.add_mailbox_policy(
        MailboxAccessPolicy(
            mailbox_owner="anna",
            allowed_requesters=["lucy"],
            scope=MailboxScope(client="ClientCo", project="API Integration"),
            allowed_actions=[GmailAction.SEARCH_METADATA],
            expiry_date=date(2026, 12, 31),
        )
    )

    assert engine.check(lucy_req).allowed is True
    assert engine.check(gmail_read_req()).allowed is True  # mark's access is untouched


def test_added_teams_policy_grants_new_requester_without_breaking_existing() -> None:
    engine = make_engine()
    lucy_req = teams_req()
    lucy_req.active_user = "lucy"
    assert engine.check(lucy_req).allowed is False
    assert engine.check(teams_req()).allowed is True  # mark's baseline access

    engine.add_teams_policy(
        TeamsAccessPolicy(
            target_user="anna",
            allowed_requesters=["lucy"],
            allowed_channels=["ClientCo Delivery"],
            allowed_projects=["API Integration"],
            allowed_clients=["ClientCo"],
            allowed_actions=[TeamsAction.SEARCH_MESSAGES],
            expiry_date=date(2026, 12, 31),
        )
    )

    assert engine.check(lucy_req).allowed is True
    assert engine.check(teams_req()).allowed is True  # mark's access is untouched
