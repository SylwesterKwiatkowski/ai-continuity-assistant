"""Summarizer layer — reason + condense + cite (spec §10.4)."""

from assistant.summarizer.base import Finding, Summarizer, Summary
from assistant.summarizer.stub import StubSummarizer

__all__ = [
    "Finding",
    "StubSummarizer",
    "Summarizer",
    "Summary",
]
