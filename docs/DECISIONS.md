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
- **Status:** Fulfilled in v0.2 — see D18.

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

### D17 — v0.2 authentication: signed sessions + pluggable provider (OAuth pending)
- **What:** identity now comes from HMAC-SHA256 signed, server-issued session tokens
  (`identity/sessions.py`; constant-time verify, TTL, tamper-proof). Login providers are
  pluggable behind `/login`: MVP ships a **dev provider** (user picker, only when
  `AUTH_MODE=dev`, with a visible warning banner); `AUTH_MODE=oauth` disables it.
- **Why not full Google OAuth yet:** requires real Google Cloud client credentials which do
  not exist yet; the provider slots into the same `/login` flow without re-architecture.
- **Consequence:** the "identity from arbitrary cookie" weakness is gone — a forged or
  expired session is treated as unauthenticated. `/admin` additionally requires the `admin`
  role on `Person.roles`.
- **Status:** Implemented (v0.2); Google OAuth provider is the follow-up.

### D18 — v0.2 storage: stdlib sqlite3 + JSON columns, no ORM
- **What:** `storage/` provides a thread-safe `Database` (stdlib `sqlite3`) with tables for
  audit_events, approvals, policies, connections, tokens; repositories implement the
  existing protocols (`AuditRepository`, `ApprovalRepository`, connection/policy stores);
  records stored as JSON via pydantic. Tokens are encrypted at rest
  (`EncryptedTokenStore`, Fernet, key derived from `TOKEN_STORE_KEY`).
- **Why:** fulfills D7 with the smallest dependency surface (only `cryptography` added);
  swapping to Postgres later means reimplementing the small repository classes, nothing else.
- **Status:** Implemented (v0.2). Audit/approval/connection state survives restarts.

### D19 — v0.2 remainder: Google OAuth login provider
- **What:** `identity/oauth.py` (`GoogleOAuthProvider`) implements the confidential-client
  Authorization Code flow by hand against Google's endpoints, using `httpx` — no
  `google-auth`/`authlib` dependency, matching D18's smallest-dependency-surface stance.
  `GET /auth/google/login` redirects to Google's consent screen with a random `state`
  stored in a short-lived cookie; `GET /auth/google/callback` verifies `state` (CSRF),
  exchanges the code for an access token, calls Google's `userinfo` endpoint, and requires
  `email_verified: true`. Both routes 403 unless `AUTH_MODE=oauth` and
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set (`config.py`); `bootstrap.py` only
  constructs a `GoogleOAuthProvider` when both are present, so an unconfigured deployment
  keeps showing the existing placeholder on `/login`.
- **Why:** this is login only — it grants a *session*, never data access. A verified Google
  account is looked up by email against the seeded `Person` list (`identity/resolver.py`,
  D8) and **refused if no match exists**; the provider never creates a `Person`. This is
  deliberate: the whole permission model (access tiers, delegated policies, audit) is keyed
  to known identities, so letting any Google account in — even a verified one — would let
  anyone outside the org obtain a session by signing in with their own Gmail. Per-user data
  connections (Gmail/Calendar/etc., D6) remain separate and still require the user to
  connect them on `/connections`; login does not imply any connector access.
- **Tradeoffs:** no `id_token` JWT signature verification — instead the email comes from an
  authenticated call to Google's own `userinfo` endpoint using the access token obtained
  server-side during the exchange, which is an equally valid (and simpler) trust path for a
  confidential client. Revisit if refresh tokens / offline access are ever needed for login
  itself (not needed today: `access_type=online`).
- **Status:** Implemented. Finishes the v0.2 "real authentication" item from `ROADMAP.md`;
  real Google *connectors* (Calendar/Gmail/Sheets/Drive, v0.3) are unrelated follow-up work.

### D20 — v0.4 (partial): approval grant/deny, backed by multiple policies per person
- **What:** `MailboxAccessPolicy`/`TeamsAccessPolicy` gained an `id` field (previously
  identity was implicit in `mailbox_owner`/`target_user`). `SqlitePolicyStore` now keys
  rows by `(kind, id)` instead of `(kind, owner)` — **several policies can now exist for
  the same person at once** (e.g. the standing continuity policy plus one or more one-off
  grants). `PermissionEngine` was changed to match: `_find_mailbox_policies`/
  `_find_teams_policies` return *all* policies for an owner, and `_evaluate_mailbox`/
  `_evaluate_teams` allow if *any one* of them authorizes the request. New
  `engine.add_mailbox_policy()`/`add_teams_policy()` make a grant effective immediately, in
  the running process, with no restart.
  `Orchestrator.grant_approval()`/`deny_approval()` are the new admin actions (wired to
  `POST /admin/approvals/{id}/grant`/`/deny`, admin-role-gated like the rest of `/admin`).
  Granting materializes a policy scoped to exactly what was requested (client/project/
  domain, or channels/keywords/participants for Teams), naming only the original
  `requester` as `allowed_requesters`, expiring after `GRANT_DURATION_DAYS` (14, a module
  constant). Both grant and deny emit an audit event via the existing `record_write` (the
  decision itself is an admin action, not a data read) and update the `ApprovalRequest`'s
  `status`/`approver`/`decided_at` in place.
- **Why the schema change was necessary, not optional:** the original `(kind, owner)` key
  meant persisting a second policy for the same owner would silently overwrite the first
  via `INSERT OR REPLACE` — a grant to a new requester would have **deleted the existing
  continuity policy** without anyone noticing. Caught before shipping (not from an
  incident); D8/D6's "known identities, least privilege" spirit is what the multi-policy
  model preserves — see CONTRIBUTING.md's non-negotiable #3.
- **Tradeoffs / what's still open (rest of v0.4.0 in ROADMAP.md):** no approver
  notification yet (an admin must know to check `/admin`); no transparency-to-target hook
  fired for the grant itself (the *subsequent read* still fires it, per D-existing
  behavior); no "revoke a granted policy" UI yet, though
  `SqlitePolicyStore.delete_mailbox`/`delete_teams` exist for it to be added without
  another schema change. `GRANT_DURATION_DAYS` is a fixed constant, not requester-chosen.
- **Status:** Implemented (grant/deny core loop only). ruff, mypy --strict, and the full
  pytest suite (136 tests) are green.

### D21 — v0.4.0: the nominated approver can decide, not only an admin
- **What:** `PermissionEngine._suggest_approver` already nominates who *should* decide a
  blocked delegated read (the mailbox owner for Gmail, the target's manager for Teams) and
  records it as `ApprovalRequest.approver` — but `POST /admin/approvals/{id}/grant`/`/deny`
  were `_require_admin`-gated, so the code contradicted what `SECURITY_MODEL.md` already
  claimed. Fixed: `web/routes.py` gains `_require_approver_or_admin`, which allows either
  the nominated approver (`approval.approver == current_user`) or an admin. A new page,
  `GET /approvals/mine` (not admin-gated), lists pending requests naming the current user
  as approver, with the same Grant/Deny forms `/admin` uses.
- **`approver` vs `decided_by`:** previously granting/denying overwrote `approval.approver`
  with whoever decided, destroying the record of who was *nominated*. `ApprovalRequest`
  now has both: `approver` is set once, at creation, and never touched again; `decided_by`
  records who actually acted. They differ exactly when an admin overrides — which
  `Orchestrator._override_note` then appends to the audit event's `reason`
  (`[ADMIN OVERRIDE — nominated approver was X]`), making it "audited as an override,
  distinguishable in the log" per `docs/DELIVERY_PLAN.md` branch 5.
- **Why:** the whole point of naming an approver was so the actual data owner decides
  access to their own data — routing every decision through an admin regardless made that
  nomination cosmetic. This is the smallest change with the highest value in the v0.4.0
  backlog (DELIVERY_PLAN.md), because the primitive (`approver`) already existed; only the
  gate was wrong.
- **Tradeoffs:** `/approvals/mine` filters client-side over `orch.approvals.pending()`
  (no new repository query) — fine at current scale, revisit if approval volume grows.
  Redirect target after a decision is a form field validated against an allow-list
  (`{"/admin", "/approvals/mine"}`), not the `Referer` header, to avoid any open-redirect
  surface.
- **Status:** Implemented (`feature/approver-decides`, DELIVERY_PLAN.md branch 5 of 8).
  ruff, mypy --strict, and the full pytest suite (141 tests) are green.
