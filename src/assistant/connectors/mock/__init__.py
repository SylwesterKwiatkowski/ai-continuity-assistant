"""Mock connectors + a registry builder used by tests and the MVP orchestrator."""

from assistant.connectors.base import BaseConnector
from assistant.connectors.mock.calendar import MockCalendarConnector
from assistant.connectors.mock.drive import MockDriveConnector
from assistant.connectors.mock.gmail import MockGmailConnector
from assistant.connectors.mock.hubspot import MockHubSpotConnector
from assistant.connectors.mock.jira import MockJiraConnector
from assistant.connectors.mock.sheets import MockSheetsConnector
from assistant.connectors.mock.teams import MockTeamsConnector
from assistant.domain.enums import System


def build_mock_registry() -> dict[System, BaseConnector]:
    """Return one mock connector instance per system."""
    connectors: list[BaseConnector] = [
        MockGmailConnector(),
        MockCalendarConnector(),
        MockTeamsConnector(),
        MockJiraConnector(),
        MockHubSpotConnector(),
        MockSheetsConnector(),
        MockDriveConnector(),
    ]
    return {c.system: c for c in connectors}


__all__ = [
    "MockCalendarConnector",
    "MockDriveConnector",
    "MockGmailConnector",
    "MockHubSpotConnector",
    "MockJiraConnector",
    "MockSheetsConnector",
    "MockTeamsConnector",
    "build_mock_registry",
]
