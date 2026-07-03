"""Summarizer interface (spec §10.4).

The summarizer reasons and condenses; it prefers a summary over dumping raw content and
always attributes sources. In MVP it is a deterministic stub so security tests stay
deterministic; a real LLM (e.g. Claude Opus 4.8) is wired later behind the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Finding:
    """One condensed, already-authorized fact plus where it came from."""

    text: str
    source: str  # human-readable source (system + link/label)


@dataclass
class Summary:
    text: str
    sources: list[str] = field(default_factory=list)


@runtime_checkable
class Summarizer(Protocol):
    def summarize(self, query: str, findings: list[Finding]) -> Summary: ...
