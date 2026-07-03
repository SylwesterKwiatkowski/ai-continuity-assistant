"""Structured response returned by orchestrator flows."""

from __future__ import annotations

from pydantic import BaseModel, Field

from assistant.permissions.policies import ApprovalType


class AssistantResponse(BaseModel):
    allowed: bool
    summary: str
    sources: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    access_reason: str = ""
    approval_required: ApprovalType | None = None
    approval_id: str | None = None
    note: str = ""
    audit_event_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
