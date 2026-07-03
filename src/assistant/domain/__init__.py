"""Domain layer — normalized models and shared enums (spec §12)."""

from assistant.domain.enums import (
    AccessTier,
    ActionType,
    GmailAction,
    System,
    TeamsAction,
)
from assistant.domain.models import (
    Attachment,
    EmailThread,
    Person,
    Project,
    Task,
    TeamsFile,
    TeamsThread,
)

__all__ = [
    "AccessTier",
    "ActionType",
    "Attachment",
    "EmailThread",
    "GmailAction",
    "Person",
    "Project",
    "System",
    "Task",
    "TeamsAction",
    "TeamsFile",
    "TeamsThread",
]
