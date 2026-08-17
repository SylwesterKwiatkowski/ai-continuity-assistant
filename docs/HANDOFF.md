# Developer Handoff — AI Business Continuity Assistant

_Snapshot refreshed 2026-08-17, HEAD `616fb1e` on `post-mvp` (== `origin/post-mvp` == `origin/main`)._

> **Where to start:** this file describes what *exists*. For what to build next, in what order,
> and what will bite you, read [`DELIVERY_PLAN.md`](DELIVERY_PLAN.md) — then
> [`ROADMAP.md`](ROADMAP.md). AI agents: [`../CLAUDE.md`](../CLAUDE.md).

## 30-second pitch

A governed work-context assistant: a colleague can ask about another person's tasks/emails/chats
*only* under a scoped, expiring, audited permission — never as a blanket "ask anything about
anyone" tool. The one rule that governs everything:

> Read with delegated, scoped permission. Write only as the active user. Never impersonate the
> target user.

Full pitch: [`README.md`](../README.md). Full contract: [`docs/SECURITY_MODEL.md`](SECURITY_MODEL.md).

## Current state (verified today, not just from docs)

| Check | Result |
|---|---|
| `pytest -q` | **136 passed**, 0 failed |
| `ruff check src tests` | **All checks passed** |
| `mypy src` (strict) | **Success, no issues** |
| CI (`.github/workflows/ci.yml`) | Green on every push since setup (2026-07-03) |
| Working tree | Clean, `post-mvp` == `origin/post-mvp` at `616fb1e` |
| Deployed instance | Running on a remote host with real Google OAuth credentials in its gitignored `.env` |

## What's built (MVP + v0.2 + part of v0.4)

- **M0–M7** (full MVP): config/skeleton, identity resolution, connection registry with the
  read-from-target/write-as-active credential rule, Permission Engine + audit core, Connector SDK
  + all 7 **mock** connectors (Gmail, Calendar, Teams, Jira, HubSpot, Sheets, Drive), semantic
  entity graph overlay, orchestrator with 5+ flows, the 12-test security acceptance suite
  (`tests/test_security_acceptance.py`, `test_p6_01`–`test_p6_12`), and a simple FastAPI+Jinja2+HTMX
  web app (`/`, `/connections`, `/admin`).
- **v0.2 trust infrastructure** (commit `a3d3102` + hardening `56419ed`): HMAC-signed sessions,
  admin role gate, full SQLite persistence (`src/assistant/storage/`), Fernet-encrypted token
  store, config that **fails closed in prod** (rejects `AUTH_MODE=dev` / default secrets outside
  local dev).
- **v0.2 Google OAuth login** (`24335fd`, D19): `identity/oauth.py` implements the Authorization
  Code flow by hand over `httpx`; `/auth/google/login` + `/auth/google/callback` issue a session
  **only** for an email matching a seeded `Person` — an unregistered Google account is refused,
  never auto-provisioned. Live and verified on the deployed host. Dormant in any environment
  where `GOOGLE_CLIENT_ID`/`_SECRET` are unset, which is the expected state of a fresh clone.
- **v0.4 grant/deny core** (`616fb1e`, D20): an admin can grant or deny a pending
  `ApprovalRequest` from `/admin`; a grant materializes a scoped policy expiring after
  `GRANT_DURATION_DAYS`. Required re-keying the policy store to allow several policies per
  person — read D20 before touching policy persistence.

## What's NOT built yet — pick up here

**Full ordering, dependencies and risks: [`DELIVERY_PLAN.md`](DELIVERY_PLAN.md).** Summary:

1. **v0.2.1 — administrable identities.** People are the last domain object not in SQLite:
   `seeds/people.json` is read once at boot into an in-memory `IdentityResolver`. Onboarding a
   colleague means editing JSON and restarting the host. Needs a `people` table, admin CRUD at
   `/admin/people`, deactivate-never-delete semantics, and audited role changes — after which the
   dev user picker can finally be retired. **This is the next work.**
2. **v0.3 — real connectors.** `src/assistant/connectors/real/` is currently **empty** (just an
   `__init__.py`). Build Calendar first (real OOO detection is load-bearing for the whole
   continuity story), then Gmail (metadata search → thread read → attachments), then Sheets/Drive.
   Everything must go behind the existing `Port` protocols in
   `src/assistant/connectors/protocols.py` so the orchestrator never changes — mock and real must
   stay swappable. Add an `@pytest.mark.integration` tier (excluded by default, sandbox creds from
   env only) rather than mixing real-API tests into the fast suite.
3. **v0.4 — finish closing the approval loop.** Grant/deny exists (D20), but: there is **no
   notification channel of any kind** in the codebase, so an approver never learns a request is
   waiting; the *named* approver still can't decide (grant/deny is admin-gated even though the
   engine nominates the mailbox owner); there is no revoke UI; and grant duration is a hard-coded
   constant. All buildable on mocks — no Google Cloud dependency — so it parallelizes with
   connector work.
4. **v0.4.1 — self-service delegation.** Nothing lets a person grant or revoke access to their own
   data proactively; every delegation today starts from someone being blocked. New scope, added
   2026-08-17.
5. **"Shared" access tier is designed, not implemented.** The engine currently only resolves
   self/delegated; project-membership modeling for the shared tier is still open (v1.0 scope).
6. Smaller/deferred: transparency-to-target hook is a no-op stub (deliberate for now, not a bug);
   branch protection on `main` isn't server-enforced (GitHub Pro required for private repos —
   currently convention-only, see [`docs/TESTING.md`](TESTING.md)).
7. **Operational debt:** the deployed host is not represented in the repo — no Dockerfile, systemd
   unit or runbook, and no record of the live redirect URI or restart procedure. There is also no
   schema-migration path, and that host now holds audit history worth keeping. See
   `ROADMAP.md` → Operational debt, and Risk R1/R4 in `DELIVERY_PLAN.md`.

Ordering rationale (from `docs/ROADMAP.md`): auth before real data, administrable identities before
real connectors, Calendar before Gmail, notification before self-service, approvals before the
Teams bot, LLM swap last since it's a single-protocol change.

## Architecture (one diagram, see `docs/ARCHITECTURE.md` for the walkthrough)

```
Interface (HTTP API + Jinja2/HTMX web app; Teams bot later)
  -> Orchestrator (identity resolution, tier decision, always checks Permission Engine first)
    -> Permission Engine (default-deny; READ-on-target and WRITE-as-active checked independently)
      -> Connection Registry (resolves whose credential: target's for private-store reads,
                               active_user's own for shared-system reads, always active_user's
                               for writes)
        -> Connector SDK (7 systems, BaseConnector._guard enforces the above, mock-first)
          -> Semantic Layer (EntityGraph — thin overlay, raw payload always preserved)
            -> Summarizer (LLM protocol; MVP = deterministic StubSummarizer, real LLM later)
              -> Audit Log (every sensitive read + every write, append-only, queryable)
```

The LLM never touches raw data or credentials directly — everything is mediated by the backend.

### Source map (`src/assistant/`)

| Module | Purpose |
|---|---|
| `api/app.py` | FastAPI app factory (thin — wiring lives in `bootstrap.py`) |
| `bootstrap.py` | `build_app_services()` — single entry point wiring all layers |
| `web/` | Server-rendered UI (routes.py + templates/), signed-session auth |
| `orchestrator/` | Coordinates every flow; never calls a connector without an approved decision |
| `permissions/` | `PermissionEngine`, policy models, conjunctive scope matching, approvals |
| `identity/` | Person resolution (from `seeds/people.json`), connections, HMAC sessions |
| `connectors/base.py` + `protocols.py` | SDK + Ports the orchestrator depends on |
| `connectors/mock/` | All 7 mock connectors + deterministic fixtures (incl. leak-test sentinels) |
| `connectors/real/` | **Empty — this is the v0.3 build target** |
| `graph/` | `EntityGraph` — thin linking overlay, D4 |
| `summarizer/` | `Summarizer` protocol + deterministic stub (D9) |
| `audit/` | `AuditLog` write-through + `AuditEvent` model |
| `domain/` | Normalized models + shared enums (`System`, `ActionType`, `AccessTier`, etc.) |
| `storage/` | SQLite repos, `EncryptedTokenStore` (Fernet), one-time seeding |
| `config.py` | pydantic-settings; fails closed in prod |

No `TODO`/`FIXME` markers anywhere in `src/` — every unfinished piece is a documented, deliberate
MVP stub (e.g. `GmailAction.FULL_MAILBOX_ACCESS` is explicitly "not implemented", stub tokens are
labeled `stub-secret::...`).

## Non-negotiable rules (enforced by tests + review, see `CONTRIBUTING.md`)

1. No connector call without a Permission Engine decision (`BaseConnector._guard` self-enforces).
2. Writes execute only as `active_user`, with `active_user`'s own connection.
3. Delegated reads of Gmail/Teams require a matching policy — default-deny.
4. Every sensitive read/write emits an `AuditEvent`, denials included.
5. Sentinel strings (`SENTINEL_FULL_BODY_DO_NOT_LEAK`, `555-0100`) must never leak into a summary.
6. No secrets in code — env vars / token store only.
7. Tests inject clocks; never call `date.today()`/`datetime.now()` inside logic under test.
8. `mypy --strict` clean on `src/`; `from __future__ import annotations` everywhere.
9. Real integrations only behind existing `Port` protocols — mock/real swappable without touching
   the orchestrator.

## Getting started

```bash
cd ~/ai-continuity-assistant
source .venv/bin/activate        # venv already provisioned, Python 3.12
pip install -e ".[dev]"          # if deps drift
cp .env.example .env             # if not already present
ruff check src tests && mypy src && pytest -q   # should show: all green, 136 passed
uvicorn assistant.api.app:app --reload           # -> http://127.0.0.1:8000, sign in as mark/anna/lucy
```

Locally you sign in with the dev picker (`AUTH_MODE=dev`, the default). You do **not** need Google
credentials to develop — the OAuth provider stays dormant while `GOOGLE_CLIENT_ID`/`_SECRET` are
unset, which is the correct state of a fresh clone. Real credentials exist only in the deployed
host's gitignored `.env`.

Read order for a new dev: `CONTRIBUTING.md` → `docs/SECURITY_MODEL.md` → README demo-scenario
section → this file → `docs/DELIVERY_PLAN.md` before writing code. Day-1 checklist with exact
steps: `docs/ONBOARDING_CHECKLIST.md`. AI agents: `CLAUDE.md` at the repo root.

## Open decisions still needing a sign-off (not blocking, but unresolved — `docs/DECISIONS.md`)

- Exact definition of a valid "continuity policy" (OOO window + backup_owner membership) — used in
  principle, not formally ratified.
- Whether the entity-graph overlay ships enabled or disabled by default.
- Storage engine: SQLite is working and tested, but Postgres-for-prod hasn't been ratified.
- Web stack (FastAPI+Jinja2+HTMX) is a working default, explicitly open to revisit.

## Reference docs

`docs/ARCHITECTURE.md` · `docs/SECURITY_MODEL.md` · `docs/DECISIONS.md` (D1–D20) ·
`docs/ROADMAP.md` · **`docs/DELIVERY_PLAN.md`** (branch order + risk register) ·
`docs/IMPLEMENTATION_PLAN.md` (M0–M7) · `docs/TESTING.md` · `docs/GOOGLE_OAUTH_SETUP.md` ·
`docs/ONBOARDING_CHECKLIST.md` · `CONTRIBUTING.md` · `CLAUDE.md` (AI agent entry point)
