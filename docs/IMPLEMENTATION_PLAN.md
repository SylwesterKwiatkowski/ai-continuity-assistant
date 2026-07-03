# Implementation Plan

Living document. Updated each implementation loop.

## Guiding principles

- Security substrate first (identity, permission engine, audit, mocks) before any real integration.
- Small, verified loops: one task → change → tests → summary → confirm → next.
- Connectors are dependency-injected; mocks stand in until permission tests pass.
- No real external API calls before mock connectors + permission tests exist.

## Current MVP scope

- **Stack:** Python 3.12 + FastAPI + Pydantic v2; SQLite (repos), pytest, ruff, mypy.
- **Positioning:** 3-tier assistant (self / shared / delegated); continuity = a delegated mode.
- **Baked in now:** Connector SDK (capability manifests) + semantic/entity graph
  (thin linking overlay with full raw passthrough).
- **Connectors (mock first):** Gmail, Google Calendar, Microsoft Teams, Jira, HubSpot,
  Google Sheets, Google Drive.
- **Connections:** per-user, self-service; token store behind an interface (stub in MVP).
- **Summarizer:** deterministic stub (real LLM wired later).
- **Interfaces:** HTTP API (backbone) + a **simple web app** (FastAPI + Jinja2 + HTMX):
  query/chat, Connections page, action confirmation, and a read-only admin audit/policy view.
  Teams bot deferred.

## Phased roadmap

### M0 — Skeleton & config  ✅ DONE
- `pyproject.toml`, package layout, settings (`config.py`), `.env.example`, seeds dir.
- **Milestone:** `pytest`/ruff/mypy green. (Python 3.12.13 installed.)

### M1 — Domain, identity, connections  ✅ DONE
- Domain models (§ below). Identity mapping + name→Person resolver from `seeds/people.json`.
- Connection registry + `TokenStore` interface (stub). Credential resolution rule
  (read→target, write→active).
- **Milestone:** resolve "Anna" → Person → per-system handles; resolve correct connection per call.

### M2 — Permission Engine + Audit  *(security core)*  ✅ DONE
- Policy models (`MailboxAccessPolicy`, `TeamsAccessPolicy`, `ApprovalRequest`) + seed policies.
- `PermissionEngine.check()` — tier detection, conjunctive scope match, conditions (OOO), expiry,
  separate read/write validation, approval decisions.
- Audit write-through (`AuditLog`) + transparency-to-target hook.
- **Milestone:** permission + audit unit tests pass (32 tests total). *No connector wired yet.*

### M3 — Connector SDK + mock connectors  ✅ DONE
- `BaseConnector` + `Capability` manifest + `PermissionContext`/`WriteResult`; `_guard` enforces
  authorization AND the credential rule at the connector boundary.
- 7 mock connectors with fixtures (OOO Anna + ClientCo "API preparation details" thread + Teams
  thread + Jira/Sheets tasks); `build_mock_registry()`.
- **Milestone:** connectors callable only via an approved decision; guard test passes (43 tests).

### M4 — Semantic layer  ✅ DONE
- `EntityGraph` (nodes + typed edges), `build_graph()` normalizes Task/EmailThread/TeamsThread/
  TeamsFile/Project into linked nodes; links inferred only from explicit fields + a domain→client
  map. Raw domain object preserved in `Node.payload`.
- Queries: `about_client`, `about_project`, `neighbors`, `nodes_of_kind`.
- **Milestone:** "everything about ClientCo" links Gmail + Teams + Jira (≥3 systems); 49 tests.

### M5 — Orchestrator + core flows (on mocks)  ✅ DONE
- `Orchestrator` wires resolve → Permission Engine → Connection Registry → connector → graph/
  summarizer → audit; `build_default_orchestrator()`. Deterministic `StubSummarizer`.
- Flows: weekly tasks · delegated Gmail search · delegated Teams search · write-as-active_user
  (Jira) · flagship combined flow. Blocked reads return a safe refusal + approval type.
- **Milestone:** flows return summary + sources + audit events; flagship runs end-to-end;
  raw body never leaked. *(project-detail flow deferred to a follow-up loop.)*

### Hardening pass (post-M5)  ✅ DONE
- Teams scope now enforces `date_range` + `allowed_participants` (closes the open scope gap).
- Blocked delegated reads persist a pending `ApprovalRequest` and return its id (D10 fulfilled).
- Orchestrator decoupled from mock classes via connector Ports (`connectors/protocols.py`).
- `get_blockers` takes an injectable `today`; token store raises on unknown refs (63 tests).

### M6 — Security test suite (acceptance gate)  ✅ DONE
- `tests/test_security_acceptance.py`: 12 named tests `test_p6_01`–`test_p6_12` mapping the full
  Phase-6 list, asserting invariants (flags, exceptions, audit fields, sentinel absence).

### M7 — Simple web app  ✅ DONE
- `src/assistant/web/` (FastAPI router + Jinja2 templates, plain-form posts; HTMX optional).
  Pages: **/** six flow forms (weekly, email, teams, project detail, Jira write, flagship) ·
  **/connections** self-service connect/disconnect for the 7 systems ·
  **/admin** read-only audit events + pending approvals + seed policies.
- Write actions require an explicit confirmation checkbox; unconfirmed writes never execute.
- Identity is a cookie-based user-switcher stub (mark/anna/lucy) — replaced by real auth later.
- Orchestrator additions: `project_detail` flow; `gaps` field reporting systems that could not
  be consulted (honest partial answers).
- **Milestone:** flagship flow runs in the browser; connections manageable in UI (83 tests).

### Later (post-MVP)
Superseded by the dedicated release plan: see **[`ROADMAP.md`](ROADMAP.md)**
(v0.2 auth+persistence → v0.3 Google connectors → v0.4 approvals+transparency →
v0.5 Microsoft+Teams bot → v0.6 real LLM → v1.0 pilot-ready).

## Domain models (from spec §12/§15)

`Person` (+ teams_id, jira_id, hubspot_id, manager_id, backup_owners) · `Task` · `Project` ·
`EmailThread` · `Attachment` · `TeamsThread` · `TeamsFile` · `AuditEvent`.
Enums: `System`, `ActionType`, `GmailAction`, `TeamsAction`, `AccessTier`.

## Testing (Phase-6 acceptance list)

1. Cannot read another user's Gmail without permission.
2. Can read scoped Gmail content when a valid policy exists.
3. Cannot read Teams messages outside allowed scope.
4. Can read Teams project context when permitted.
5. A write executes only as active_user.
6. A write is never executed as target_user.
7. Audit events created for sensitive reads.
8. Audit events created for writes.
9. Permission denial returns a safe response.
10. Ambiguous permission triggers approval flow or clear refusal.
11. Orchestrator never calls connectors without permission validation.
12. Summaries don't expose raw sensitive content unnecessarily.

Plus: `scope.py` matrix tests, connection-resolution tests, connector-guard test.

## Milestones summary

| Milestone | Definition of done                                              |
|-----------|-----------------------------------------------------------------|
| M0        | Project runs; lint/type/test harness green                      |
| M1        | Identity + connection resolution working                        |
| M2        | Permission engine + audit tested in isolation                   |
| M3        | 7 mock connectors, all gated                                    |
| M4        | Cross-tool entity linking                                       |
| M5        | All core flows end-to-end on mocks                              |
| M6        | Full security suite green (acceptance gate)                     |
| M7        | Flagship flow runnable in the browser; connections managed in UI |

## Known open questions

- **Continuity access definition** — assumed: an active policy row whose `conditions` include
  `only_when_out_of_office` **and** requester ∈ `backup_owners`; no implicit access without a
  policy. *Needs final confirmation.*
- **Scope semantics** — assumed conjunctive + default-deny. *Confirmed in principle; revisit if
  real data shows false negatives.*
- **Graph overlay in MVP** — building as a thin linking overlay (raw passthrough). Option to ship
  disabled-by-default remains open.
- **Real auth/OAuth** — per-connector OAuth deferred; token-store interface defined now.
