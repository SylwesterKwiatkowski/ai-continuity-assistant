"""Connectors layer — uniform SDK over external systems (spec §11)."""

from assistant.connectors.base import (
    BaseConnector,
    Capability,
    PermissionContext,
    UnauthorizedConnectorCall,
    WriteResult,
)
from assistant.connectors.protocols import (
    CalendarPort,
    GmailPort,
    HubSpotPort,
    JiraPort,
    SheetsPort,
    TeamsPort,
)

__all__ = [
    "BaseConnector",
    "CalendarPort",
    "Capability",
    "GmailPort",
    "HubSpotPort",
    "JiraPort",
    "PermissionContext",
    "SheetsPort",
    "TeamsPort",
    "UnauthorizedConnectorCall",
    "WriteResult",
]
