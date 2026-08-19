# Delivery Plan — v0.2.1 through v0.4.1

_Written 2026-08-17, against `post-mvp` @ `616fb1e`. Companion to [`ROADMAP.md`](ROADMAP.md):
the roadmap says **what** and **why**, this file says **in what order, on which branch, and
what will bite you**._

Read this before starting work. If you are an AI agent, also read [`../CLAUDE.md`](../CLAUDE.md)
and [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — the non-negotiable rules there are enforced by
tests and by review, and are not up for renegotiation inside a task.

## Why this plan exists

Three product decisions were taken on 2026-08-17:

1. **Retire the dev user picker** — Google sign-in is live and verified on the deployed host, so
   real people can log in and the sandbox identity switcher should go.
2. **Add an admin panel for user administration** — onboarding a colleague must not mean editing
   `seeds/people.json` and restarting.
3. **Let every person manage their own delegations** — who may read their data, and who did.

Only #3 was partly on the roadmap. #2 was on it nowhere, and is the largest of the three, because
**people are the last domain object not in the database**. #1 is one line of config but is gated
on #2 existing. The plan below sequences them accordingly.

## Branch plan

Convention per `CONTRIBUTING.md`: `feature/x` → `post-mvp` → release checklist → `main` + tag.

| # | Branch | Release | Depends on | Size |
|---|---|---|---|---|
| 1 | `feature/people-persistence` | v0.2.1 | — | L |
| 2 | `feature/admin-people-crud` | v0.2.1 | 1 | M |
| 3 | `feature/role-audit-guard` | v0.2.1 | 2 | S |
| 4 | `feature/retire-dev-login` | v0.2.1 | 2 | M |
| 5 | `feature/approver-decides` | v0.4.0 | — | S |
| 6 | `feature/notification-channel` | v0.4.0 | — | M |
| 7 | `feature/revoke-and-duration` | v0.4.0 | — | M |
| 8 | `feature/self-service-delegation` | v0.4.1 | 1, 5, 7 | L |

**Critical path:** 1 → 2 → 4. Branch 5 has no dependencies and is the cheapest high-value change
in the entire plan — start it first, in parallel, regardless of everything else. Branch 6 can also
start at any time.

**One non-code task with external lead time:** map `anna` to a real Google account (a third test
address). She is the target of every demo flow and the owner-side actor in branch 8; while she
stays the `anna@acme.com` placeholder, the whole owner-side experience is untestable through a
real login. Start this at branch 1, not at branch 8.

---

## Phase 1 — Identities (v0.2.1)

### 1. `feature/people-persistence`

Pure backend. No user-visible change; the existing suite is the regression net.

- `people` table + `SqlitePersonRepository` in `storage/repositories.py`.
- Seed from `seeds/people.json` on first boot — extend `storage/seed.py:initialize_database`,
  which does not touch people at all today. The seed file stays a bootstrap fixture; the DB
  becomes the runtime source of truth.
- `IdentityResolver` (`identity/resolver.py`) gains mutation and must reflect changes **in the
  running process**: `bootstrap.py` hands one instance to both the `PermissionEngine` and the
  `Orchestrator` at startup. Mirror the pattern D20 established for policies
  (`engine.add_mailbox_policy()`). Do not invent a second mechanism.
- **Ship a migration mechanism in this branch** (see Risk 1). The deployed host holds audit
  history and granted policies that cannot be regenerated.

**Done when:** people load from SQLite, `from_seed()` is a first-boot path only, a person added
directly to the DB is resolvable without a restart, and all 136 existing tests still pass.

### 2. `feature/admin-people-crud`

- `/admin/people` routes + template, gated by the existing `_require_admin` (`web/routes.py`).
- Create, edit (name, email, per-system handles, manager, backup owners), deactivate.
- Editing an email must keep OAuth login working — login resolves by email (D19,
  `identity/oauth.py` → `resolver.by_email`).
- **Deactivate, never hard-delete** (see Risk 3). Deactivation must be one guard the engine
  consults, not four independent checks scattered across login, policy evaluation, policy
  creation and the UI pickers.

**Done when:** a colleague is onboarded end-to-end through `/admin`, signs in with Google, and is
selectable wherever a person can be named — no JSON edit, no restart.

### 3. `feature/role-audit-guard`

Small, but it is a security invariant and deserves its own reviewable diff.

- Role changes go through the audit log. An admin granting a role — especially to themselves — is
  precisely the event this system exists to record.
- Last-admin guard: the final `admin` role cannot be removed or deactivated. Lockout on the
  deployed host, after branch 4, has no recovery path that isn't SSH and SQL.

### 4. `feature/retire-dev-login`

**Two commits, in this order** — the split is deliberate, so that if something breaks you know
which half did it:

1. **Migrate the tests.** `tests/test_web.py` and `tests/test_auth.py` authenticate via
   `client.post("/login", data={"user": ...})`. Switch them to minting a session directly with
   `SessionManager.issue()` — `test_auth.py` already does exactly this for its session tests.
   Suite must be green with the dev picker still present.
2. **Gate the dev provider.** Preferred form: permit `AUTH_MODE=dev` only when
   `app_env == "local"` (`config.py` already rejects it when `app_env == "prod"`; this extends the
   same fail-closed validator to `dev`). Offline development survives a Google outage; no deployed
   environment can ever authenticate anyone without Google.

Keep D17's pluggable-provider seam. Only the dev *provider* is being retired, not the abstraction.

**Do branch 4 only after the Operational debt items in `ROADMAP.md` are addressed** — see Risk 4.

---

## Phase 2 — Consent (v0.4.0)

### 5. `feature/approver-decides` — ✅ done (2026-08-19, DECISIONS D21)

The single highest value-per-line change available. No dependencies; do it first.

The engine already routes Gmail denials to the mailbox owner
(`engine._suggest_approver` → `ApprovalType.MAILBOX_OWNER`) and records them as
`ApprovalRequest.approver`. But `POST /admin/approvals/{id}/grant` is `_require_admin`-gated
(`web/routes.py`). The system nominates Anna as approver and then lets an admin decide in her
place — the code contradicts what `SECURITY_MODEL.md` already claims.

- Allow the named approver to act on requests over their own data.
- Keep admin as an explicit override, audited **as an override**, distinguishable in the log.

### 6. `feature/notification-channel`

There is no notification mechanism of any kind in the codebase today. Everything owner-facing
depends on this existing.

- A `Notifier` protocol with a `StubNotifier` default, the same shape as `Summarizer`
  (`summarizer/base.py` + `summarizer/stub.py`, D9). Tests stay deterministic; no mail server is
  needed until it is genuinely needed.
- Then approver notification and transparency-to-target are thin consumers of it.

### 7. `feature/revoke-and-duration`

- Revoke route + UI. `SqlitePolicyStore.delete_mailbox`/`delete_teams` already exist; there is no
  route and no button. Revocation must take effect in-process immediately — the mirror of
  `engine.add_mailbox_policy()` — not at next restart.
- `GRANT_DURATION_DAYS` (fixed 14, `orchestrator/service.py`) becomes a bounded parameter with a
  server-enforced maximum. Default unchanged. An owner approving access wants "until I'm back".

---

## Phase 3 — Ownership (v0.4.1)

### 8. `feature/self-service-delegation`

Larger, but by this point every primitive exists; it is mostly composition and one page.

- `/me/delegations`: every policy naming the viewer as `mailbox_owner`/`target_user` — grantee,
  exact scope, expiry, and origin (seed / approved request / self-granted).
- Owner-initiated grant: a scoped, expiring policy with **no** prior `ApprovalRequest`.
  `Orchestrator.grant_approval()` already shows how to materialize one; this is the same path
  minus the approval, audited as an owner action rather than an admin one.
- Scope validation (see Risk 2) — this is the security-critical part of the branch.
- Owner revoke, immediate and audited.
- Personal access history on the same page, so "who read my mail" and "who *can* read my mail"
  are one screen.

---

## Risk register

Ordered by severity. Each names the failure mode, not just the concern.

### High

**R1 — Irreplaceable state on the deployed host, with no migration path.**
D20's policy re-keying was absorbed by a fresh database. Branch 1 adds a table; branch 7 may alter
policy rows. That host now holds real audit history and real granted policies.
*Failure mode:* not an error — a silent reseed or schema mismatch that drops the audit trail. In a
system whose entire value proposition is "every access is auditable", that is the worst available
outcome, and it is silent.
*Mitigation:* build the migration mechanism inside branch 1, before it is urgent. Back up the
host's SQLite file before the first deploy of branch 1.

**R2 — Self-service delegation is a privilege-escalation surface.**
Every grant path so far had an admin in it. `/me/delegations` lets a non-admin create policy rows.
*Failure mode:* incomplete scope validation — Anna grants access to a mailbox that is not hers,
names herself as requester on someone else's data, grants to a deactivated person, or exceeds the
duration maximum. Any one of these is a bypass around the entire permission engine.
*Mitigation:* adversarial tests in the `tests/test_security_acceptance.py` style (`test_p6_*`), not
happy-path coverage. Validate server-side, never trust the form. Treat every field of an
owner-submitted grant as hostile.

**R3 — Deactivation is a security control spread across four call sites.**
Login, policy evaluation, policy creation, and the person pickers.
*Failure mode:* miss one and a deactivated person retains working delegated access — exactly the
"revoke the departing employee" scenario the feature exists to serve, failing silently.
*Mitigation:* one guard the engine consults, plus a test asserting a deactivated person is denied
through every entry point.

### Medium

**R4 — Retiring dev login while the deployment is undocumented.**
After branch 4, Google is the only way in outside localhost. There is no Dockerfile, systemd unit,
Procfile or runbook in version control, and no doc recording the host, the live
`GOOGLE_REDIRECT_URI`, or the restart procedure.
*Failure mode:* OAuth client misconfiguration, an unverified-app user cap, or a host rebuild locks
everyone out, and the recovery procedure exists only in one person's memory.
*Mitigation:* land the Operational debt items in `ROADMAP.md` **before** branch 4, not after.

**R5 — The resolver becomes shared mutable state.**
`bootstrap.py` hands one `IdentityResolver` instance to the engine and orchestrator.
*Failure mode:* under a multi-worker uvicorn/gunicorn deployment, worker A's newly created user is
invisible to worker B until restart — an intermittent, confusing, hard-to-reproduce bug.
*Mitigation:* check how the host actually runs the app. If multi-worker, the resolver must read
through to SQLite rather than caching people in memory.

**R6 — Real logins against mock data.**
People sign in as themselves and see Anna's fictional `acme.com` mail; `connectors/real/` is still
empty and v0.3 is untouched.
*Failure mode:* testers read the mocks as bugs, and the feedback gathered describes a system that
does not exist yet.
*Mitigation:* say so explicitly to anyone testing, or hold user testing until v0.3.

### Governance — not a code risk, but a hard gate

**R7 — The DPIA obligation triggers at v0.3, not at v1.0.**
Testing consent flows over mock data is fine. The first real Gmail read of a colleague's actual
mailbox is processing of employee personal data, and D12 already commits this project to a DPIA
and works-council review before that point. `ROADMAP.md` lists it under v1.0, which is misleading
about *when* it binds.
*Consequence:* this plan is deliberately ordered so all governance machinery (v0.2.1, v0.4.x) lands
while data is still mock. If v0.3 is pulled forward, the DPIA must be pulled forward with it.
"We were only testing" is not a defence under GDPR.

---

## Acceptance, per release

- **v0.2.1** — a colleague is onboarded entirely through `/admin`, signs in with Google, appears in
  policy pickers; no deployed environment can authenticate anyone without Google.
- **v0.4.0** — Lucy's blocked search becomes an approved, expiring, audited access *decided by
  Anna, who was told it was waiting*; Anna can revoke it before expiry.
- **v0.4.1** — before going out of office Anna grants Mark scoped access to her ClientCo mail until
  her return date, then revokes it early herself: no admin, no blocked request, and Mark's access
  changes on his next query.
