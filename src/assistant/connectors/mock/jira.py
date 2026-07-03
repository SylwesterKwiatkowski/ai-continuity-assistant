"""Mock Jira connector (spec §11.4)."""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.connectors.mock.data import anna_jira_tasks
from assistant.domain.enums import ActionType, System
from assistant.domain.models import Task


class MockJiraConnector(BaseConnector):
    system: ClassVar[System] = System.JIRA

    def manifest(self) -> list[Capability]:
        return [
            Capability(system=self.system, action="get_assigned_issues", access=ActionType.READ),
            Capability(system=self.system, action="get_project_issues", access=ActionType.READ),
            Capability(system=self.system, action="get_blockers", access=ActionType.READ),
            Capability(system=self.system, action="create_jira_issue", access=ActionType.WRITE),
            Capability(system=self.system, action="comment_jira_issue", access=ActionType.WRITE),
        ]

    def get_assigned_issues(self, ctx: PermissionContext) -> list[Task]:
        self._guard(ctx, "get_assigned_issues", ActionType.READ)
        target = ctx.target_user or ctx.active_user
        return [t for t in anna_jira_tasks() if t.assignee == target]

    def get_project_issues(self, ctx: PermissionContext, project: str) -> list[Task]:
        self._guard(ctx, "get_project_issues", ActionType.READ)
        return [t for t in anna_jira_tasks() if t.project == project]

    def get_blockers(self, ctx: PermissionContext, today: date | None = None) -> list[Task]:
        self._guard(ctx, "get_blockers", ActionType.READ)
        # A blocker here = an overdue issue.
        effective_today = today or date.today()
        return [
            t for t in anna_jira_tasks() if t.due_date is not None and t.due_date < effective_today
        ]

    def create_jira_issue_as_active_user(
        self, ctx: PermissionContext, project: str, summary: str, description: str = ""
    ) -> WriteResult:
        conn = self._guard(ctx, "create_jira_issue", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="create_jira_issue",
            actor=conn.user_id,
            resource_id=f"{project}-NEW",
            detail=summary,
        )

    def comment_on_jira_issue_as_active_user(
        self, ctx: PermissionContext, issue_id: str, comment: str
    ) -> WriteResult:
        conn = self._guard(ctx, "comment_jira_issue", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="comment_jira_issue",
            actor=conn.user_id,
            resource_id=issue_id,
        )
