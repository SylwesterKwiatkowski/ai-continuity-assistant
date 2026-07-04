# Roadmap

Post-MVP release plan. Work happens on `post-mvp`; each release merges to `main` with a tag
after the release checklist in [`../CONTRIBUTING.md`](../CONTRIBUTING.md) passes.

Status: **v0.1.0-mvp shipped** (M0–M7: security core, mock connectors, orchestrator flows,
web app, 83 tests). See `IMPLEMENTATION_PLAN.md` for what the MVP contains.

## v0.2.0 — Trustworthy identity & memory  *(do this first)*

The MVP's two declared weaknesses, fixed before any real data is wired:

- [x] **CI** (GitHub Actions: ruff + mypy + pytest on all three branches) — ✅ done 2026-07-03.
      Branch protection on `main` needs GitHub Pro on private repos (API 403 on Free) —
      protection is by convention for now; TESTING.md has the enable command post-upgrade.
- [x] **Session authentication** (2026-07-04): HMAC-signed, server-issued session tokens
      replace the arbitrary cookie; identity comes only from a verified session. The user
      switcher survives solely as the dev login provider (`AUTH_MODE=dev`, warning banner);
      `AUTH_MODE=oauth` disables it. See DECISIONS D17.
- [ ] **Google OAuth provider** for `/login` — needs real Google Cloud client credentials;
      plugs into the same session flow (remainder of "real authentication").
- [x] **Persistence** (2026-07-04): SQLite via the repository interfaces for audit events,
      policies, approvals, connections; state survives restarts. `DATABASE_URL` is real.
      See DECISIONS D18.
- [x] **Encrypted token store** (2026-07-04): Fernet encryption at rest behind the existing
      `TokenStore` protocol, key derived from `TOKEN_STORE_KEY`.
- [x] **Admin role gate** (2026-07-04): `/admin` requires the `admin` role (`Person.roles`);
      403 otherwise. *(From external review, 2026-07-03.)*

**Definition of done:** a restart loses nothing; nobody can act without logging in;
acceptance suite green.

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

- [ ] Approver notification (email or web inbox) for pending `ApprovalRequest`s.
- [ ] Grant/deny actions; a grant materializes a **temporary scoped policy** with
      auto-expiry; deny records the reason.
- [ ] **Transparency-to-target** goes live: the target is notified when their delegated data
      is read (who/what/when/why) + a personal access-history page.
- [ ] Admin actions: revoke a policy, see sensitive-access alerts.

**Definition of done:** Lucy's blocked search can become an approved, expiring, audited
access without an admin editing JSON.

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
2. **Calendar before Gmail** — prove per-user OAuth on availability data before mail content.
3. **Approvals before the Teams bot** — the bot's UX depends on approval buttons existing.
4. **LLM late** — it is the easiest swap (one protocol) and everything is testable without it.

## Deferred / ideas parking lot

Slack connector · GitHub/GitLab connector · Notion/Confluence · meeting-transcript ingestion
(Zoom/Meet/Gong) · DLP/PII redaction in summaries · SIEM export of the audit log ·
multi-tenant productization.
