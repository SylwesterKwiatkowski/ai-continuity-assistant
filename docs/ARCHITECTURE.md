# Architecture

## Goals

- Recover cross-tool work context safely, with permissions and audit.
- Keep the **Permission Engine as a mandatory chokepoint** — no connector call happens
  without an authorizing decision.
- Keep the **LLM as a reasoner/summarizer only** — it never touches raw data or credentials.
- Make breadth cheap: new connectors are additive behind a uniform SDK.

## System components

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Interface        MVP: HTTP API + simple web app (Jinja2+HTMX)              │
│                  Later: Teams bot (@Secretary)                             │
│                  (authenticates the active_user)                           │
└───────────────┬──────────────────────────────────────────────────────────┘
                │  active_user identity + natural-language request
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Orchestrator                                                               │
│  - parse intent (action, needs_attachment, ...)                            │
│  - resolve identities: active_user, target_user, client, project, dates    │
│  - decide access tier (self / shared / delegated)                          │
│  - plan connector calls; sequence read → summarize → (confirm) → write     │
│  - ALWAYS call the Permission Engine before any data access or write       │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Permission & Policy Engine        (default-deny)                           │
│  - validates READ on target's data and WRITE as active_user SEPARATELY     │
│  - matches scope conjunctively (client AND project AND dates AND ...)      │
│  - checks conditions (e.g. only_when_out_of_office) and expiry             │
│  - returns {allowed, allowed_actions, scope, reason, required_approval}    │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Connection Registry                                                        │
│  - per-user, self-service connections (OAuth; user-owned tokens)           │
│  - resolves the correct credential per call:                               │
│      reads  → the TARGET's connection (policy-gated)                       │
│      writes → the ACTIVE_USER's connection (always)                        │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Connector SDK          BaseConnector + CapabilityManifest                  │
│  Gmail · Calendar · Teams · Jira · HubSpot · Sheets · Drive                │
│  - each method declares: system, action, access(read/write),              │
│    sensitivity, requires_scope                                             │
│  - receives a resolved PermissionContext + a user connection               │
│  - CANNOT be called without an authorizing decision                        │
│  - MVP: mock implementations returning fixtures                            │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Semantic Layer     thin normalization + linking OVERLAY (not a funnel)     │
│  - maps a subset of results into entities: Person/Project/Client/          │
│    Task/Thread/File, and links them across tools                           │
│  - full native payload passes through untouched (raw/extra fields)         │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Summarizer (LLM interface)                                                 │
│  - reason + summarize + cite sources; prefer summary over raw dumps        │
│  - MVP: deterministic stub (keeps security tests deterministic)            │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Audit Log + (later) Admin Dashboard                                        │
│  - records every sensitive read and every write                            │
│  - transparency-to-target hook (notify person when their data is read)     │
└──────────────────────────────────────────────────────────────────────────┘
```

Two cross-cutting services are touched at every sensitive step: **Audit** (write-through) and
the **Connection Registry** (credential resolution).

## Data flow — the flagship request

Request: *"Anna is on vacation. Find the ClientCo email + Teams messages about preparing the
API and the attached docs, then create a Jira task to review the requirements."*

1. **Intent + identity.** Orchestrator parses: action = read(gmail, teams) + write(jira);
   active_user = Mark, target_user = Anna, client = ClientCo, project = API Integration.
2. **Tier.** target_user ≠ active_user → **delegated**.
3. **Absence check.** Calendar connector `detect_out_of_office(Anna)` → confirms OOO.
4. **Read permission.** Engine finds `MailboxAccessPolicy` + `TeamsAccessPolicy` where
   Mark ∈ allowed_requesters, scope = ClientCo/API Integration, condition OOO holds, not expired.
   Returns allowed actions + effective scope.
5. **Scoped reads.** Connection Registry supplies **Anna's** Gmail/Teams connections;
   connectors search *within the effective scope only*, return metadata → rank → read top threads.
6. **Normalize + summarize.** Semantic layer links results to ClientCo/API Integration; summarizer
   produces a cited summary (requirements, decisions, attachments) — not raw dumps.
7. **Write permission.** Engine validates actor = Mark and Mark has Jira write capability.
8. **Write as active_user.** Jira connector `create_jira_issue_as_active_user` uses **Mark's**
   connection. Anna's credential is never used for a write.
9. **Audit.** Three events recorded: Gmail read (Mark/Anna), Teams read (Mark/Anna), Jira write
   (actor_for_write_action = Mark). Transparency hook can notify Anna.
10. **Respond.** Summary + sources + action taken + access reason + "no action taken as Anna."

## Integration boundaries

- Connectors are the **only** components that talk to external systems.
- The orchestrator talks to connectors **only after** the Permission Engine authorizes the exact
  `(system, action, scope)`.
- The LLM/summarizer receives *already-retrieved, already-authorized* data — it never initiates a
  fetch and never sees credentials.
- Storage is behind repository interfaces (policies, connections, audit, people) — SQLite in MVP,
  swappable later.

## Permission flow (summary)

Default-deny. The engine answers, per operation: *Can this active_user act on this target's data,
for this action, within this scope, under these conditions, before expiry?* and separately
*Can this active_user write to this system as themselves?* Ambiguous or missing permission → block
and offer an `ApprovalRequest`. Detail in [`SECURITY_MODEL.md`](SECURITY_MODEL.md).

## Audit flow (summary)

Write-through logging around every sensitive read (before returning results) and every write
(after execution), distinguishing requester/active_user vs target_user and read vs write, and
recording `actor_for_write_action`. Append-only, queryable by user/system/project/client/date for
the future admin dashboard. Detail in [`SECURITY_MODEL.md`](SECURITY_MODEL.md).
