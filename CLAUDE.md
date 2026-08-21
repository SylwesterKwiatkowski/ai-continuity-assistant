# CLAUDE.md — instructions for AI coding agents

This file is loaded automatically by Claude Code. Human developers: read
[`CONTRIBUTING.md`](CONTRIBUTING.md) first; this file is the agent-facing summary of it.

## What this project is

A governed work-context assistant. A colleague can ask about another person's
tasks/emails/chats **only** under a scoped, expiring, audited permission. The rule that
governs every design decision:

> Read with delegated, scoped permission. Write only as the active user. Never impersonate
> the target user.

Security contract: [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Where the work is defined

| Question | File |
|---|---|
| What are we building next, and why | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| In what order, on which branch, what will bite me | [`docs/DELIVERY_PLAN.md`](docs/DELIVERY_PLAN.md) |
| Why is the code shaped like this | [`docs/DECISIONS.md`](docs/DECISIONS.md) (D1–D22) |
| How do I test it | [`docs/TESTING.md`](docs/TESTING.md) |
| What is already built | [`docs/HANDOFF.md`](docs/HANDOFF.md) |

**Start at `docs/DELIVERY_PLAN.md`.** It carries the branch order, the dependencies between
branches, and a risk register. Do not re-plan the work from scratch — the sequencing there
encodes constraints that are not obvious from the code.

## Non-negotiable rules

These are enforced by tests and by review. Do not relax one to make a task pass; if a rule
appears to block the task, stop and say so.

1. No connector call without a Permission Engine decision (`BaseConnector._guard` self-enforces).
2. Writes execute only as `active_user`, using `active_user`'s own connection.
3. Delegated reads of Gmail/Teams require a matching policy — **default-deny**.
4. Every sensitive read and write emits an `AuditEvent`, denials included.
5. Sentinel strings (`SENTINEL_FULL_BODY_DO_NOT_LEAK`, `555-0100`) must never reach a summary.
6. No secrets in code — environment variables and the encrypted token store only.
   `.env` is gitignored and stays that way. Never write a real credential into a tracked file.
7. Tests inject clocks. Never call `date.today()` / `datetime.now()` inside logic under test.
8. `mypy --strict` clean on `src/`; `from __future__ import annotations` in every module.
9. Real integrations only behind the existing `Port` protocols in `connectors/protocols.py` —
   mock and real must stay swappable without touching the orchestrator.
10. The web layer never calls connectors, the registry, or the engine directly. Everything goes
    through `Orchestrator` methods.

## Before you claim a task is done

```bash
ruff check src tests && mypy src && pytest -q
```

All three must be green. State the actual test count in your summary. If something fails, say
so with the output — do not describe partial work as finished.

## Conventions that matter here

- **Branches:** `feature/x` → `post-mvp` → release checklist → `main` + tag. Never commit
  directly to `main`.
- **Commit messages:** this repo uses long, explanatory bodies that record *why* — especially
  for schema changes and security-relevant decisions. Match that. See `616fb1e` for the shape.
- **Decisions get written down.** A structural or security-relevant choice gets a numbered entry
  in `docs/DECISIONS.md` in the same commit that implements it.
- **Roadmap items get checked off** with a date and a pointer to the decision, in the same
  commit that completes them.
- **Deactivate, never hard-delete** anything a policy or audit event references by id.

## Current state (2026-08-17)

- Google OAuth login is **live and verified** on the deployed host. Credentials live in that
  host's gitignored `.env`. The absence of `.env` in a fresh clone is expected and correct.
- All 7 connectors are still **mocks**. `connectors/real/` is empty — that is v0.3.
- The dev user picker (`AUTH_MODE=dev`) is still present and is scheduled for retirement in
  v0.2.1, but **only after** `/admin/people` exists. Do not remove it early: every web test
  currently authenticates through it.
- People are in SQLite now (2026-08-19, DECISIONS D22), behind a real schema-migration
  mechanism. Still open in v0.2.1: `/admin/people` CRUD, deactivation *enforcement* (the
  `Person.active` field exists but nothing checks it yet), role-change auditing, a real
  Google account for `anna`, and retiring the dev login provider.
