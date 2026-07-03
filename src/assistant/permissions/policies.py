"""Permission policies, requests, and decisions (spec §7).

Two policy types gate *delegated* reads of sensitive systems:
  - MailboxAccessPolicy  -> Gmail
  - TeamsAccessPolicy    -> Microsoft Teams

A PermissionRequest describes one operation; the PermissionEngine returns a PermissionDecision.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from assistant.domain.enums import AccessTier, ActionType, GmailAction, System, TeamsAction


class RequestedScope(BaseModel):
    """The scope an operation is asking for. Matched conjunctively against a policy."""

    client: str | None = None
    project: str | None = None
    domain: str | None = None
    channels: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    date_range: str | None = None


class MailboxScope(BaseModel):
    """Scope allowed by a MailboxAccessPolicy (spec §7.1)."""

    type: str | None = None
    client: str | None = None
    domain: str | None = None
    project: str | None = None


class MailboxAccessPolicy(BaseModel):
    """Delegated read policy over one person's mailbox (spec §7.1)."""

    mailbox_owner: str
    allowed_requesters: list[str]
    scope: MailboxScope = Field(default_factory=MailboxScope)
    allowed_actions: list[GmailAction] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expiry_date: date | None = None
    audit_required: bool = True


class TeamsAccessPolicy(BaseModel):
    """Delegated read policy over one person's Teams context (spec §7.1)."""

    target_user: str
    allowed_requesters: list[str]
    allowed_channels: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)
    allowed_clients: list[str] = Field(default_factory=list)
    allowed_keywords: list[str] = Field(default_factory=list)
    allowed_participants: list[str] = Field(default_factory=list)
    date_range: str | None = None
    allowed_actions: list[TeamsAction] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expiry_date: date | None = None
    audit_required: bool = True


class ApprovalType(StrEnum):
    """Who can approve a blocked request (spec §16)."""

    MAILBOX_OWNER = "mailbox_owner"
    MANAGER = "manager"
    PROJECT_OWNER = "project_owner"
    ADMIN = "admin"


class ApprovalRequest(BaseModel):
    """A request for approval when permission is absent/ambiguous (spec §16)."""

    id: str
    requester: str
    target_user: str | None = None
    approver: str | None = None
    approver_type: ApprovalType | None = None
    systems_requested: list[System] = Field(default_factory=list)
    scope: RequestedScope = Field(default_factory=RequestedScope)
    reason: str = ""
    expiry_date: date | None = None
    status: str = "pending"


class PermissionRequest(BaseModel):
    """One operation to authorize."""

    active_user: str
    system: System
    action: str
    action_type: ActionType
    target_user: str | None = None
    scope: RequestedScope = Field(default_factory=RequestedScope)
    actor: str | None = None  # for writes; defaults to active_user

    @property
    def resolved_actor(self) -> str:
        return self.actor or self.active_user


class PermissionDecision(BaseModel):
    """The engine's verdict for one operation (spec §7.4 / §10.3)."""

    allowed: bool
    access_tier: AccessTier
    allowed_actions: list[str] = Field(default_factory=list)
    scope: RequestedScope | None = None
    reason: str = ""
    required_approval: ApprovalType | None = None
    permission_policy_used: str | None = None
