"""Deterministic fixtures for the mock connectors.

Centered on the spec's flagship scenario: Anna is out of office; ClientCo sent
"API preparation details" with attachments; there is a related Teams thread.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from assistant.domain.models import (
    Attachment,
    EmailThread,
    Project,
    Task,
    TeamsFile,
    TeamsThread,
)


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 9, 0, tzinfo=UTC)


# --- Gmail (Anna's mailbox) ---

def anna_email_threads() -> list[EmailThread]:
    return [
        EmailThread(
            id="thr-clientco-api",
            mailbox_owner="anna",
            subject="API preparation details",
            sender="dev@clientco.com",
            participants=["anna@acme.com", "dev@clientco.com"],
            date=_dt(2026, 6, 21),
            snippet=(
                "ClientCo requests OAuth 2.0 support. Sandbox endpoint must be ready before "
                "July 5. Please confirm webhook retry behavior. Field mapping attached."
            ),
            body=(
                "SENTINEL_FULL_BODY_DO_NOT_LEAK — Hi Anna, here is the detailed brief. "
                "Also, unrelated: my personal mobile is 555-0100 and my home address is private. "
                "Please keep the OAuth scopes to read-only for the sandbox."
            ),
            attachments=[
                Attachment(
                    id="att-brief",
                    filename="ClientCo_API_Integration_Brief.pdf",
                    mime_type="application/pdf",
                    source_email_thread="thr-clientco-api",
                    permission_scope="ClientCo/API Integration",
                ),
                Attachment(
                    id="att-webhooks",
                    filename="Webhook_Requirements.xlsx",
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    source_email_thread="thr-clientco-api",
                    permission_scope="ClientCo/API Integration",
                ),
            ],
            source_url="https://mail.google.com/mail/u/0/#inbox/thr-clientco-api",
        ),
    ]


# --- Teams ---

def anna_teams_threads() -> list[TeamsThread]:
    return [
        TeamsThread(
            id="teams-clientco-0624",
            channel="ClientCo Delivery",
            participants=["anna", "mark", "backend-lead"],
            date=_dt(2026, 6, 24),
            snippet=(
                "Anna: the backend team should review the endpoints before the next ClientCo "
                "meeting. We still owe them the webhook retry policy."
            ),
            related_project="API Integration",
            related_client="ClientCo",
            source_url="https://teams.microsoft.com/l/message/clientco-delivery/0624",
        ),
    ]


def teams_files() -> list[TeamsFile]:
    return [
        TeamsFile(
            id="tf-endpoints",
            filename="ClientCo_Endpoints_Draft.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            channel="ClientCo Delivery",
            shared_by="anna",
            shared_date=_dt(2026, 6, 24),
            related_project="API Integration",
            related_client="ClientCo",
            source_url="https://teams.microsoft.com/l/file/tf-endpoints",
        ),
    ]


# --- Jira (issues assigned to Anna) ---

def anna_jira_tasks() -> list[Task]:
    from assistant.domain.enums import System

    return [
        Task(
            id="CRM-241",
            title="Migrate legacy CRM contacts",
            source=System.JIRA,
            assignee="anna",
            due_date=date(2026, 6, 30),  # overdue relative to 2026-07-03
            status="In Progress",
            project="CRM Migration",
            url="https://acme.atlassian.net/browse/CRM-241",
        ),
        Task(
            id="API-12",
            title="Implement OAuth 2.0 token exchange",
            source=System.JIRA,
            assignee="anna",
            due_date=date(2026, 7, 5),
            status="To Do",
            project="API Integration",
            client="ClientCo",
            url="https://acme.atlassian.net/browse/API-12",
        ),
    ]


# --- Google Sheets (recurring tasks) ---

def anna_recurring_tasks() -> list[Task]:
    from assistant.domain.enums import System

    return [
        Task(
            id="sheet-row-7",
            title="Weekly data validation",
            source=System.SHEETS,
            assignee="anna",
            due_date=date(2026, 7, 3),  # Friday
            status="Pending",
            project="CRM Migration",
            url="https://docs.google.com/spreadsheets/d/tracker#gid=0&row=7",
        ),
    ]


# --- HubSpot / Projects ---

def clientco_project() -> Project:
    return Project(
        id="proj-api-integration",
        name="API Integration",
        client="ClientCo",
        owner="anna",
        status="Active",
        deadline=date(2026, 7, 5),
        source_links=["https://acme.atlassian.net/browse/API-12"],
    )
