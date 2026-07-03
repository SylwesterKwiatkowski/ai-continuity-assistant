"""Mock Gmail connector (spec §11.1)."""

from __future__ import annotations

from typing import ClassVar

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    WriteResult,
)
from assistant.connectors.mock.data import anna_email_threads
from assistant.domain.enums import ActionType, GmailAction, System
from assistant.domain.models import Attachment, EmailThread


class MockGmailConnector(BaseConnector):
    system: ClassVar[System] = System.GMAIL

    def manifest(self) -> list[Capability]:
        reads = (
            GmailAction.SEARCH_METADATA,
            GmailAction.READ_THREAD,
            GmailAction.RETRIEVE_ATTACHMENT,
        )
        writes = ("send_email", "create_draft", "forward_attachment")
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

    # --- reads (use the target's connection) ---

    def search_email_metadata(
        self, ctx: PermissionContext, query: str
    ) -> list[EmailThread]:
        self._guard(ctx, GmailAction.SEARCH_METADATA, ActionType.READ)
        owner = ctx.target_user or ctx.active_user
        # Metadata-only view: full bodies and raw payloads are withheld until read_thread.
        threads = [t for t in anna_email_threads() if t.mailbox_owner == owner]
        return [t.model_copy(update={"raw": None, "body": None}) for t in threads]

    def read_email_thread(self, ctx: PermissionContext, thread_id: str) -> EmailThread | None:
        self._guard(ctx, GmailAction.READ_THREAD, ActionType.READ)
        for t in anna_email_threads():
            if t.id == thread_id:
                return t
        return None

    def list_attachments(self, ctx: PermissionContext, thread_id: str) -> list[Attachment]:
        self._guard(ctx, GmailAction.RETRIEVE_ATTACHMENT, ActionType.READ)
        for t in anna_email_threads():
            if t.id == thread_id:
                return list(t.attachments)
        return []

    # --- writes (always as the active_user) ---

    def send_email_as_active_user(
        self, ctx: PermissionContext, to: str, subject: str, body: str
    ) -> WriteResult:
        conn = self._guard(ctx, "send_email", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="send_email",
            actor=conn.user_id,
            detail=f"sent to {to} — {subject}",
        )

    def create_draft_as_active_user(
        self, ctx: PermissionContext, to: str, subject: str, body: str
    ) -> WriteResult:
        conn = self._guard(ctx, "create_draft", ActionType.WRITE)
        return WriteResult(
            system=self.system, action="create_draft", actor=conn.user_id, detail=subject
        )

    def forward_attachment_as_active_user(
        self, ctx: PermissionContext, attachment_id: str, recipient: str
    ) -> WriteResult:
        conn = self._guard(ctx, "forward_attachment", ActionType.WRITE)
        return WriteResult(
            system=self.system,
            action="forward_attachment",
            actor=conn.user_id,
            resource_id=attachment_id,
            detail=f"forwarded to {recipient}",
        )
