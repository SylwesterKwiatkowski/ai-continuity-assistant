"""Audit event model (spec §12.8 / §15).

One record per sensitive read and per write. The shape deliberately distinguishes
requester/active_user vs target_user, read vs write, and records actor_for_write_action.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from assistant.domain.enums import ActionType, System


class AuditEvent(BaseModel):
    id: str
    timestamp: datetime
    active_user: str
    target_user: str | None = None
    action_type: ActionType
    system_accessed: System
    action: str | None = None
    search_query: str | None = None
    resource_ids: list[str] = Field(default_factory=list)
    resource_type: str | None = None
    attachments_accessed: list[str] = Field(default_factory=list)
    files_accessed: list[str] = Field(default_factory=list)
    permission_policy_used: str | None = None
    approval_id: str | None = None
    actor_for_write_action: str | None = None
    result_status: str = "allowed"
    reason: str | None = None
