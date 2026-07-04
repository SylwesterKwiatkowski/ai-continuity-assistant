# AI Business Continuity Assistant

An internal, governed **work-context assistant** that helps a team recover operational
context — tasks, project details, emails, chats, attachments, documentation — from the
company's work tools, with delegated, scoped permissions and a complete audit trail.

It is **not** "anyone can ask anything about anyone." It is a business-continuity and
organizational-memory assistant built on permissions, delegations, approvals, and auditing.

## The one rule that governs everything

```
Read with delegated, scoped permission.
Write only as the active user.
Never impersonate the target user.
```

See [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) for how this is enforced at the
credential layer, not just by convention.

## Core concept: two identities

- **`active_user`** — the person talking to the assistant. The *only* valid actor for any write.
- **`target_user`** — the person being asked about. Their data can be *read* only under a
  scoped, conditional, non-expired policy, and is *never* an actor for writes.

## Access tiers

The assistant is useful all the time, not only during absences. Value grows across three tiers
while privacy risk stays contained:

| Tier          | Whose data                         | Permission needed                         |
|---------------|------------------------------------|-------------------------------------------|
| **self**      | the active_user's own data         | none (it's theirs)                        |
| **shared**    | team/project/client data           | project membership                        |
| **delegated** | another person's private data      | scoped policy + conditions + audit        |

Business continuity (e.g. "Anna is on vacation, find the ClientCo email") is **one mode of the
delegated tier**, not the whole product.

## Connected systems (per-user, self-service)

Each user connects and chooses which apps are linked to *their own* account (OAuth; tokens are
user-owned). Delegated reads use the **target's** connection (policy-gated); writes always use
the **active_user's** connection.

Gmail · Google Calendar · Microsoft Teams · Jira · HubSpot · Google Sheets · Google Drive

All seven ship first as **mock connectors**; real integrations replace them one-by-one only
after the permission tests pass.

## Architecture (high level)

```
Interface (MVP: HTTP API + simple web app; Teams bot later)
  → Orchestrator (intent, identity resolution, flow planning)
    → Permission Engine (default-deny; validates read-on-target and write-as-active separately)
      → Connection Registry (resolves which user's credential to use)
        → Connector SDK (7 systems; mock first, behind a uniform interface)
          → Semantic Layer (thin normalization + linking overlay; raw data passes through)
            → Summarizer (LLM: reason + summarize + cite only; stubbed in MVP)
              → Audit Log (every sensitive read + every write; transparency-to-target hook)
```

The LLM never accesses raw data or credentials directly. Every tool call passes through the
backend and the Permission Engine.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Local setup

> Requires Python 3.12+.

```bash
git clone <repo> ai-continuity-assistant
cd ai-continuity-assistant
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # once pyproject.toml lands (M0)
cp .env.example .env             # fill in local values
```

## Environment variables

Secrets are never hardcoded; everything comes from the environment or the token store.
See `.env.example` for the authoritative list. Expected keys (MVP):

| Variable                | Purpose                                             |
|-------------------------|-----------------------------------------------------|
| `APP_ENV`               | `local` / `dev` / `prod`                            |
| `DATABASE_URL`          | SQLite URL (`sqlite:///./assistant.sqlite`)         |
| `TOKEN_STORE_KEY`       | key for the encrypted (Fernet) per-user token store |
| `AUTH_MODE`             | `dev` (demo user picker) / `oauth` (provider TBD)   |
| `SESSION_SECRET`        | HMAC key for signed session tokens — secret in prod |
| `SESSION_TTL_HOURS`     | session lifetime (default 8)                        |
| `LLM_API_KEY`           | summarizer key (unused while stub is active)        |
| `LLM_MODEL`             | model id (e.g. `claude-opus-4-8`) when wired        |

## Development commands

```bash
pytest                                   # full suite (acceptance gate included)
pytest tests/test_security_acceptance.py # the 12 named Phase-6 security tests
ruff check src tests                     # lint
mypy src                                 # type-check (strict)
uvicorn assistant.api.app:app --reload   # run the web app → http://127.0.0.1:8000
```

The web app runs on mock connectors with seeded data. Sign in at `/login` (dev mode: pick
mark / anna / lucy) to try the permission model. State persists in SQLite across restarts.

## Demo scenario (how "Mark" works without any real accounts)

Nobody connects real apps in dev mode — the demo universe is **seeded**, and the mock
connectors return fixtures. The security machinery is real end-to-end (sessions, permission
engine, policy matching, credential resolution, audit); only the final data fetch is canned.

**The cast** (`seeds/`):

| Persona | Role in the demo |
|---|---|
| **anna** | Out of office 2026-07-01→10; owns the ClientCo mailbox data; connected: Gmail, Teams, Calendar |
| **mark** | Anna's backup owner for **ClientCo / API Integration**; connected to all 7 systems |
| **lucy** | Admin (can view `/admin`); has **no** delegated access — her searches get blocked |

**The data** (`src/assistant/connectors/mock/data.py`): Anna's mailbox holds the
"API preparation details" thread from `dev@clientco.com` with two attachments; a Teams
thread in *ClientCo Delivery*; Jira issues CRM-241 (overdue) and API-12; a recurring
Sheets task; and her Calendar OOO window.

**The delegation** (`seeds/policies.json`): Mark may read Anna's Gmail/Teams, scoped to
ClientCo / API Integration, **only while she is out of office**, expiring 2026-07-20.

**Things to try:** sign in as each persona; disconnect Anna's Gmail on `/connections`
(Mark's search then honestly refuses); edit `policies.json` to remove Mark or expire the
policy and watch the engine deny; move Anna's OOO window into the past in
`connectors/mock/calendar.py`.

> ⚠️ Connections and policies are copied into SQLite **on first boot only** — after editing
> those seed files, delete the database (`rm assistant.sqlite`) so it re-seeds.
> `people.json` is read fresh on every start.

Real data arrives in v0.3 when mock connectors are swapped for real ones and
`/connections` becomes a genuine OAuth consent flow.

`/connections` manages your own app connections; `/admin` (admin role — Lucy) shows the
audit trail, pending approvals, and policies.

## Status

**MVP complete** (`v0.1.0-mvp`): security core, 7 mock connectors, orchestrator flows, simple
web app. v0.2 trust infrastructure (session auth, persistence, encrypted tokens) has landed
on `post-mvp`/`main`. Current test count: run `pytest -q` or see the CI badge/runs.

## For developers

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) — onboarding, branch model, the
non-negotiable security rules, and the release checklist. Then:

| Doc | What it answers |
|---|---|
| [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) | The contract all code must obey |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, data flow, boundaries |
| [`docs/TESTING.md`](docs/TESTING.md) | Automated gates + manual smoke procedure |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Release plan v0.2 → v1.0 with rationale |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | What the MVP contains (M0–M7) |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Why things are the way they are (D1–D16) |
