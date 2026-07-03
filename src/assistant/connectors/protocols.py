"""Connector port protocols — the orchestrator depends only on these, not on mock classes."""

from __future__ import annotations

from typing import Protocol

from assistant.connectors.base import PermissionContext, WriteResult
from assistant.domain.models import EmailThread, Task, TeamsThread


class GmailPort(Protocol):
    def search_email_metadata(self, ctx: PermissionContext, query: str) -> list[EmailThread]: ...


class TeamsPort(Protocol):
    def search_teams_messages(
        self, ctx: PermissionContext, keywords: list[str]
    ) -> list[TeamsThread]: ...


class JiraPort(Protocol):
    def get_assigned_issues(self, ctx: PermissionContext) -> list[Task]: ...

    def get_project_issues(self, ctx: PermissionContext, project: str) -> list[Task]: ...

    def create_jira_issue_as_active_user(
        self, ctx: PermissionContext, project: str, summary: str, description: str = ...
    ) -> WriteResult: ...


class SheetsPort(Protocol):
    def get_recurring_tasks(self, ctx: PermissionContext) -> list[Task]: ...


class HubSpotPort(Protocol):
    def get_company_by_name_or_domain(
        self, ctx: PermissionContext, name_or_domain: str
    ) -> dict[str, str] | None: ...


class CalendarPort(Protocol):
    def is_out_of_office(self, user_id: str, on: object = ...) -> bool: ...
