"""Agent Orchestrator (spec §10.2).

Coordinates every flow: resolve identities -> ask the Permission Engine -> resolve the correct
connection -> call the connector -> normalize + summarize -> audit. The orchestrator NEVER calls
a connector without an approving decision, and every write goes out as the active_user.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
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
from assistant.permissions.approvals import ApprovalRepository, InMemoryApprovalRepository
from assistant.permissions.engine import PermissionEngine
from assistant.permissions.policies import (
    PermissionDecision,
    PermissionRequest,
    RequestedScope,
)
from assistant.summarizer.base import Finding, Summarizer
from assistant.summarizer.stub import StubSummarizer

WRITE_NOTE = "No action taken as the target. All write actions executed as the active_user."


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
    ) -> None:
        self._resolver = resolver
        self._registry = registry
        self._engine = engine
        self._connectors = connectors
        self._summarizer = summarizer
        self._audit = audit
        self._approvals: ApprovalRepository = approvals or InMemoryApprovalRepository()

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
    )
