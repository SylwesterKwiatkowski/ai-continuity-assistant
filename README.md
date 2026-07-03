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
| `DATABASE_URL`          | SQLite path (MVP), Postgres URL later               |
| `TOKEN_STORE_KEY`       | encryption key for the per-user token store         |
| `LLM_API_KEY`           | summarizer key (unused while stub is active)        |
| `LLM_MODEL`             | model id (e.g. `claude-opus-4-8`) when wired        |

## Development commands

```bash
pytest                                   # all tests (83; acceptance gate included)
pytest tests/test_security_acceptance.py # the 12 named Phase-6 security tests
ruff check src tests                     # lint
mypy src                                 # type-check (strict)
uvicorn assistant.api.app:app --reload   # run the web app → http://127.0.0.1:8000
```

The web app (MVP) runs on mock connectors with seeded data. Use the user switcher
(mark / anna / lucy) to try the permission model: Mark may search Anna's ClientCo mail while
she is out of office; Lucy is refused and an approval request is created. `/connections`
manages your own app connections; `/admin` shows the audit trail.

## Status

Early scaffolding. See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for the
phased roadmap and current MVP scope, and [`docs/DECISIONS.md`](docs/DECISIONS.md) for
architectural decisions and open questions.
