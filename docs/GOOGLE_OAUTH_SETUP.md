# Google OAuth Setup Guide

One-time setup that unblocks **v0.2's remaining item** (OAuth login provider) and **v0.3**
(real Google connectors: Calendar → Gmail → Sheets → Drive). Anyone with access to the
Google account can follow this; ~20 minutes.

> **Strong recommendation:** use a **Google Workspace test domain / sandbox accounts**, not
> your real company mailboxes. The integration tests will read and plant email fixtures.

## 1. Create the Google Cloud project

1. Go to https://console.cloud.google.com → project picker → **New Project**.
2. Name: `ai-continuity-assistant-dev` (anything works). Note the **Project ID**.

## 2. Enable the APIs

**APIs & Services → Library**, enable each of:

| API | Needed for |
|---|---|
| Gmail API | delegated mailbox search/read, send-as-active-user |
| Google Calendar API | OOO detection, meetings, create-event |
| Google Sheets API | recurring tasks, trackers |
| Google Drive API | file search/metadata |

## 3. Configure the OAuth consent screen

**APIs & Services → OAuth consent screen**:

- **User type — this choice matters:**
  - **Internal** (available only if the project is inside a Google Workspace org):
    zero-verification, all users in the domain can consent. **Pick this if you can.**
  - **External**: fine for dev, but stays in *Testing* mode — add each sandbox account
    under **Test users** (max 100). Note: Gmail scopes are **restricted scopes**; taking an
    External app to production later requires Google's security verification. Internal
    apps skip that entirely.
- App name: `AI Continuity Assistant`; support + developer email: yours.
- Scopes: you can leave empty here (the app requests scopes at runtime), or pre-add the
  list below for clarity.

## 4. Scopes the app will request (least privilege, per action tier)

| Purpose | Scope |
|---|---|
| Login / identity | `openid`, `email`, `profile` |
| Calendar read (OOO, meetings) | `https://www.googleapis.com/auth/calendar.readonly` |
| Calendar create-event (write, as active user) | `https://www.googleapis.com/auth/calendar.events` |
| Gmail metadata + thread read (delegated, policy-gated) | `https://www.googleapis.com/auth/gmail.readonly` |
| Gmail send / drafts (write, as active user) | `https://www.googleapis.com/auth/gmail.send`, `https://www.googleapis.com/auth/gmail.compose` |
| Sheets read / write | `https://www.googleapis.com/auth/spreadsheets.readonly` → upgrade to `.../spreadsheets` when writes land |
| Drive file search (read) | `https://www.googleapis.com/auth/drive.readonly` |

v0.3 starts with **read-only + gmail.send** — write scopes are added per connector as the
write actions ship. Per-user consent happens on `/connections`, so each person grants only
the systems they connect (matches DECISIONS D6).

## 5. Create the OAuth client

**APIs & Services → Credentials → Create credentials → OAuth client ID**:

- Application type: **Web application**
- Name: `assistant-web-dev`
- Authorized redirect URIs (add both):
  - `http://localhost:8000/auth/google/callback`
  - `http://127.0.0.1:8000/auth/google/callback`

Copy the **Client ID** and **Client secret**.

## 6. Put the credentials in `.env` (never in git)

```bash
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

These keys are the contract the v0.3 implementation will read (they are documented in
`.env.example`; `Settings` gains the fields when the OAuth provider is built). The client
secret is a secret — it lives in `.env`/the deployment secret store only.

## 7. Sandbox accounts for integration tests

Create 2–3 test accounts (e.g. `test-anna@…`, `test-mark@…`):

- **Workspace test domain**: create them as normal users; Internal consent covers them.
- **External/consumer**: plain Gmail accounts added as **Test users** on the consent screen.

The v0.3 integration tier (see `TESTING.md`) will seed them: an OOO event in test-Anna's
calendar, a "ClientCo" fixture email with attachments in her mailbox (including a sentinel
string that must never leak into summaries).

## 8. Done — what unblocks

| With these credentials | Roadmap item |
|---|---|
| Google **login** at `/login` (AUTH_MODE=oauth) | finishes v0.2 |
| Per-user consent flow on `/connections` | v0.3 |
| Real Calendar → Gmail → Sheets → Drive connectors + integration test tier | v0.3 |

## Troubleshooting

- **"Access blocked: app not verified"** — External app: the signing-in account isn't in
  Test users, or you're requesting restricted scopes in production mode. Add the test user
  or switch to Internal.
- **`redirect_uri_mismatch`** — the URI in the request must match step 5 **exactly**
  (scheme, host, port, path).
- **Consent screen shows scary warning** — normal for External+Testing apps; click
  *Continue* (advanced). Internal apps don't show it.
