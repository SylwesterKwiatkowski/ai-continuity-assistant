"""Agent Orchestrator (spec §10.2).

Coordinates every flow: resolve identities -> ask the Permission Engine -> resolve the correct
connection -> call the connector -> normalize + summarize -> audit. The orchestrator NEVER calls
a connector without an approving decision, and every write goes out as the active_user.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import cast

from assistant.audit.log import AuditLog
from assistant.connectors.base import (
    TARGET_CREDENTIAL_SYSTEMS,
    BaseConnector,
    PermissionContext,
)
from assistant.connectors.mock import build_mock_registry
from assistant.connectors.protocols import (
    CalendarPort,
    GmailPort,
    HubSpotPort,
    JiraPort,
    SheetsPort,
    TeamsPort,
)
from assistant.domain.enums import ActionType, GmailAction, System, TeamsAction
from assistant.domain.models import EmailThread, Task, TeamsThread
from assistant.identity.connections import ConnectionRegistry
from assistant.identity.errors import ConnectionNotFound
from assistant.identity.resolver import IdentityResolver
from assistant.orchestrator.responses import AssistantResponse
from assistant.permissions.approvals import (
    ApprovalAlreadyDecided,
    ApprovalNotFound,
    ApprovalRepository,
    InMemoryApprovalRepository,
)
from assistant.permissions.engine import PermissionEngine
from assistant.permissions.policies import (
    ApprovalRequest,
    MailboxAccessPolicy,
    MailboxScope,
    PermissionDecision,
    PermissionRequest,
    PolicyStore,
    RequestedScope,
    TeamsAccessPolicy,
)
from assistant.summarizer.base import Finding, Summarizer
from assistant.summarizer.stub import StubSummarizer

WRITE_NOTE = "No action taken as the target. All write actions executed as the active_user."

# How long a manually-approved one-off grant lasts before it needs re-approving. Kept as a
# module constant rather than configurable — this is a stopgap until v0.4's full "temporary
# scoped policy" design is revisited (DECISIONS.md D20).
GRANT_DURATION_DAYS = 14

_GRANTED_GMAIL_ACTIONS = [
    GmailAction.SEARCH_METADATA,
    GmailAction.READ_THREAD,
    GmailAction.SUMMARIZE,
    GmailAction.RETRIEVE_ATTACHMENT,
]
_GRANTED_TEAMS_ACTIONS = [
    TeamsAction.SEARCH_MESSAGES,
    TeamsAction.READ_THREAD,
    TeamsAction.SUMMARIZE,
    TeamsAction.RETRIEVE_FILE,
]


@dataclass
class _Authz:
    decision: PermissionDecision
    ctx: PermissionContext | None
    req: PermissionRequest | None = None


class _CalendarAbsence:
    """Backs the Permission Engine's OOO condition with the Calendar connector."""

    def __init__(self, calendar: CalendarPort, clock: Callable[[], date]) -> None:
        self._cal = calendar
        self._clock = clock

    def is_out_of_office(self, user_id: str) -> bool:
        return self._cal.is_out_of_office(user_id, on=self._clock())


class Orchestrator:
    def __init__(
        self,
        resolver: IdentityResolver,
        registry: ConnectionRegistry,
        engine: PermissionEngine,
        connectors: dict[System, BaseConnector],
        summarizer: Summarizer,
        audit: AuditLog,
        approvals: ApprovalRepository | None = None,
        policy_store: PolicyStore | None = None,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._resolver = resolver
        self._registry = registry
        self._engine = engine
        self._connectors = connectors
        self._summarizer = summarizer
        self._audit = audit
        self._approvals: ApprovalRepository = approvals or InMemoryApprovalRepository()
        self._policy_store = policy_store
        self._clock = clock

    @property
    def approvals(self) -> ApprovalRepository:
        return self._approvals

    @property
    def audit(self) -> AuditLog:
        """Read-only access to the audit log (for admin dashboard)."""
        return self._audit

    @property
    def connections_registry(self) -> ConnectionRegistry:
        """Read-only access to the connection registry (for connections page)."""
        return self._registry

    # typed connector accessors (port-typed; real connectors share the method names)
    def _gmail(self) -> GmailPort:
        return cast(GmailPort, self._connectors[System.GMAIL])

    def _teams(self) -> TeamsPort:
        return cast(TeamsPort, self._connectors[System.TEAMS])

    def _jira(self) -> JiraPort:
        return cast(JiraPort, self._connectors[System.JIRA])

    def _sheets(self) -> SheetsPort:
        return cast(SheetsPort, self._connectors[System.SHEETS])

    def _hubspot(self) -> HubSpotPort:
        return cast(HubSpotPort, self._connectors[System.HUBSPOT])

    # ------------------------------------------------------------------ authorization

    def _authorize_read(
        self,
        active_user: str,
        target_id: str | None,
        system: System,
        action: str,
        scope: RequestedScope,
    ) -> _Authz:
        req = PermissionRequest(
            active_user=active_user,
            target_user=target_id,
            system=system,
            action=action,
            action_type=ActionType.READ,
            scope=scope,
        )
        decision = self._engine.check(req)
        if not decision.allowed:
            self._audit.record_read(
                active_user=active_user,
                target_user=target_id,
                system=system,
                action=action,
                result_status="denied",
                reason=decision.reason,
            )
            return _Authz(decision, None, req)

        delegated_private = (
            system in TARGET_CREDENTIAL_SYSTEMS
            and target_id is not None
            and target_id != active_user
        )
        try:
            conn = (
                self._registry.resolve_for_read(cast(str, target_id), system)
                if delegated_private
                else self._registry.resolve_own(active_user, system)
            )
        except ConnectionNotFound as exc:
            self._audit.record_read(
                active_user=active_user,
                target_user=target_id,
                system=system,
                action=action,
                result_status="error",
                reason=str(exc),
            )
            return _Authz(decision, None, req)

        ctx = PermissionContext(
            active_user=active_user,
            target_user=target_id,
            system=system,
            action=action,
            access=ActionType.READ,
            decision=decision,
            connection=conn,
        )
        return _Authz(decision, ctx, req)

    def _authorize_write(
        self, active_user: str, system: System, action: str, target_id: str | None = None
    ) -> _Authz:
        req = PermissionRequest(
            active_user=active_user,
            target_user=target_id,
            system=system,
            action=action,
            action_type=ActionType.WRITE,
            actor=active_user,
        )
        decision = self._engine.check(req)
        if not decision.allowed:
            return _Authz(decision, None, req)
        conn = self._registry.resolve_own(active_user, system)
        ctx = PermissionContext(
            active_user=active_user,
            target_user=target_id,
            system=system,
            action=action,
            access=ActionType.WRITE,
            decision=decision,
            connection=conn,
        )
        return _Authz(decision, ctx, req)

    # ------------------------------------------------------------------ finding helpers

    @staticmethod
    def _task_finding(t: Task) -> Finding:
        due = t.due_date.isoformat() if t.due_date else "no due date"
        return Finding(
            text=f"[{t.source}] {t.id}: {t.title} — {t.status}, due {due} (project {t.project})",
            source=f"{t.source}: {t.url}",
        )

    @staticmethod
    def _email_finding(t: EmailThread) -> Finding:
        when = t.date.date().isoformat() if t.date else "unknown date"
        atts = ", ".join(a.filename for a in t.attachments)
        text = f"Email '{t.subject}' ({when}): {t.snippet}"
        if atts:
            text += f" [attachments: {atts}]"
        return Finding(text=text, source=f"gmail: {t.source_url}")

    @staticmethod
    def _teams_finding(t: TeamsThread) -> Finding:
        when = t.date.date().isoformat() if t.date else "unknown date"
        return Finding(
            text=f"Teams [{t.channel}] ({when}): {t.snippet}",
            source=f"teams: {t.source_url}",
        )

    # ------------------------------------------------------------------ flows

    def weekly_tasks(self, active_user: str, target_name: str) -> AssistantResponse:
        target = self._resolver.by_name(target_name)
        findings: list[Finding] = []
        audit_ids: list[str] = []
        gaps: list[str] = []

        jira = self._authorize_read(
            active_user, target.id, System.JIRA, "get_assigned_issues", RequestedScope()
        )
        if jira.ctx is not None:
            tasks = self._jira().get_assigned_issues(jira.ctx)
            findings.extend(self._task_finding(t) for t in tasks)
            audit_ids.append(
                self._audit.record_read(
                    active_user=active_user, target_user=target.id, system=System.JIRA,
                    action="get_assigned_issues", resource_ids=[t.id for t in tasks],
                    reason=jira.decision.reason,
                ).id
            )
        else:
            gaps.append(f"Could not consult {System.JIRA}: {jira.decision.reason}")

        sheets = self._authorize_read(
            active_user, target.id, System.SHEETS, "get_recurring_tasks", RequestedScope()
        )
        if sheets.ctx is not None:
            rec = self._sheets().get_recurring_tasks(sheets.ctx)
            findings.extend(self._task_finding(t) for t in rec)
            audit_ids.append(
                self._audit.record_read(
                    active_user=active_user, target_user=target.id, system=System.SHEETS,
                    action="get_recurring_tasks", resource_ids=[t.id for t in rec],
                    reason=sheets.decision.reason,
                ).id
            )
        else:
            gaps.append(f"Could not consult {System.SHEETS}: {sheets.decision.reason}")

        summary = self._summarizer.summarize(
            f"What is {target.name} working on this week?", findings
        )
        return AssistantResponse(
            allowed=True,
            summary=summary.text,
            sources=summary.sources,
            access_reason=f"Delegated work-context read for {target.name} (audited).",
            audit_event_ids=audit_ids,
            gaps=gaps,
        )

    def search_email(
        self,
        active_user: str,
        target_name: str,
        *,
        client: str,
        project: str,
        domain: str | None = None,
        keywords: list[str] | None = None,
    ) -> AssistantResponse:
        target = self._resolver.by_name(target_name)
        domain = domain or self._lookup_domain(active_user, client)
        scope = RequestedScope(
            client=client, project=project, domain=domain, keywords=keywords or [],
            date_range="last_90_days",
        )
        authz = self._authorize_read(
            active_user, target.id, System.GMAIL, GmailAction.SEARCH_METADATA, scope
        )
        if authz.ctx is None:
            return self._refusal(authz, target_name, "mailbox")

        threads = self._gmail().search_email_metadata(authz.ctx, query=f"{client} {project}")
        findings = [self._email_finding(t) for t in threads]
        audit_id = self._audit.record_read(
            active_user=active_user, target_user=target.id, system=System.GMAIL,
            action=GmailAction.SEARCH_METADATA, search_query=f"{client} {project}",
            resource_ids=[t.id for t in threads],
            attachments_accessed=[a.filename for t in threads for a in t.attachments],
            permission_policy_used=authz.decision.permission_policy_used,
            reason=authz.decision.reason,
        ).id
        summary = self._summarizer.summarize(
            f"{client} {project} email from {target.name}", findings
        )
        return AssistantResponse(
            allowed=True, summary=summary.text, sources=summary.sources,
            access_reason=authz.decision.reason, audit_event_ids=[audit_id],
        )

    def search_teams(
        self,
        active_user: str,
        target_name: str,
        *,
        client: str,
        project: str,
        channels: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> AssistantResponse:
        target = self._resolver.by_name(target_name)
        scope = RequestedScope(
            client=client, project=project,
            channels=channels or [], keywords=keywords or [],
            participants=[target.id], date_range="last_90_days",
        )
        authz = self._authorize_read(
            active_user, target.id, System.TEAMS, TeamsAction.SEARCH_MESSAGES, scope
        )
        if authz.ctx is None:
            return self._refusal(authz, target_name, "Teams context")

        threads = self._teams().search_teams_messages(authz.ctx, keywords=keywords or [])
        findings = [self._teams_finding(t) for t in threads]
        audit_id = self._audit.record_read(
            active_user=active_user, target_user=target.id, system=System.TEAMS,
            action=TeamsAction.SEARCH_MESSAGES, resource_ids=[t.id for t in threads],
            permission_policy_used=authz.decision.permission_policy_used,
            reason=authz.decision.reason,
        ).id
        summary = self._summarizer.summarize(
            f"What did {target.name} say about {client} {project} in Teams?", findings
        )
        return AssistantResponse(
            allowed=True, summary=summary.text, sources=summary.sources,
            access_reason=authz.decision.reason, audit_event_ids=[audit_id],
        )

    def create_jira_task(
        self, active_user: str, *, project: str, summary: str, description: str = ""
    ) -> AssistantResponse:
        authz = self._authorize_write(active_user, System.JIRA, "create_jira_issue")
        if authz.ctx is None:
            return AssistantResponse(
                allowed=False, summary="Write blocked.", access_reason=authz.decision.reason
            )
        result = self._jira().create_jira_issue_as_active_user(
            authz.ctx, project=project, summary=summary, description=description
        )
        audit_id = self._audit.record_write(
            active_user=active_user, system=System.JIRA, action="create_jira_issue",
            resource_ids=[result.resource_id] if result.resource_id else [],
        ).id
        return AssistantResponse(
            allowed=True,
            summary=f"Created Jira issue in {project} as {result.actor}: {summary}",
            actions_taken=[f"jira.create_jira_issue as {result.actor}: {result.resource_id}"],
            note=WRITE_NOTE,
            audit_event_ids=[audit_id],
        )

    def project_detail(
        self, active_user: str, *, project: str, client: str
    ) -> AssistantResponse:
        """Read Jira project issues, HubSpot company, and own Teams messages for a project."""
        findings: list[Finding] = []
        audit_ids: list[str] = []
        gaps: list[str] = []

        # Jira: shared system — target_user=None means self-tier
        jira_authz = self._authorize_read(
            active_user, None, System.JIRA, "get_project_issues",
            RequestedScope(project=project, client=client),
        )
        if jira_authz.ctx is not None:
            tasks = self._jira().get_project_issues(jira_authz.ctx, project)
            findings.extend(self._task_finding(t) for t in tasks)
            audit_ids.append(
                self._audit.record_read(
                    active_user=active_user, target_user=None, system=System.JIRA,
                    action="get_project_issues",
                    resource_ids=[t.id for t in tasks],
                    reason=jira_authz.decision.reason,
                ).id
            )
        else:
            gaps.append(f"Could not consult {System.JIRA}: {jira_authz.decision.reason}")

        # HubSpot: shared system — self-tier
        hs_authz = self._authorize_read(
            active_user, None, System.HUBSPOT, "get_company",
            RequestedScope(client=client),
        )
        if hs_authz.ctx is not None:
            company = self._hubspot().get_company_by_name_or_domain(hs_authz.ctx, client)
            if company:
                name = company.get("name", client)
                domain = company.get("domain", "")
                cid = company.get("id", "")
                findings.append(Finding(
                    text=f"Client {name} (domain {domain}) in HubSpot",
                    source="hubspot: company " + cid,
                ))
        else:
            gaps.append(f"Could not consult {System.HUBSPOT}: {hs_authz.decision.reason}")

        # Teams: self-tier (target_user=None) — may be refused due to missing connection/policy
        teams_scope = RequestedScope(
            client=client, project=project, date_range="last_90_days",
        )
        teams_authz = self._authorize_read(
            active_user, None, System.TEAMS, TeamsAction.SEARCH_MESSAGES, teams_scope
        )
        if teams_authz.ctx is not None:
            threads = self._teams().search_teams_messages(
                teams_authz.ctx, keywords=[project]
            )
            findings.extend(self._teams_finding(t) for t in threads)
            audit_ids.append(
                self._audit.record_read(
                    active_user=active_user, target_user=None, system=System.TEAMS,
                    action=TeamsAction.SEARCH_MESSAGES,
                    resource_ids=[t.id for t in threads],
                    permission_policy_used=teams_authz.decision.permission_policy_used,
                    reason=teams_authz.decision.reason,
                ).id
            )
        else:
            gaps.append(f"Could not consult {System.TEAMS}: {teams_authz.decision.reason}")

        summary = self._summarizer.summarize(
            f"Project detail: {project} for {client}", findings
        )
        return AssistantResponse(
            allowed=True,
            summary=summary.text,
            sources=summary.sources,
            access_reason="Shared project context (audited).",
            audit_event_ids=audit_ids,
            gaps=gaps,
        )

    def flagship(
        self, active_user: str, target_name: str, *, client: str, project: str
    ) -> AssistantResponse:
        """Read email + Teams (delegated), then create a Jira task — all writes as active_user."""
        keywords = ["API", "OAuth", "webhook", "sandbox"]
        email = self.search_email(
            active_user, target_name, client=client, project=project, keywords=keywords
        )
        if not email.allowed:
            return email
        teams = self.search_teams(
            active_user, target_name, client=client, project=project,
            channels=["ClientCo Delivery"], keywords=keywords,
        )
        if not teams.allowed:
            return teams

        write = self.create_jira_task(
            active_user, project=project,
            summary=f"Review {client} {project} preparation requirements",
        )

        return AssistantResponse(
            allowed=True,
            summary=email.summary + "\n\n" + teams.summary,
            sources=email.sources + teams.sources,
            actions_taken=write.actions_taken,
            access_reason=email.access_reason,
            note=WRITE_NOTE,
            audit_event_ids=email.audit_event_ids + teams.audit_event_ids + write.audit_event_ids,
        )

    # ------------------------------------------------------------------ helpers

    def _lookup_domain(self, active_user: str, client: str) -> str | None:
        authz = self._authorize_read(
            active_user, None, System.HUBSPOT, "get_company", RequestedScope(client=client)
        )
        if authz.ctx is None:
            return None
        company = self._hubspot().get_company_by_name_or_domain(authz.ctx, client)
        return company.get("domain") if company else None

    def _refusal(self, authz: _Authz, target_name: str, what: str) -> AssistantResponse:
        approval_id: str | None = None
        summary = (
            f"I can't access {target_name}'s {what} for this request: "
            f"{authz.decision.reason}. I can request approval."
        )
        if authz.decision.required_approval is not None and authz.req is not None:
            approval_req = self._engine.build_approval_request(authz.req, authz.decision)
            self._approvals.add(approval_req)
            approval_id = approval_req.id
            summary += f" (approval request {approval_id} created)"
        return AssistantResponse(
            allowed=False,
            summary=summary,
            access_reason=authz.decision.reason,
            approval_required=authz.decision.required_approval,
            approval_id=approval_id,
        )

    # ------------------------------------------------------------------ approval decisions

    def _get_pending_approval(self, approval_id: str) -> ApprovalRequest:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ApprovalNotFound(approval_id)
        if approval.status != "pending":
            raise ApprovalAlreadyDecided(approval_id, approval.status)
        return approval

    def grant_approval(self, approval_id: str, admin_user: str) -> ApprovalRequest:
        """Approve a pending request: materialize a scoped, auto-expiring policy per
        requested system, make it effective immediately, and mark the request granted.

        This is an admin decision, not a data access — it does not go through the
        Permission Engine itself. Every system granted still emits its own audit event
        (an admin action, not a read of anyone's data) so the decision is traceable in
        /admin like everything else (SECURITY_MODEL.md).
        """
        approval = self._get_pending_approval(approval_id)
        if approval.target_user is None:
            raise ValueError(f"approval {approval_id!r} has no target_user to grant access to")

        expiry = self._clock() + timedelta(days=GRANT_DURATION_DAYS)
        granted_policy_ids: list[str] = []
        for system in approval.systems_requested:
            if system == System.GMAIL:
                mailbox_policy = MailboxAccessPolicy(
                    mailbox_owner=approval.target_user,
                    allowed_requesters=[approval.requester],
                    scope=MailboxScope(
                        type="project_or_client",
                        client=approval.scope.client,
                        domain=approval.scope.domain,
                        project=approval.scope.project,
                    ),
                    allowed_actions=_GRANTED_GMAIL_ACTIONS,
                    expiry_date=expiry,
                )
                self._engine.add_mailbox_policy(mailbox_policy)
                if self._policy_store is not None:
                    self._policy_store.save_mailbox([mailbox_policy])
                granted_policy_ids.append(mailbox_policy.id)
            elif system == System.TEAMS:
                teams_policy = TeamsAccessPolicy(
                    target_user=approval.target_user,
                    allowed_requesters=[approval.requester],
                    allowed_channels=approval.scope.channels,
                    allowed_projects=[approval.scope.project] if approval.scope.project else [],
                    allowed_clients=[approval.scope.client] if approval.scope.client else [],
                    allowed_keywords=approval.scope.keywords,
                    allowed_participants=approval.scope.participants,
                    date_range=approval.scope.date_range,
                    allowed_actions=_GRANTED_TEAMS_ACTIONS,
                    expiry_date=expiry,
                )
                self._engine.add_teams_policy(teams_policy)
                if self._policy_store is not None:
                    self._policy_store.save_teams([teams_policy])
                granted_policy_ids.append(teams_policy.id)
            self._audit.record_write(
                active_user=admin_user, system=system, action="grant_delegated_access",
                target_user=approval.target_user, resource_ids=granted_policy_ids[-1:],
                resource_type="policy", approval_id=approval.id, result_status="granted",
                reason=f"approved by {admin_user}, expires {expiry.isoformat()}",
            )

        decided = approval.model_copy(
            update={"status": "granted", "approver": admin_user, "decided_at": self._clock()}
        )
        self._approvals.add(decided)
        return decided

    def deny_approval(self, approval_id: str, admin_user: str, reason: str = "") -> ApprovalRequest:
        """Deny a pending request. No policy is created; the decision itself is audited."""
        approval = self._get_pending_approval(approval_id)
        for system in approval.systems_requested:
            self._audit.record_write(
                active_user=admin_user, system=system, action="deny_delegated_access",
                target_user=approval.target_user, approval_id=approval.id,
                result_status="denied", reason=reason or f"denied by {admin_user}",
            )
        decided = approval.model_copy(
            update={
                "status": "denied",
                "approver": admin_user,
                "decided_at": self._clock(),
                "reason": reason or approval.reason,
            }
        )
        self._approvals.add(decided)
        return decided


def build_default_orchestrator(clock: Callable[[], date] = date.today) -> Orchestrator:
    resolver = IdentityResolver.from_seed()
    registry = ConnectionRegistry.from_seed()
    connectors = build_mock_registry()
    calendar = cast(CalendarPort, connectors[System.CALENDAR])
    engine = PermissionEngine.from_seed(
        resolver=resolver, absence_provider=_CalendarAbsence(calendar, clock), clock=clock
    )
    return Orchestrator(
        resolver=resolver,
        registry=registry,
        engine=engine,
        connectors=connectors,
        summarizer=StubSummarizer(),
        audit=AuditLog(),
        clock=clock,
    )
