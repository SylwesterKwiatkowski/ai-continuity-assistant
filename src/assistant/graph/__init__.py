"""Semantic layer — thin linking overlay over connector results (D4)."""

from assistant.graph.build import build_graph
from assistant.graph.entities import Edge, EntityGraph, EntityKind, Node

__all__ = [
    "Edge",
    "EntityGraph",
    "EntityKind",
    "Node",
    "build_graph",
]
