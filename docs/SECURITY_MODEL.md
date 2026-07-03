# Security Model

This document is the authoritative description of how the assistant stays safe. Code and tests
must conform to it. When in doubt, **default-deny**.

## The one rule

```
Read with delegated, scoped permission.
Write only as the active user.
Never impersonate the target user.
```

## active_user vs target_user

- **`active_user`** — the authenticated person making the request. The **only** valid actor for
  any write. Their own credential is used for all writes.
- **`target_user`** — the person being asked about. Their data may be *read* only under a matching,
  in-scope, in-condition, non-expired policy. A target_user is **never** an actor for a write.

Every audit event records both, and every write event records `actor_for_write_action`
(which must equal the active_user).

## Access tiers

| Tier          | Whose data                     | Permission needed                          | Notes                                    |
|---------------|--------------------------------|--------------------------------------------|------------------------------------------|
| **self**      | active_user's own              | none                                       | Uses the user's own connection.          |
| **shared**    | team/project/client data       | project membership / shared visibility     | No access to another person's private data. |
| **delegated** | another person's private data  | scoped policy + conditions + audit         | The risky tier; strictest checks. Continuity lives here. |

Tier is decided first: `target_user is None or target_user == active_user` → **self**;
data explicitly shared/project-scoped → **shared**; otherwise → **delegated**.

## Credential rule (enforced at the connection layer)

Because connections are **per-user and self-service**, the "never impersonate" rule is enforced
by *which credential is used*, not merely by convention:

- **Reads** of a target's data use the **target's** connection — and only if the Permission Engine
  authorized that exact `(system, action, scope)`. If the target has not connected that app, the
  read is simply impossible → honest refusal.
- **Writes** always use the **active_user's own** connection. The target's credential is *never*
  used for a write. A write request whose `actor != active_user` is a hard invariant violation
  (raise + audit), not a recoverable condition.

## Read permissions

Delegated reads are governed by policy objects:

### `MailboxAccessPolicy` (Gmail)
`mailbox_owner`, `allowed_requesters`, `scope` (type, client, domain, project),
`allowed_actions`, `conditions`, `expiry_date`, `audit_required`.

### `TeamsAccessPolicy` (Teams)
`target_user`, `allowed_requesters`, `allowed_channels`, `allowed_projects`, `allowed_clients`,
`allowed_keywords`, `date_range`, `allowed_actions`, `conditions`, `expiry_date`, `audit_required`.

### Gmail action levels (least → most privileged)
- `search_metadata` — sender, subject, date, snippet, attachment names. **Cannot** read full email.
- `read_thread` — full thread, only if in authorized scope.
- `summarize` — AI summary. **Preferred over showing the full email.**
- `retrieve_attachment` — access relevant attachments.
- `forward_attachment` — forward to an authorized user; the send happens **as the active_user**.
- `full_mailbox_access` — **avoided** except tightly controlled admin cases.

### Teams action levels
- `search_messages` (by channel, project, client, keywords, date, participant)
- `read_thread` — a specific thread within scope
- `summarize` — AI summary (preferred over dumping messages)
- `retrieve_file` — files shared in Teams within scope
- `post_message` — **only as the active_user**, never as the target_user.

### Scope matching
**Conjunctive and default-deny.** A delegated read is allowed only if *all* applicable scope
dimensions match — client AND project AND date_range AND (for Teams) channel/participant/keywords.
Any miss → deny. Conditions (e.g. `only_when_out_of_office`) must hold and `expiry_date` must not
have passed.

## Write permissions

A separate check: does the active_user have write capability on the target system? If yes, the
write executes with the active_user's connection. The Permission Engine validates read and write
**independently** — read access to a target's data never implies write authority, and vice versa.

Systems covered: Gmail, Google Calendar, Microsoft Teams, Jira, HubSpot, Google Sheets, Drive.

## Approval flow

When permission is **ambiguous or absent**, the assistant **blocks** and offers to request
approval rather than guessing. An `ApprovalRequest` captures: `id`, `requester`, `target_user`,
`approver`, `systems_requested`, `scope`, `reason`, `expiry_date`, `status`.

Approval types: mailbox owner · manager · project owner · admin.

> MVP creates and stores the `ApprovalRequest` and returns a "blocked — approval available"
> response. Asynchronous approver notification/callback is deferred (see IMPLEMENTATION_PLAN).

## Audit rules

Every sensitive read (logged **before** returning results) and every write (logged **after**
execution) produces an `AuditEvent` capturing at least:

`timestamp`, `active_user`, `target_user`, `action_type` (read/write), `system_accessed`,
`search_query`, `resource_ids`, `resource_type`, `attachments_accessed`, `files_accessed`,
`permission_policy_used`, `approval_id` (if any), `actor_for_write_action`, `result_status`,
`reason`.

The log clearly distinguishes requester/active_user vs target_user and read vs write. It is
append-only and queryable by active_user / target_user / system / project / client / date.

### Transparency-to-target
Each delegated-read event fires an optional `notify_target(event)` hook so the affected person can
be told their data was accessed (who, what, when, why). No-op in MVP; pluggable later. This is a
deliberate anti-surveillance measure.

## Privacy guardrails (from the spec)

- No reading another person's email/Teams without explicit permission, delegation, or a continuity
  policy.
- Never return personal, HR, legal, financial, or medical content unless clearly within the
  authorized work scope.
- Never return unrelated private chats/conversations.
- Prefer summaries over full email/message bodies.
- Limit searches by client, project, domain, channel, keywords, and date.
- Read only the most relevant threads.
- Respect native permissions of Jira, HubSpot, Google Workspace, and Microsoft.
- Always cite the source system; state uncertainty when information is incomplete.
- Execute all writes only as the active_user. Never impersonate the target_user.

## Non-impersonation rule (invariants)

1. No write is ever executed with a target_user's credential.
2. No write is ever attributed to a target_user (`actor_for_write_action == active_user` always).
3. A connector write method requires an explicit `active_user` and rejects any other actor.
4. The orchestrator cannot reach a connector without a Permission Engine decision.
5. `full_mailbox_access` and unbounded Teams reads are not implemented in MVP.

These invariants are covered by the security test suite (see IMPLEMENTATION_PLAN, Testing).
