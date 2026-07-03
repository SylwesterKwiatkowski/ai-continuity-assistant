"""Mock Google Sheets connector (spec §11.6)."""

from __future__ import annotations

from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.connectors.mock.data import anna_recurring_tasks
from assistant.domain.enums import ActionType, System
from assistant.domain.models import Task


class MockSheetsConnector(BaseConnector):
    system: ClassVar[System] = System.SHEETS

    def manifest(self) -> list[Capability]:
        return [
            Capability(system=self.system, action="get_recurring_tasks", access=ActionType.READ),
            Capability(system=self.system, action="get_project_tracker", access=ActionType.READ),
            Capability(system=self.system, action="append_row", access=ActionType.WRITE),
        ]

    def get_recurring_tasks(self, ctx: PermissionContext) -> list[Task]:
        self._guard(ctx, "get_recurring_tasks", ActionType.READ)
        target = ctx.target_user or ctx.active_user
        return [t for t in anna_recurring_tasks() if t.assignee == target]

    def append_sheet_row_as_active_user(
        self, ctx: PermissionContext, sheet_id: str, values: list[str]
    ) -> WriteResult:
        conn = self._guard(ctx, "append_row", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="append_row", actor=conn.user_id, resource_id=sheet_id
        )
