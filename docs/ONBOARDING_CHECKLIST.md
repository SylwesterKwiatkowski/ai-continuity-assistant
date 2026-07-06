# New Developer — Onboarding Checklist

One page. Do the tracks in order; check boxes as you go. Deep detail lives in the linked docs.

## Track 1 — Get running and verify everything (Day 1, ~30 min)

- [ ] **Access**: accept the GitHub invite to `SylwesterKwiatkowski/ai-continuity-assistant`.
- [ ] **Clone and install**:
  ```bash
  git clone https://github.com/SylwesterKwiatkowski/ai-continuity-assistant.git
  cd ai-continuity-assistant
  python3.12 -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev]"
  cp .env.example .env
  ```
- [ ] **Read three files, in this order**:
  1. [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — branch rules + the non-negotiable security rules
  2. [`SECURITY_MODEL.md`](SECURITY_MODEL.md) — the contract all code must obey
  3. [`../README.md`](../README.md) → "Demo scenario" — who Mark / Anna / Lucy are
- [ ] **Run the automated checks** (must be green before AND after any change you make):
  ```bash
  ruff check src tests && mypy src && pytest -q
  ```
- [ ] **Run the app and do the manual smoke** (full table: [`TESTING.md`](TESTING.md)):
  ```bash
  uvicorn assistant.api.app:app --reload   # → http://127.0.0.1:8000
  ```
  Quick version: log in as **mark** → search Anna's ClientCo email (works) →
  log in as **lucy** → same search (**blocked**, approval created) →
  `/admin` as lucy (works) and as mark (**403**) →
  restart the server → audit history still present in `/admin`.
- [ ] **Internalize the work rules**: all work on `post-mvp`; never commit to `main` directly;
      CI green before merge; update docs in the same commit as behavior changes.

## Track 2 — Google Cloud setup (~20 min, one time)

Click-by-click guide: [`GOOGLE_OAUTH_SETUP.md`](GOOGLE_OAUTH_SETUP.md). Condensed:

- [ ] Create a Google Cloud project.
- [ ] Enable 4 APIs: Gmail, Calendar, Sheets, Drive.
- [ ] OAuth consent screen — **Internal** if a Google Workspace org is available (much
      simpler); otherwise External + add test users.
- [ ] Create an OAuth client (Web application), redirect URI
      `http://localhost:8000/auth/google/callback`.
- [ ] Put Client ID/Secret into `.env` (**never into git**).
- [ ] Create 2–3 **sandbox test accounts** (test-Anna, test-Mark) — never real mailboxes.

> Decision owned by the project owner: whether this lives in the company Google
> account/Workspace or a dedicated test org. Everything else you can do alone.

## First coding tasks (in this order — see [`ROADMAP.md`](ROADMAP.md))

1. **Google OAuth login provider** at `/login` — finishes v0.2 (needs Track 2).
2. **v0.3 real connectors** — Calendar first, then Gmail; each behind the existing Ports
   (`src/assistant/connectors/protocols.py`) + the integration test tier from
   [`TESTING.md`](TESTING.md).
3. **v0.4 approval grant/deny loop** — buildable anytime, even before Google Cloud
   (runs entirely on mocks).

## If you remember only one thing

```
Read with delegated, scoped permission.
Write only as the active user.
Never impersonate the target user.
```

Every connector call goes through the Permission Engine; every sensitive read and every
write is audited. If a change would weaken either property, stop and raise it first.
