"""Conjunctive, default-deny scope matching (DECISIONS.md D11).

A request is "in scope" only if, for every dimension the policy constrains, the request
specifies a matching value. A broader (or unspecified) request than the policy allows is
denied — we never widen access by omission.
"""

from __future__ import annotations

from assistant.permissions.policies import MailboxScope, RequestedScope, TeamsAccessPolicy


def _eq(a: str | None, b: str | None) -> bool:
    """Case-insensitive equality for present strings."""
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def _subset_ci(requested: list[str], allowed: list[str]) -> bool:
    """True if every requested item is within the allowed set (case-insensitive)."""
    allowed_ci = {x.strip().lower() for x in allowed}
    return all(item.strip().lower() in allowed_ci for item in requested)


def mailbox_scope_matches(req: RequestedScope, policy: MailboxScope) -> tuple[bool, str]:
    """Return (matches, reason). Every constrained dimension must be matched by the request."""
    if policy.client and not _eq(req.client, policy.client):
        return False, f"client out of scope (requires {policy.client!r})"
    if policy.project and not _eq(req.project, policy.project):
        return False, f"project out of scope (requires {policy.project!r})"
    if policy.domain and not _eq(req.domain, policy.domain):
        return False, f"domain out of scope (requires {policy.domain!r})"
    return True, ""


def teams_scope_matches(req: RequestedScope, policy: TeamsAccessPolicy) -> tuple[bool, str]:
    """Return (matches, reason) for a Teams request against a TeamsAccessPolicy."""
    client_ok = bool(req.client) and _subset_ci([req.client or ""], policy.allowed_clients)
    if policy.allowed_clients and not client_ok:
        return False, f"client out of scope (allowed: {policy.allowed_clients})"

    project_ok = bool(req.project) and _subset_ci([req.project or ""], policy.allowed_projects)
    if policy.allowed_projects and not project_ok:
        return False, f"project out of scope (allowed: {policy.allowed_projects})"

    if policy.allowed_channels and req.channels:
        if not _subset_ci(req.channels, policy.allowed_channels):
            return False, "one or more requested channels are out of scope"

    if policy.allowed_keywords and req.keywords:
        if not _subset_ci(req.keywords, policy.allowed_keywords):
            return False, "one or more requested keywords are out of scope"

    if policy.date_range is not None and req.date_range is not None:
        if policy.date_range.strip().lower() != req.date_range.strip().lower():
            return False, f"date range out of scope (allowed: {policy.date_range})"

    if policy.allowed_participants and req.participants:
        if not _subset_ci(req.participants, policy.allowed_participants):
            return False, "one or more requested participants are out of scope"

    return True, ""
