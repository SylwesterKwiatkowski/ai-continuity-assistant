"""Deterministic summarizer stub (MVP, DECISIONS.md D9).

Builds a structured summary from already-condensed findings. It never fabricates content
and only echoes the snippet-level text it was given — it does not receive or emit raw bodies.
"""

from __future__ import annotations

from assistant.summarizer.base import Finding, Summary


class StubSummarizer:
    def summarize(self, query: str, findings: list[Finding]) -> Summary:
        if not findings:
            return Summary(text=f"No relevant information found for: {query}", sources=[])
        lines = [f"Summary for: {query}", ""]
        lines.extend(f"- {f.text}" for f in findings)
        # Preserve source order while de-duplicating.
        seen: set[str] = set()
        sources: list[str] = []
        for f in findings:
            if f.source and f.source not in seen:
                seen.add(f.source)
                sources.append(f.source)
        return Summary(text="\n".join(lines), sources=sources)
