"""M2 — Permission Engine tests (maps to Phase-6 security items 1-6, 9, 10)."""

from __future__ import annotations

from datetime import date

from assistant.domain import ActionType, GmailAction, System, TeamsAction
from assistant.identity import IdentityResolver
from assistant.permissions import (
    ApprovalType,
    PermissionEngine,
    PermissionRequest,
    RequestedScope,
)

FIXED_TODAY = date(2026, 7, 3)  # within the seed policies' 2026-07-20 expiry


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
    decision = make_engine(today=date(2026, 7, 21)).check(gmail_read_req())
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

def test_build_approval_request_targets_mailbox_owner() -> None:
    engine = make_engine(anna_ooo=False)
    req = gmail_read_req()
    decision = engine.check(req)
    approval = engine.build_approval_request(req, decision)
    assert approval.requester == "mark"
    assert approval.target_user == "anna"
    assert approval.approver == "anna"  # mailbox owner
    assert approval.status == "pending"
