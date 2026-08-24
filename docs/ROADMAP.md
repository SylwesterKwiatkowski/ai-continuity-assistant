# Roadmap

Post-MVP release plan. Work happens on `post-mvp`; each release merges to `main` with a tag
after the release checklist in [`../CONTRIBUTING.md`](../CONTRIBUTING.md) passes.

**This file is the *what* and *why*. For the *how* — branch-by-branch order, dependencies between
branches, and the risk register — see [`DELIVERY_PLAN.md`](DELIVERY_PLAN.md), and read it before
starting any of the work below.**

Status: **v0.1.0-mvp shipped** (M0–M7: security core, mock connectors, orchestrator flows,
web app); **v0.2 complete** — trust infrastructure and the Google OAuth login provider have
both landed, and Google sign-in is live and verified against the deployed instance (client
credentials live in that host's gitignored `.env`, never in the repo). **v0.2.1 in progress**:
people are in SQLite (DELIVERY_PLAN branch 1, DECISIONS D22) and `/admin/people` CRUD with
full deactivation enforcement has landed (branch 2, DECISIONS D23); role-change auditing and
retiring the dev login provider remain. See `IMPLEMENTATION_PLAN.md` for MVP contents; current
test count comes from CI, not docs.

## v0.2.0 — Trustworthy identity & memory  *(do this first)*

The MVP's two declared weaknesses, fixed before any real data is wired:

- [x] **CI** (GitHub Actions: ruff + mypy + pytest on all three branches) — ✅ done 2026-07-03.
      Branch protection on `main` needs GitHub Pro on private repos (API 403 on Free) —
      protection is by convention for now; TESTING.md has the enable command post-upgrade.
- [x] **Session authentication** (2026-07-04): HMAC-signed, server-issued session tokens
      replace the arbitrary cookie; identity comes only from a verified session. The user
      switcher survives solely as the dev login provider (`AUTH_MODE=dev`, warning banner);
      `AUTH_MODE=oauth` disables it. See DECISIONS D17.
- [x] **Google OAuth provider** for `/login` (2026-08-03): `identity/oauth.py` implements
      the Authorization Code flow; `/auth/google/login` + `/auth/google/callback` plug into
      the existing session flow. Only activates once `GOOGLE_CLIENT_ID`/`_SECRET` are set —
      follow [`GOOGLE_OAUTH_SETUP.md`](GOOGLE_OAUTH_SETUP.md) to generate them (one-time,
      ~20 minutes; also unblocks all of v0.3). See DECISIONS D19.
- [x] **Persistence** (2026-07-04): SQLite via the repository interfaces for audit events,
      policies, approvals, connections; state survives restarts. `DATABASE_URL` is real.
      See DECISIONS D18.
- [x] **Encrypted token store** (2026-07-04): Fernet encryption at rest behind the existing
      `TokenStore` protocol, key derived from `TOKEN_STORE_KEY`.
- [x] **Admin role gate** (2026-07-04): `/admin` requires the `admin` role (`Person.roles`);
      403 otherwise. *(From external review, 2026-07-03.)*

**Definition of done:** a restart loses nothing; nobody can act without logging in;
acceptance suite green.

## v0.2.1 — Administrable identities  *(prerequisite for real users; before v0.3)*

People are the last domain object **not** in the database: `seeds/people.json` is read once at
boot into an in-memory `IdentityResolver` (`identity/resolver.py`), while audit, approvals,
connections and policies are all SQLite-backed. Onboarding a colleague today means editing JSON
and restarting the host — untenable now that real Google accounts sign in.

- [x] **`people` table + `SqlitePersonRepository`** (2026-08-19), seeded from
      `seeds/people.json` on first boot only (`storage/seed.py:initialize_database`). The seed
      file is now a bootstrap fixture; the DB is the runtime source of truth. Shipped alongside
      a real schema-migration mechanism (`storage/db.py`) — see DECISIONS D22.
- [x] **Runtime-mutable resolver** (2026-08-19): `bootstrap.py` hands one `IdentityResolver`
      instance to the engine and orchestrator at startup; `resolver.upsert()` makes a new or
      edited person effective in-process, no restart — mirrors D20's
      `engine.add_mailbox_policy()`. See DECISIONS D22.
- [x] **Admin user CRUD** at `/admin/people` (2026-08-24), gated by the existing
      `_require_admin` (`web/routes.py`): create, edit (name, email, per-system handles,
      manager, backup owners), deactivate/reactivate. Editing an email keeps OAuth login
      working — verified directly (D19, D23).
- [x] **Deactivate, never hard-delete** (2026-08-24). A deactivated person cannot log in
      (including mid-session — enforced on every request, not just at login), cannot be
      named in a new policy grant, and their existing policies evaluate as denied. Four
      independent checks consulting the same `Person.active` field — see DECISIONS D23.
- [ ] **Role changes are audited; the last admin cannot be removed.** `Person.roles` is a
      free-form list where only `"admin"` is meaningful. An admin granting a role — especially to
      themselves — is exactly the event this system exists to record, so it goes through the
      audit log. A last-admin guard prevents lockout.
- [ ] **Map `anna` to a real Google account** (a third test account). She is the target of every
      demo flow and the owner-side actor in v0.4.1; while she remains the `anna@acme.com`
      placeholder, the entire owner-side experience is untestable through a real login.
- [ ] **Retire the dev login provider** — last, and only once the above works. Removing the
      `POST /login` user picker and the `AUTH_MODE=dev` branch means every web test that
      authenticates via `client.post("/login", ...)` (`tests/test_web.py`, `tests/test_auth.py`)
      must mint a session directly through `SessionManager.issue()` — the pattern `test_auth.py`
      already uses for its session tests. Keep D17's pluggable-provider seam; only the dev
      *provider* goes. Preferred form: permit `dev` only when `app_env == "local"`, so offline
      development survives a Google outage while no deployed environment can ever use it.

**Definition of done:** a colleague is onboarded entirely through `/admin`, signs in with Google,
and is selectable in policy pickers — no JSON edit, no restart; and no deployed environment can
authenticate anyone without Google. *(Onboarding through `/admin` works today; the remaining gap
is that "signs in with Google" still means one of the three seeded people — a real account for
`anna` and retiring the dev provider are what's left.)*

## v0.3.0 — First real connectors (Google side)

Order chosen to prove OAuth plumbing on low-sensitivity data before touching mailboxes:

- [ ] Per-user OAuth consent flow on `/connections` (authorize → store token → scopes shown).
- [ ] **Google Calendar** connector (real OOO detection replaces the mock absence signal).
- [ ] **Gmail** connector (metadata search → thread read → attachments), strictly behind the
      existing `GmailPort` + guards. The Gmail query builder derives from policy scope
      (client domain, keywords, date range) — never broader.
- [ ] **Sheets** and **Drive** connectors.
- [ ] Integration test tier (`@pytest.mark.integration`, sandbox account) — see TESTING.md.
- [ ] Shared guard-test suite parametrized over mock + real implementations.

**Definition of done:** the flagship flow runs against a real Google Workspace sandbox with
the same permission behavior the mocks enforce.

## v0.4.0 — Approval loop closed & transparency live

- [x] **Grant/deny actions** (2026-08-14): `POST /admin/approvals/{id}/grant`/`/deny` from
      `/admin`. Granting materializes a **temporary scoped policy** with auto-expiry
      (`GRANT_DURATION_DAYS`, currently 14) scoped to exactly the original request; denying
      records the reason. Both are audited. Required first extending the policy store to
      support multiple policies per person — see DECISIONS D20.
- [x] **The named approver can decide — not only an admin** (2026-08-19): the nominated
      approver (`ApprovalRequest.approver`) can now grant/deny requests over their own data
      at the same `/admin/approvals/{id}/grant`/`/deny` routes, surfaced to them at the new
      `GET /approvals/mine` (not admin-gated). Admin remains a decision path, now recorded
      as an explicit, audited override (`ApprovalRequest.decided_by` vs `.approver`). See
      DECISIONS D21.
- [ ] **Notification channel** (SMTP or in-app inbox) — *there is none in the codebase today*.
      Pick one here: it is the hard prerequisite for approver notification, for
      transparency-to-target, and for all of v0.4.1. An approval loop whose approver never
      learns a request exists is a loop nobody closes.
- [ ] **Approver notification** for pending `ApprovalRequest`s, over that channel — an admin
      still has to know to check `/admin`.
- [ ] **Transparency-to-target** goes live: the target is notified when their delegated data
      is read (who/what/when/why) + a personal access-history page.
- [ ] **Revoke a granted policy** — `SqlitePolicyStore.delete_mailbox`/`delete_teams` exist;
      no route, no UI. Grant-without-revoke is not acceptable once anyone but an admin grants.
      Revocation must take effect in-process immediately (the mirror of D20's
      `engine.add_*_policy()`), not at next restart.
- [ ] **Approver-chosen grant duration** — `GRANT_DURATION_DAYS` is a fixed 14-day module
      constant (`orchestrator/service.py`). An owner approving access wants "until I'm back".
      Make it a bounded parameter (policy maximum enforced server-side); default unchanged.
- [ ] Admin actions: sensitive-access alerts.

**Definition of done:** Lucy's blocked search becomes an approved, expiring, audited access
**decided by Anna, who was told it was waiting** — no admin, no JSON edit — and Anna can revoke
it before it expires. *(Grant/deny loop and approver-decides done; Anna can already decide
her own request at `/approvals/mine` — notification, revoke UI, and grant duration remain.)*

## v0.4.1 — Self-service delegation (owner-managed)

Everything up to here is reactive: a delegation exists only because someone was blocked first.
This release lets people set up and tear down delegations over their own data proactively —
the human half of the continuity promise, and the precondition for v1.0's automated handoff packs.

- [ ] **`/me/delegations`** — a person sees every policy naming them as `mailbox_owner` /
      `target_user`: who it grants access to, exact scope, expiry, and origin (seed, approved
      request, or self-granted).
- [ ] **Owner-initiated grant** — create a scoped, expiring policy with no prior
      `ApprovalRequest`. `Orchestrator.grant_approval()` already shows how to materialize one;
      this is the same path minus the approval, audited as an owner action rather than an
      admin one.
- [ ] **Scope validation on self-service grants**: never broader than what the grantor can
      themselves access, never naming a deactivated person (v0.2.1), always bounded by the
      policy-maximum duration. Self-service must not become a privilege-escalation route.
- [ ] **Owner revoke** of any policy over their own data — immediate, audited, and reflected to
      the grantee's next request without a restart.
- [ ] **Personal access history** — the target-side view from v0.4.0 lives on this same page, so
      "who read my mail" and "who *can* read my mail" are one screen.

**Definition of done:** before going out of office, Anna grants Mark scoped access to her ClientCo
mail until her return date, then revokes it early herself — no admin involved, no blocked request
needed, and Mark's access changes on his very next query.

## v0.5.0 — Microsoft side & the Teams bot

- [ ] **Jira**, **HubSpot**, **Teams** real connectors (same Port discipline).
- [ ] **Teams bot** (`@Secretary`): natural commands, responses with sources, approval
      buttons, action buttons — a thin client over the same orchestrator; no new data paths.

## v0.6.0 — Real LLM layer

- [ ] Swap `StubSummarizer` for Claude (latest, e.g. `claude-opus-4-8`) behind the existing
      `Summarizer` protocol; the stub remains the test default.
- [ ] Natural-language intent parsing (free-text → flow + entities) replacing fixed forms;
      the parsed plan is still authorized step-by-step by the Permission Engine — the LLM
      never gains direct data access (spec §10.4 rules).
- [ ] Summary quality guardrails: cite-or-omit, uncertainty statements, no personal data.
- [ ] **LLM safety test tier**: prompt-injection resistance (retrieved email/Teams content is
      attacker-controllable input to the summarizer), refusal behavior, citation fidelity,
      and PII/raw-body leakage checks. *(From external review, 2026-07-03.)*

## v1.0 — Pilot-ready

- [ ] "Shared" access tier fully modeled (project membership) — closes the known limitation.
- [ ] Proactive **handoff packs**: detect upcoming OOO → pre-generate a scoped continuity
      brief the owner reviews and approves before leaving.
- [ ] Security review + **DPIA / works-council review** — deliberately out of MVP scope but
      **mandatory before production use with real employee mailbox data** (see DECISIONS D12).
- [ ] Postgres option, deployment story, backup/retention policy for the audit log.

## Ordering rationale (for whoever picks this up)

1. **Auth before real data** — never connect a real mailbox to a cookie-stub identity.
2. **Administrable identities before real connectors** — once real mailboxes are wired, adding a
   person by editing JSON and restarting the host is both an outage and an unaudited act.
3. **Calendar before Gmail** — prove per-user OAuth on availability data before mail content.
4. **Notification before self-service** — owner-managed delegation is worthless if the owner is
   never told there is something to decide.
5. **Owner-side approval before owner-side granting** — the reactive path (v0.4.0) is smaller and
   exercises the same authorization questions the proactive path (v0.4.1) will face.
6. **Approvals before the Teams bot** — the bot's UX depends on approval buttons existing.
7. **LLM late** — it is the easiest swap (one protocol) and everything is testable without it.
8. **Governance gates the data, not the code** — v0.2.1 and v0.4.x are best landed *while data is
   still mock*, because v0.3 is what triggers the DPIA obligation below.

## Operational debt  *(not release-gated, but real)*

- [ ] **The deployment is not in the repo.** A remote host runs the app with real Google
      credentials in a gitignored `.env` — correct for the secrets, but there is no
      Dockerfile / systemd unit / Procfile / runbook under version control, and no doc recording
      the host, the live `GOOGLE_REDIRECT_URI`, or the restart-and-migrate procedure. Rebuilding
      or handing over that box currently depends on one person's memory. v1.0's "deployment
      story" is the destination; this is the interim gap.
- [ ] **Secret rotation procedure** for `SESSION_SECRET` and `TOKEN_STORE_KEY`. Rotating the
      latter orphans every encrypted token; `bootstrap.py` silently re-stubs them today, which
      real connectors will not tolerate. Write the procedure before v0.3, not after.
- [x] **Schema migrations** (2026-08-19): `storage/db.py` now runs a versioned, append-only
      list of migrations tracked in `schema_migrations`, applied via `CREATE TABLE IF NOT
      EXISTS` — safe against a database that already has a table from before migrations
      existed (verified against a simulated pre-migration file; see DECISIONS D22). Landed
      in the same branch that added the `people` table, per its own requirement.
- [ ] **DPIA / works-council review timing** (D12, listed under v1.0). Mock data keeps it
      deferrable. The moment v0.3 points real connectors at colleagues' actual mailboxes it is
      not deferrable — and "we were only testing" is not a defence under GDPR.

## Deferred / ideas parking lot

Slack connector · GitHub/GitLab connector · Notion/Confluence · meeting-transcript ingestion
(Zoom/Meet/Gong) · DLP/PII redaction in summaries · SIEM export of the audit log ·
multi-tenant productization.
