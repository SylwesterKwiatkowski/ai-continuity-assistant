"""Mock HubSpot connector (spec §11.5)."""

from __future__ import annotations

from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.domain.enums import ActionType, System

_COMPANIES: dict[str, dict[str, str]] = {
    "clientco": {"id": "hs-clientco", "name": "ClientCo", "domain": "clientco.com"},
}


class MockHubSpotConnector(BaseConnector):
    system: ClassVar[System] = System.HUBSPOT

    def manifest(self) -> list[Capability]:
        return [
            Capability(system=self.system, action="get_company", access=ActionType.READ),
            Capability(system=self.system, action="get_deals", access=ActionType.READ),
            Capability(system=self.system, action="create_note", access=ActionType.WRITE),
            Capability(system=self.system, action="create_task", access=ActionType.WRITE),
        ]

    def get_company_by_name_or_domain(
        self, ctx: PermissionContext, name_or_domain: str
    ) -> dict[str, str] | None:
        self._guard(ctx, "get_company", ActionType.READ)
        key = name_or_domain.lower().replace(".com", "")
        return _COMPANIES.get(key)

    def create_hubspot_note_as_active_user(
        self, ctx: PermissionContext, object_id: str, note_body: str
    ) -> WriteResult:
        conn = self._guard(ctx, "create_note", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="create_note", actor=conn.user_id, resource_id=object_id
        )

    def create_hubspot_task_as_active_user(
        self, ctx: PermissionContext, object_id: str, task_body: str
    ) -> WriteResult:
        conn = self._guard(ctx, "create_task", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="create_task", actor=conn.user_id, resource_id=object_id
        )
