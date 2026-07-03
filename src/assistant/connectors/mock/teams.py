"""Mock Microsoft Teams connector (spec §11.3)."""

from __future__ import annotations

from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.connectors.mock.data import anna_teams_threads, teams_files
from assistant.domain.enums import ActionType, System, TeamsAction
from assistant.domain.models import TeamsFile, TeamsThread


class MockTeamsConnector(BaseConnector):
    system: ClassVar[System] = System.TEAMS

    def manifest(self) -> list[Capability]:
        reads = (
            TeamsAction.SEARCH_MESSAGES,
            TeamsAction.READ_THREAD,
            TeamsAction.RETRIEVE_FILE,
        )
        writes = ("post_message", "reply_to_thread", "share_file")
        caps: list[Capability] = [
            Capability(
                system=self.system,
                action=a,
                access=ActionType.READ,
                sensitivity="sensitive",
                requires_scope=True,
            )
            for a in reads
        ]
        caps += [
            Capability(system=self.system, action=a, access=ActionType.WRITE) for a in writes
        ]
        return caps

    # --- reads ---

    def search_teams_messages(
        self, ctx: PermissionContext, keywords: list[str]
    ) -> list[TeamsThread]:
        self._guard(ctx, TeamsAction.SEARCH_MESSAGES, ActionType.READ)
        target = ctx.target_user or ctx.active_user
        return [t for t in anna_teams_threads() if target in t.participants]

    def read_teams_thread(self, ctx: PermissionContext, thread_id: str) -> TeamsThread | None:
        self._guard(ctx, TeamsAction.READ_THREAD, ActionType.READ)
        for t in anna_teams_threads():
            if t.id == thread_id:
                return t
        return None

    def list_teams_files(self, ctx: PermissionContext) -> list[TeamsFile]:
        self._guard(ctx, TeamsAction.RETRIEVE_FILE, ActionType.READ)
        return teams_files()

    # --- writes (always as the active_user) ---

    def send_teams_message_as_active_user(
        self, ctx: PermissionContext, channel_or_chat: str, message: str
    ) -> WriteResult:
        conn = self._guard(ctx, "post_message", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="post_message",
            actor=conn.user_id,
            detail=f"posted to {channel_or_chat}",
        )

    def reply_to_teams_thread_as_active_user(
        self, ctx: PermissionContext, thread_id: str, message: str
    ) -> WriteResult:
        conn = self._guard(ctx, "reply_to_thread", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="reply_to_thread", actor=conn.user_id, resource_id=thread_id
        )

    def share_teams_file_as_active_user(
        self, ctx: PermissionContext, file_id: str, destination: str
    ) -> WriteResult:
        conn = self._guard(ctx, "share_file", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="share_file",
            actor=conn.user_id,
            resource_id=file_id,
            detail=f"shared to {destination}",
        )
