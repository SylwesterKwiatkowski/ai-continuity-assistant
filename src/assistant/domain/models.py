"""Normalized domain models (spec §12).

These are the common shapes that connector results are mapped into. Per DECISIONS.md D4,
normalization is a thin overlay: connectors may attach their full native payload in `raw`
so nothing is lost.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from assistant.domain.enums import System


class Person(BaseModel):
    """A person, with their handles across systems (spec §12.1)."""

    id: str
    name: str
    email: str
    teams_id: str | None = None
    jira_id: str | None = None
    hubspot_id: str | None = None
    manager_id: str | None = None
    backup_owners: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    # Deactivate, never hard-delete (ROADMAP.md v0.2.1): policies/connections/audit events
    # reference people by id, so removing a row would orphan them. The field exists from
    # this schema onward; enforcement (deny login, exclude from pickers, deny as a
    # requester) is v0.2.1 branch 2's job — see DECISIONS.md D22.
    active: bool = True

    def handle_for(self, system: System) -> str | None:
        """Return this person's identifier in `system`, or None if unmapped.

        Google Workspace systems are keyed by email; others by their per-system id.
        """
        mapping: dict[System, str | None] = {
            System.GMAIL: self.email,
            System.CALENDAR: self.email,
            System.SHEETS: self.email,
            System.DRIVE: self.email,
            System.TEAMS: self.teams_id,
            System.JIRA: self.jira_id,
            System.HUBSPOT: self.hubspot_id,
        }
        return mapping.get(system)


class Task(BaseModel):
    """A unit of work from Jira or Sheets (spec §12.2)."""

    id: str
    title: str
    source: System
    assignee: str | None = None
    due_date: date | None = None
    status: str | None = None
    project: str | None = None
    client: str | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


class Project(BaseModel):
    """A project spanning systems (spec §12.3)."""

    id: str
    name: str
    client: str | None = None
    owner: str | None = None
    status: str | None = None
    deadline: date | None = None
    source_links: list[str] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class Attachment(BaseModel):
    """An email attachment (spec §12.5)."""

    id: str
    filename: str
    mime_type: str | None = None
    source_email_thread: str | None = None
    permission_scope: str | None = None


class EmailThread(BaseModel):
    """A Gmail thread (spec §12.4)."""

    id: str
    mailbox_owner: str
    subject: str | None = None
    sender: str | None = None
    participants: list[str] = Field(default_factory=list)
    date: datetime | None = None
    snippet: str | None = None
    body: str | None = None  # full content; withheld in metadata-only views
    attachments: list[Attachment] = Field(default_factory=list)
    source_url: str | None = None
    raw: dict[str, Any] | None = None


class TeamsThread(BaseModel):
    """A Microsoft Teams thread (spec §12.6)."""

    id: str
    channel: str | None = None
    participants: list[str] = Field(default_factory=list)
    date: datetime | None = None
    snippet: str | None = None
    related_project: str | None = None
    related_client: str | None = None
    source_url: str | None = None
    raw: dict[str, Any] | None = None


class TeamsFile(BaseModel):
    """A file shared in Teams (spec §12.7)."""

    id: str
    filename: str
    mime_type: str | None = None
    channel: str | None = None
    shared_by: str | None = None
    shared_date: datetime | None = None
    related_project: str | None = None
    related_client: str | None = None
    source_url: str | None = None
