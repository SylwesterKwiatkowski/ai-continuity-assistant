"""M4 — semantic layer: cross-tool linking + raw passthrough (D4)."""

from __future__ import annotations

from assistant.connectors.mock.data import (
    anna_email_threads,
    anna_jira_tasks,
    anna_teams_threads,
    clientco_project,
    teams_files,
)
from assistant.domain import System
from assistant.domain.models import EmailThread
from assistant.graph import EntityKind, build_graph


def make_graph() -> object:
    items: list[object] = [
        *anna_email_threads(),
        *anna_teams_threads(),
        *teams_files(),
        *anna_jira_tasks(),
        clientco_project(),
    ]
    return build_graph(items, domain_client_map={"clientco.com": "ClientCo"})


def test_everything_about_clientco_spans_multiple_systems() -> None:
    graph = make_graph()
    about = graph.about_client("ClientCo")
    systems = {n.source_system for n in about if n.source_system is not None}
    # Email (Gmail), Teams thread/file (Teams), and the API-12 Jira task must all link in.
    assert {System.GMAIL, System.TEAMS, System.JIRA} <= systems


def test_email_client_derived_from_domain_map() -> None:
    graph = make_graph()
    email_nodes = graph.nodes_of_kind(EntityKind.EMAIL_THREAD)
    assert email_nodes[0].client == "ClientCo"  # derived from dev@clientco.com


def test_raw_payload_is_preserved() -> None:
    graph = make_graph()
    email_nodes = graph.nodes_of_kind(EntityKind.EMAIL_THREAD)
    payload = email_nodes[0].payload
    assert isinstance(payload, EmailThread)
    assert payload.subject == "API preparation details"  # native data intact


def test_crm_task_without_client_not_linked_to_clientco() -> None:
    graph = make_graph()
    about_ids = {n.id for n in graph.about_client("ClientCo")}
    assert "API-12" in about_ids       # has client=ClientCo
    assert "CRM-241" not in about_ids  # no client -> not linked (no speculative inference)


def test_attachments_linked_to_their_thread() -> None:
    graph = make_graph()
    email_nodes = graph.nodes_of_kind(EntityKind.EMAIL_THREAD)
    attachments = graph.neighbors(email_nodes[0].ref, rel="has_attachment")
    names = {a.label for a in attachments}
    assert names == {"ClientCo_API_Integration_Brief.pdf", "Webhook_Requirements.xlsx"}


def test_project_and_people_links() -> None:
    graph = make_graph()
    about_project = graph.about_project("API Integration")
    kinds = {n.kind for n in about_project}
    # The API-12 task and the Teams thread both declare project "API Integration".
    assert EntityKind.TASK in kinds
    assert EntityKind.TEAMS_THREAD in kinds
