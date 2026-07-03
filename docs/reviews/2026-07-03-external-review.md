# Developer Review Notes

Prepared after reviewing the `ai-continuity-assistant` repository, comparing branches, and running
the local validation suite.

## Summary

This is a strong MVP/security prototype. The idea is sound: an internal business-continuity
assistant that helps recover work context while explicitly avoiding "anyone can ask anything about
anyone." The strongest part of the design is the separation between:

- `active_user`: the authenticated person using the assistant.
- `target_user`: the person whose work context may be queried.

The core governing rule is correctly reflected across the docs and code:

```text
Read with delegated, scoped permission.
Write only as the active user.
Never impersonate the target user.
```

The implementation is not production-ready yet, but it is well structured for an MVP. The most
important security boundaries are implemented in code, not only described in documentation.

## What Is Done Well

1. Security-first architecture

   The project starts with identity, permissions, audit, connector guards, mocks, and deterministic
   tests before any real Gmail/Teams data is connected. That is the right order for this kind of
   product.

2. Permission engine is a real chokepoint

   `PermissionEngine` implements default-deny behavior for sensitive delegated reads. Gmail and
   Teams require explicit policies, valid scope, valid conditions, and non-expired access.

3. Connector boundary is guarded

   `BaseConnector._guard()` checks that a connector call has an allowed permission decision, matches
   the intended system/action/access type, and uses the correct user's credential. This is an
   important backstop against accidental bypasses in orchestrator code.

4. Credential model is directionally right

   Private delegated reads use the target user's connection for Gmail/Teams. Writes use only the
   active user's connection. That is the right implementation of "never impersonate."

5. Audit is treated as part of the product

   Sensitive reads and writes are audited, and test coverage checks audit behavior. The MVP is also
   honest that transparency-to-target is still deferred.

6. Tests are meaningful

   The project includes a dedicated `tests/test_security_acceptance.py` suite covering the 12
   important security behaviors: unauthorized reads blocked, scoped reads allowed, out-of-scope Teams
   denied, writes as active user only, audit events, approval flow, connector guard, and no raw
   sensitive body leakage.

7. Roadmap is honest

   The roadmap correctly identifies the remaining high-risk gaps: real auth, persistence, encrypted
   token storage, real OAuth connectors, approval completion, transparency notifications, and
   legal/privacy review before real employee mailbox data.

## What Can Be Better

1. Real authentication must come before real data

   The current web app uses a cookie-based user switcher. This is fine for a demo, but it must not be
   connected to real company data. Real login and session-to-person mapping should be the next
   implementation milestone.

2. Persistence is required for audit and approvals

   Audit events, approvals, policies, and connections are currently seed/in-memory style MVP
   structures. A restart losing audit or approval state is not acceptable beyond demo.

3. Encrypted token storage is required before OAuth

   The `TokenStore` protocol is a good abstraction, but the MVP store is not production storage.
   Implement encrypted persistent token storage before any real connector rollout.

4. The "lower-sensitivity systems" assumption needs review

   Gmail and Teams are correctly treated as sensitive. Jira, Calendar, HubSpot, Sheets, and Drive are
   currently treated as lower-sensitivity work context. In real companies, these systems may contain
   sensitive HR, legal, financial, customer, or personal data. This decision should be revisited
   before production use.

5. Approval flow is only started, not closed

   The MVP creates pending approval requests, but does not notify approvers, allow grant/deny, or
   materialize temporary scoped policies. This should be completed before wider internal use.

6. Real LLM layer needs its own safety tests

   The stub summarizer is good for deterministic security tests. When replacing it with a real LLM,
   add tests for citations, uncertainty, refusal behavior, prompt-injection resistance, and PII/raw
   body leakage.

7. Manual admin/connections screens are demo-grade

   The web layer mostly goes through the orchestrator, which is good. The admin and connections
   surfaces are useful for MVP testing, but they need real authorization boundaries before
   production.

8. Branch protection is not fully enforced

   Docs note that GitHub branch protection is not enabled due to account limitations. Until this is
   solved, merges to `main` rely on convention.

## Branch Comparison

There are three branches locally:

- `mvp`
- `post-mvp`
- `main`

Practical difference:

- `mvp` is the frozen MVP branch.
- `post-mvp` has the same app code and tests as `mvp`, plus documentation/process updates.
- `main` and `post-mvp` currently have no file differences.

Difference from `mvp` to `post-mvp`:

- Added `CONTRIBUTING.md`
- Added `docs/ROADMAP.md`
- Added `docs/TESTING.md`
- Updated `README.md`
- Updated `docs/IMPLEMENTATION_PLAN.md`

No differences were found in:

- `src/`
- `tests/`
- `seeds/`
- `pyproject.toml`

Conclusion: behaviorally, `mvp` and `post-mvp` are the same app. Operationally, `post-mvp` is
better documented and easier to hand off.

## Test Results

Validation was run locally through the existing project virtualenv:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_security_acceptance.py -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```

Results on `post-mvp`:

- Full test suite: `83 passed`
- Security acceptance suite: `12 passed`
- Ruff: passed
- Mypy: passed

Results on `mvp`:

- Full test suite: `83 passed`
- Security acceptance suite: `12 passed`
- Ruff: passed
- Mypy: passed

Warnings observed:

- FastAPI/Starlette test-client deprecation warnings only.
- No functional test failures.

## Recommended Next Steps

1. Keep `mvp` frozen

   Treat `mvp` as the frozen MVP branch/tag. Only cherry-pick critical fixes there.

2. Use `post-mvp` as active development

   Since `post-mvp` has better handoff docs and no behavior change, it is the right branch for
   ongoing work.

3. Confirm whether `post-mvp` is already merged to `main`

   Locally, `main` and `post-mvp` have no file differences. If remote PR state still shows them as
   separate, merge/close accordingly so the repository state is unambiguous.

4. Prioritize v0.2 before real connectors

   Do not connect real Gmail/Teams/company data until these are done:

   - Real authentication
   - Persistent audit/policies/approvals/connections
   - Encrypted token store
   - Dev/demo user switcher hidden behind an explicit flag

5. Reassess delegated access for "lower-sensitivity" systems

   Before production, decide whether Calendar, Jira, Drive, Sheets, HubSpot should require explicit
   scoped policies in the same way as Gmail/Teams, or at least have stricter per-system controls.

6. Complete approvals and transparency before wider internal rollout

   Approval requests should notify approvers, support grant/deny, create temporary scoped policies,
   and notify the target user when delegated data is accessed.

7. Add real-connector integration tests only after auth/token storage are ready

   Real connectors should be tested against sandbox accounts and must reuse the same connector guard
   invariants already proven by mocks.

8. When adding a real LLM, keep the stub as test default

   The stub should remain the deterministic unit/security-test backend. Add a separate test tier for
   LLM summarization quality, citations, privacy leakage, and prompt-injection behavior.

## Final Recommendation

The developer has built a solid MVP foundation. The project is ready for handoff and continued
development, but not ready for real employee data.

The correct next move is not more demo features. The correct next move is trust infrastructure:
real authentication, persistence, encrypted token storage, and completion of the approval and
transparency loop.

