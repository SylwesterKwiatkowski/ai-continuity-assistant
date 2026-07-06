# Contributing / Developer Onboarding

Welcome. This document is the entry point for anyone developing this project. Read it fully
before writing code — this codebase has **security invariants that are not optional**.

> **Brand new here?** Start with the one-page
> [`docs/ONBOARDING_CHECKLIST.md`](docs/ONBOARDING_CHECKLIST.md) — day-1 setup, smoke test,
> Google Cloud track, and your first coding tasks.

## What this project is (60 seconds)

An internal, permission-gated assistant that recovers work context (tasks, emails, chats,
files) across Gmail, Google Calendar, Microsoft Teams, Jira, HubSpot, Google Sheets and
Google Drive — with delegated, scoped read permissions, writes only as the acting user, and a
full audit trail. The one rule that governs everything:

```
Read with delegated, scoped permission.
Write only as the active user.
Never impersonate the target user.
```

Start by reading, in this order:
1. [`README.md`](README.md) — what it does, how to run it
2. [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) — **the contract your code must obey**
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components and data flow
4. [`docs/DECISIONS.md`](docs/DECISIONS.md) — why things are the way they are (D1–D16)
5. [`docs/ROADMAP.md`](docs/ROADMAP.md) — what to build next
6. [`docs/TESTING.md`](docs/TESTING.md) — how to verify your work

## Setup

```bash
git clone https://github.com/SylwesterKwiatkowski/ai-continuity-assistant.git
cd ai-continuity-assistant
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest -q          # expect: all green
uvicorn assistant.api.app:app --reload   # web app on http://127.0.0.1:8000
```

The MVP runs entirely on **mock connectors** with seeded data (`seeds/`). No external
credentials are needed. The seeded scenario: Anna is out of office 2026-07-01..07-10; Mark is
her backup owner for ClientCo / API Integration; Lucy has no delegated access.

## Branch model

| Branch     | Purpose                              | Rules                                            |
|------------|--------------------------------------|--------------------------------------------------|
| `main`     | Stable releases                      | Only merges from `post-mvp`; every merge is tagged (`v0.x.0`). Never commit directly. |
| `mvp`      | Frozen snapshot of the shipped MVP (`v0.1.0-mvp`) | Do not develop here. Critical fixes only, cherry-picked, tagged `v0.1.x-mvp`. |
| `post-mvp` | Active development                   | All feature work. Branch feature branches off this if the work is large. |

Flow: `feature/x` → `post-mvp` → (release checklist) → `main` + tag.

## Daily workflow

1. Work on `post-mvp` (or a feature branch off it).
2. Keep changes small and reviewable; one concern per commit.
3. Before every commit, all three must pass:
   ```bash
   ruff check src tests && mypy src && pytest -q
   ```
4. Update the docs *in the same commit* when behavior changes:
   - new/changed architectural choice → append a `D<n>` entry to `docs/DECISIONS.md`
   - milestone progress → `docs/IMPLEMENTATION_PLAN.md`
   - security behavior → `docs/SECURITY_MODEL.md` (and expect this to be reviewed hard)

## Non-negotiable engineering rules

These are enforced by tests (`tests/test_security_acceptance.py`) and code review. Breaking
them is a rejected PR, no matter how useful the feature:

1. **No connector call without a Permission Engine decision.** Every connector method takes a
   `PermissionContext` and guards itself (`BaseConnector._guard`). Never add a bypass.
2. **Writes execute only as the `active_user`**, with the active_user's own connection.
   A write with anyone else's credential must raise.
3. **Delegated reads of Gmail/Teams require a matching policy** (scope conjunctive,
   conditions met, not expired). Default-deny: if in doubt, deny and offer approval.
4. **Every sensitive read and every write emits an `AuditEvent`.** Denied attempts too.
5. **Summaries over raw dumps.** Never render full email/message bodies in responses.
   The test suite plants sentinel strings to catch leaks — keep it that way.
6. **No secrets in code.** Environment variables / token store only.
7. **Determinism in tests.** Inject clocks (`clock=lambda: date(...)`); never call
   `date.today()`/`datetime.now()` inside logic under test.
8. **Typed everything.** `mypy --strict` on `src/` stays green. `from __future__ import
   annotations` in every module.
9. **Real API integrations only behind the existing Ports** (`connectors/protocols.py`),
   dependency-injected so mocks keep working. Mock and real connectors must be swappable
   without touching the orchestrator.

## Release checklist (`post-mvp` → `main`)

1. CI green on `post-mvp` (ruff + mypy + full pytest).
2. `pytest tests/test_security_acceptance.py -q` — the 12 named security tests are the
   release blocker.
3. Manual smoke procedure from [`docs/TESTING.md`](docs/TESTING.md) executed and clean.
4. `docs/` updated (DECISIONS, IMPLEMENTATION_PLAN, ROADMAP status).
5. Merge to `main`, tag `v0.x.0`, push branch + tag.

## Repository map

```
src/assistant/
├── api/            FastAPI app factory (+ /health)
├── web/            server-rendered web UI (routes + Jinja2 templates)
├── orchestrator/   flow coordination — the ONLY caller of connectors
├── permissions/    Permission Engine, policies, scope matching, approvals
├── identity/       person resolution, per-user connections, credential rule
├── connectors/     base SDK (guards), Ports, mock/ implementations, real/ (empty yet)
├── graph/          semantic linking overlay (non-authoritative)
├── summarizer/     Summarizer protocol + deterministic stub (real LLM later)
├── audit/          AuditEvent + write-through log + transparency hook
├── domain/         normalized models + enums
└── config.py       pydantic-settings (env-driven)
seeds/              people, connections, policies + mock fixtures scenario
tests/              unit + flow tests; test_security_acceptance.py is the gate
docs/               the five living documents + ROADMAP + TESTING
```

## Current known limitations (honest list)

- Authentication is **signed-session based with a dev login provider** (user picker behind
  `AUTH_MODE=dev`). The Google OAuth provider is not wired yet — do not expose this app
  beyond localhost/demo until it is (see ROADMAP v0.2.0 remainder, DECISIONS D17).
- All connectors are mocks; `connectors/real/` is empty.
- Approval requests are persisted but approvers are not notified yet.
- The "shared" access tier is designed (SECURITY_MODEL) but the engine currently resolves
  only self/delegated; project-membership modeling is pending.

CI runs on GitHub Actions for all three branches, and `main` requires the `checks` job to
pass — see [`docs/TESTING.md`](docs/TESTING.md).
