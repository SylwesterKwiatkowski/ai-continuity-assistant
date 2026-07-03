"""Build an EntityGraph from heterogeneous connector results (thin normalization).

Links are inferred only from explicit fields (client, project, assignee, participants) plus
an optional domain→client map for email/threads. No speculative inference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from assistant.domain.models import (
    EmailThread,
    Project,
    Task,
    TeamsFile,
    TeamsThread,
)
from assistant.graph.entities import EntityGraph, EntityKind, Node, Ref


def build_graph(
    items: Iterable[object],
    *,
    domain_client_map: Mapping[str, str] | None = None,
) -> EntityGraph:
    graph = EntityGraph()
    dcm = {k.lower(): v for k, v in (domain_client_map or {}).items()}
    for item in items:
        if isinstance(item, Task):
            _add_task(graph, item)
        elif isinstance(item, EmailThread):
            _add_email_thread(graph, item, dcm)
        elif isinstance(item, TeamsThread):
            _add_teams_thread(graph, item)
        elif isinstance(item, TeamsFile):
            _add_teams_file(graph, item)
        elif isinstance(item, Project):
            _add_project(graph, item)
    return graph


def _domain(address: str) -> str:
    return address.split("@")[-1].strip().lower() if "@" in address else ""


def _link_client(graph: EntityGraph, ref: Ref, client: str | None) -> None:
    if not client:
        return
    client_ref = graph.add_node(
        Node(kind=EntityKind.CLIENT, id=client, label=client, client=client)
    ).ref
    graph.add_edge(ref, "about_client", client_ref)


def _link_project(graph: EntityGraph, ref: Ref, project: str | None, client: str | None) -> None:
    if not project:
        return
    project_ref = graph.add_node(
        Node(kind=EntityKind.PROJECT, id=project, label=project, project=project, client=client)
    ).ref
    graph.add_edge(ref, "about_project", project_ref)


def _link_person(graph: EntityGraph, ref: Ref, person: str, rel: str) -> None:
    person_ref = graph.add_node(
        Node(kind=EntityKind.PERSON, id=person, label=person)
    ).ref
    graph.add_edge(ref, rel, person_ref)


def _add_task(graph: EntityGraph, task: Task) -> None:
    node = graph.add_node(
        Node(
            kind=EntityKind.TASK,
            id=task.id,
            label=task.title,
            client=task.client,
            project=task.project,
            people=[task.assignee] if task.assignee else [],
            url=task.url,
            source_system=task.source,
            payload=task,
        )
    )
    _link_client(graph, node.ref, task.client)
    _link_project(graph, node.ref, task.project, task.client)
    if task.assignee:
        _link_person(graph, node.ref, task.assignee, "assigned_to")


def _add_email_thread(graph: EntityGraph, thread: EmailThread, dcm: dict[str, str]) -> None:
    from assistant.domain.enums import System

    client: str | None = None
    for addr in [thread.sender or "", *thread.participants]:
        mapped = dcm.get(_domain(addr))
        if mapped:
            client = mapped
            break

    node = graph.add_node(
        Node(
            kind=EntityKind.EMAIL_THREAD,
            id=thread.id,
            label=thread.subject or "(no subject)",
            client=client,
            people=[thread.mailbox_owner, *thread.participants],
            url=thread.source_url,
            source_system=System.GMAIL,
            payload=thread,
        )
    )
    _link_client(graph, node.ref, client)
    _link_person(graph, node.ref, thread.mailbox_owner, "in_mailbox_of")
    for att in thread.attachments:
        att_ref = graph.add_node(
            Node(
                kind=EntityKind.ATTACHMENT,
                id=att.id,
                label=att.filename,
                client=client,
                source_system=System.GMAIL,
                payload=att,
            )
        ).ref
        graph.add_edge(node.ref, "has_attachment", att_ref)


def _add_teams_thread(graph: EntityGraph, thread: TeamsThread) -> None:
    from assistant.domain.enums import System

    node = graph.add_node(
        Node(
            kind=EntityKind.TEAMS_THREAD,
            id=thread.id,
            label=thread.snippet or thread.channel or thread.id,
            client=thread.related_client,
            project=thread.related_project,
            people=list(thread.participants),
            url=thread.source_url,
            source_system=System.TEAMS,
            payload=thread,
        )
    )
    _link_client(graph, node.ref, thread.related_client)
    _link_project(graph, node.ref, thread.related_project, thread.related_client)
    for person in thread.participants:
        _link_person(graph, node.ref, person, "participant")


def _add_teams_file(graph: EntityGraph, file: TeamsFile) -> None:
    from assistant.domain.enums import System

    node = graph.add_node(
        Node(
            kind=EntityKind.TEAMS_FILE,
            id=file.id,
            label=file.filename,
            client=file.related_client,
            project=file.related_project,
            people=[file.shared_by] if file.shared_by else [],
            url=file.source_url,
            source_system=System.TEAMS,
            payload=file,
        )
    )
    _link_client(graph, node.ref, file.related_client)
    _link_project(graph, node.ref, file.related_project, file.related_client)


def _add_project(graph: EntityGraph, project: Project) -> None:
    node = graph.add_node(
        Node(
            kind=EntityKind.PROJECT,
            id=project.name,
            label=project.name,
            client=project.client,
            project=project.name,
            people=[project.owner] if project.owner else [],
            payload=project,
        )
    )
    _link_client(graph, node.ref, project.client)
    if project.owner:
        _link_person(graph, node.ref, project.owner, "owned_by")
