"""Mock Google Drive connector (our added system, D5)."""

from __future__ import annotations

from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.domain.enums import ActionType, System

_FILES: list[dict[str, str]] = [
    {
        "id": "drive-brief",
        "filename": "ClientCo_API_Integration_Brief.pdf",
        "mime_type": "application/pdf",
        "url": "https://drive.google.com/file/d/drive-brief",
    },
]


class MockDriveConnector(BaseConnector):
    system: ClassVar[System] = System.DRIVE

    def manifest(self) -> list[Capability]:
        return [
            Capability(system=self.system, action="search_files", access=ActionType.READ),
            Capability(system=self.system, action="get_file_metadata", access=ActionType.READ),
            Capability(system=self.system, action="create_file", access=ActionType.WRITE),
        ]

    def search_files(self, ctx: PermissionContext, query: str) -> list[dict[str, str]]:
        self._guard(ctx, "search_files", ActionType.READ)
        q = query.lower()
        return [f for f in _FILES if q in f["filename"].lower()]

    def create_file_as_active_user(
        self, ctx: PermissionContext, filename: str, content: str = ""
    ) -> WriteResult:
        conn = self._guard(ctx, "create_file", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="create_file", actor=conn.user_id, detail=filename
        )
