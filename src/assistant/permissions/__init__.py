"""Permissions layer — the default-deny Permission & Policy Engine (spec §7)."""

from assistant.permissions.approvals import ApprovalRepository, InMemoryApprovalRepository
from assistant.permissions.engine import AbsenceProvider, PermissionEngine
from assistant.permissions.policies import (
    ApprovalRequest,
    ApprovalType,
    MailboxAccessPolicy,
    MailboxScope,
    PermissionDecision,
    PermissionRequest,
    RequestedScope,
    TeamsAccessPolicy,
)

__all__ = [
    "AbsenceProvider",
    "ApprovalRepository",
    "ApprovalRequest",
    "ApprovalType",
    "InMemoryApprovalRepository",
    "MailboxAccessPolicy",
    "MailboxScope",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionRequest",
    "RequestedScope",
    "TeamsAccessPolicy",
]
