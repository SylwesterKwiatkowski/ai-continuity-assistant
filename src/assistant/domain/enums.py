"""Enumerations shared across the domain.

Action levels mirror the spec's Gmail/Teams access tiers (SECURITY_MODEL.md).
"""

from __future__ import annotations

from enum import StrEnum


class System(StrEnum):
    """External systems the assistant can connect to."""

    GMAIL = "gmail"
    CALENDAR = "calendar"
    TEAMS = "teams"
    JIRA = "jira"
    HUBSPOT = "hubspot"
    SHEETS = "sheets"
    DRIVE = "drive"


class ActionType(StrEnum):
    """Coarse action classification — validated separately by the Permission Engine."""

    READ = "read"
    WRITE = "write"


class AccessTier(StrEnum):
    """Whose data is being accessed (see SECURITY_MODEL.md)."""

    SELF = "self"
    SHARED = "shared"
    DELEGATED = "delegated"


class GmailAction(StrEnum):
    """Gmail action levels, least → most privileged."""

    SEARCH_METADATA = "search_metadata"
    READ_THREAD = "read_thread"
    SUMMARIZE = "summarize"
    RETRIEVE_ATTACHMENT = "retrieve_attachment"
    FORWARD_ATTACHMENT = "forward_attachment"
    FULL_MAILBOX_ACCESS = "full_mailbox_access"  # avoided; not implemented in MVP


class TeamsAction(StrEnum):
    """Microsoft Teams action levels."""

    SEARCH_MESSAGES = "search_messages"
    READ_THREAD = "read_thread"
    SUMMARIZE = "summarize"
    RETRIEVE_FILE = "retrieve_file"
    POST_MESSAGE = "post_message"  # only as active_user
