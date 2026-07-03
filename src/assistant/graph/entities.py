"""Entity graph structures (semantic overlay, DECISIONS.md D4).

This is a thin linking layer, NOT a canonical store: each Node keeps the original domain
object in `payload`, so nothing is lost and downstream summarization still sees native data.
The graph exists to answer "what is related to what" (e.g. everything about ClientCo) and to
support precise scoping — it does not decide what the assistant is allowed to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from assistant.domain.enums import System

Ref = tuple["EntityKind", str]


class EntityKind(StrEnum):
    PERSON = "person"
    CLIENT = "client"
    PROJECT = "project"
    TASK = "task"
    EMAIL_THREAD = "email_thread"
    TEAMS_THREAD = "teams_thread"
    TEAMS_FILE = "teams_file"
    ATTACHMENT = "attachment"


@dataclass
class Node:
    kind: EntityKind
    id: str
    label: str
    client: str | None = None
    project: str | None = None
    people: list[str] = field(default_factory=list)
    url: str | None = None
    source_system: System | None = None
    payload: object | None = None  # the original domain model (raw passthrough)

    @property
    def ref(self) -> Ref:
        return (self.kind, self.id)


@dataclass
class Edge:
    src: Ref
    rel: str
    dst: Ref


class EntityGraph:
    """An in-memory graph of nodes and typed edges."""

    def __init__(self) -> None:
        self.nodes: dict[Ref, Node] = {}
        self.edges: list[Edge] = []

    def add_node(self, node: Node) -> Node:
        # First writer wins for identity; later ones enrich missing client/project.
        existing = self.nodes.get(node.ref)
        if existing is None:
            self.nodes[node.ref] = node
            return node
        existing.client = existing.client or node.client
        existing.project = existing.project or node.project
        return existing

    def add_edge(self, src: Ref, rel: str, dst: Ref) -> None:
        edge = Edge(src=src, rel=rel, dst=dst)
        if edge not in self.edges:
            self.edges.append(edge)

    def nodes_of_kind(self, kind: EntityKind) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def about_client(self, client: str) -> list[Node]:
        c = client.strip().lower()
        return [
            n
            for n in self.nodes.values()
            if n.kind != EntityKind.CLIENT and (n.client or "").strip().lower() == c
        ]

    def about_project(self, project: str) -> list[Node]:
        p = project.strip().lower()
        return [
            n
            for n in self.nodes.values()
            if n.kind != EntityKind.PROJECT and (n.project or "").strip().lower() == p
        ]

    def neighbors(self, ref: Ref, rel: str | None = None) -> list[Node]:
        out: list[Node] = []
        for e in self.edges:
            if e.src == ref and (rel is None or e.rel == rel) and e.dst in self.nodes:
                out.append(self.nodes[e.dst])
        return out
