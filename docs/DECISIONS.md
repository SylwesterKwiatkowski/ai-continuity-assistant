# Architectural Decisions

Chronological record of decisions, tradeoffs, and unresolved questions. Newest additions appended.

## Format
Each entry: **decision** · **why** · **tradeoffs / alternatives** · **status**.

---

### D1 — Language & framework: Python 3.12 + FastAPI
- **Why:** typed schemas via Pydantic, easy dependency injection for swapping mock↔real connectors,
  strong SDK coverage for Google/Jira/HubSpot/MS Graph. Best fit for a permission-heavy backend.
- **Tradeoffs:** if a Teams bot / web dashboard front-end becomes dominant, a TS/Node stack would
  unify languages. Accepted — backend correctness matters more early.
- **Runtime note:** M0 briefly ran on the machine's stock Python 3.9. Python 3.12.13 has since been
  installed via Homebrew (`brew install python@3.12`); `requires-python` and the ruff/mypy targets
  are back to 3.12, the venv is rebuilt on 3.12, and enums use `enum.StrEnum`.
- **Status:** Confirmed by user (running on Python 3.12.13).

### D2 — Positioning: 3-tier assistant (self / shared / delegated)
- **Why:** most always-on value is single-player (querying one's own data), which needs no
  delegation and carries little privacy risk. Continuity becomes one delegated mode rather than the
  whole product, containing the surveillance risk the spec itself flags.
- **Tradeoffs:** slightly more design up front than a continuity-only build.
- **Status:** Confirmed by user.

### D3 — Bake in Connector SDK now
- **Why:** a uniform `BaseConnector` + capability manifest lets every system (and future plugins)
  pass through one Permission Engine. Cheap now, expensive to retrofit.
- **Tradeoffs:** a little abstraction before the first real connector exists.
- **Status:** Confirmed by user.

### D4 — Bake in semantic/entity graph now, as a thin linking overlay
- **Why:** enables cross-tool linking ("everything about ClientCo") and precise scope matching,
  which per-tool federated search cannot do.
- **Anti-limiting guard:** the graph is an **overlay, not a funnel** — connectors return rich native
  payloads (`raw`/`extra` preserved), the layer normalizes only a subset for linking/scoping, the
  summarizer still sees native content, and schemas are extensible. This addresses the concern that
  a canonical model could constrain the app.
- **Tradeoffs:** more moving parts than no graph. Option remains to ship it disabled-by-default in
  MVP and enable once flows work.
- **Status:** Confirmed by user (overlay refinement recorded).

### D5 — In-scope systems: seven connectors
- Gmail, Google Calendar, Microsoft Teams, Jira, HubSpot, Google Sheets, **Google Drive**.
- **Why:** the spec's six plus Drive (where docs/files live). 
- **Status:** Confirmed by user.

### D6 — Per-user, self-service connections (user-owned credentials)
- **Why:** each active_user authorizes and chooses which apps connect to their own account. This
  makes "never impersonate" enforceable at the **credential layer**: reads use the target's
  connection (policy-gated), writes always use the active_user's own connection.
- **Tradeoffs:** delegated reads require the target to have connected that app; if not connected,
  the read is impossible (honest refusal) rather than falling back to a global service account.
  Accepted — it is the safer default.
- **Status:** Confirmed by user.

### D7 — Storage: SQLite behind repository interfaces (MVP)
- **Why:** simplest thing that works; swappable to Postgres later without touching domain logic.
- **Status:** Reasonable default (documented; not explicitly ratified).

### D8 — Identity mapping from a seed file (MVP)
- **Why:** `seeds/people.json` maps each Person's Google/Teams/Jira/HubSpot IDs + `backup_owners`;
  avoids live directory sync in MVP.
- **Status:** Reasonable default.

### D9 — Deterministic summarizer stub (MVP)
- **Why:** with reads mocked, a deterministic stub keeps security tests deterministic. Real LLM
  (e.g. Claude Opus 4.8) wired later behind the same interface.
- **Status:** Reasonable default.

### D10 — Approval flow depth (MVP)
- **Why:** MVP creates/stores an `ApprovalRequest` and returns "blocked — approval available";
  async approver notification/callback deferred.
- **Status:** Implemented (hardening pass): blocked delegated reads persist a pending
  `ApprovalRequest` (`permissions/approvals.py`) and return its id in the response.

### D11 — Scope matching: conjunctive + default-deny
- **Why:** matches the spec's least-privilege intent; any unmatched scope dimension denies.
- **Tradeoffs:** risk of false negatives on messy real data; revisit against real fixtures.
- **Status:** Confirmed in principle.

### D12 — Explicitly out of scope for MVP
- Legal/GDPR/works-council compliance work (per user direction, not a build concern now).
- `full_mailbox_access`, unbounded Teams reads.
- Real OAuth, Teams bot, proactive/handoff packs.
- **Status:** Confirmed by user (legal explicitly deprioritized).

### D13 — Simple web app in MVP; Teams bot later
- **Why:** the user wants a usable GUI in MVP. A web app also naturally hosts the two screens the
  security model needs anyway — the self-service **Connections** page (D6) and a basic **admin /
  audit** view. Teams bot (the spec's eventual primary interface) is deferred to a later phase.
- **Scope of "simple":** query/chat page (cited summaries + source links), Connections page
  (connect/disconnect the 7 apps), action confirmation (write-as-active_user), and a read-only
  admin audit + policy view. All are thin clients over the existing API.
- **Tradeoffs:** a little UI work in MVP vs. API-only. Accepted — it exercises the full flow and
  gives a real product surface.
- **Status:** Confirmed by user.

### D14 — Web app tech: FastAPI + Jinja2 templates + HTMX
- **Why:** lightest option that stays in the Python stack — no separate Node/React build, server-
  rendered pages, HTMX for interactivity. Fast to build and easy to reason about for a "simple" UI.
- **Tradeoffs:** less rich than a React SPA; if the UI grows (complex dashboard interactions), swap
  to a SPA later behind the same API. Accepted.
- **Status:** Reasonable default (proposed; open to change).

### D15 — Sensitivity tiers for delegated reads
- **Rule:** delegated reads of **Gmail and Teams** require an explicit, in-scope, in-condition,
  non-expired policy (default-deny). Delegated reads of **Calendar, Jira, HubSpot, Sheets, Drive**
  are lower-sensitivity work context — allowed for a colleague and **still audited**, no explicit
  policy required.
- **Why:** matches the spec — MVP1 supports "what is Anna doing this week" (Jira/Calendar/Sheets)
  freely, while the spec gates Gmail/Teams behind `MailboxAccessPolicy`/`TeamsAccessPolicy`.
- **Tradeoffs:** treats task/calendar metadata as non-secret. Revisit if any of these systems carry
  sensitive free-text in practice; a system can be moved into `SENSITIVE_SYSTEMS` with no other
  change.
- **Why the risk is bounded (added after external review, 2026-07-03):** shared-system reads run
  with the **active_user's own credential** (D16). When real connectors land, Mark's Jira/HubSpot/
  Drive queries execute with Mark's token, so he can only ever see what those tools' **native
  permissions** already grant him — the assistant does not widen access, it only aggregates it.
  The exposure is therefore "what the requester could already see," plus our audit trail on top.
  This does not remove the need to revisit per deployment (mocks can't model native ACLs), but it
  is why these systems don't need `MailboxAccessPolicy`-style gating to be safe by default.
- **Status:** Reasonable default (implemented in `permissions/engine.py`); flag for review.

### D16 — Read credential depends on system type
- **Rule:** a delegated READ of a **private store (Gmail, Teams)** uses the **target's** connection;
  a read of a **shared system (Jira, Calendar, HubSpot, Sheets, Drive)** uses the **active_user's
  own** connection, filtered by the target (e.g. Mark queries Jira for issues assigned to Anna).
  Writes always use the active_user's own connection.
- **Why:** matches how these systems actually work — mailboxes/personal chats are per-user private;
  Jira/Calendar/etc. are shared records where assignment is a field, not a private inbox. Also means
  the target need not have "connected" a shared system for their tasks to be visible.
- **Where:** `TARGET_CREDENTIAL_SYSTEMS` in `connectors/base.py`; enforced in the connector guard
  and in `Orchestrator._authorize_read`.
- **Status:** Reasonable default; consistent with D15's sensitivity split.

---

## Unresolved questions
- Exact definition of a valid "continuity policy" (OOO condition + backup_owner membership) — needs
  final confirmation before M2 hardening.
- Whether the graph overlay ships enabled or disabled-by-default in MVP.
- Storage engine ratification (SQLite vs Postgres) once data volume is understood.
- Web app tech (Jinja2+HTMX vs React SPA) — default set in D14, open to change.
