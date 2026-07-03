# Testing Guide

How to verify this project — automated gates, the manual smoke procedure, and per-branch
policy. The security model is only as good as these checks; treat them as the product.

## Automated checks (run before every commit; identical on every branch)

```bash
source .venv/bin/activate
ruff check src tests                             # lint / style
mypy src                                         # strict type-check
pytest -q                                        # full suite
pytest tests/test_security_acceptance.py -q      # the 12 named Phase-6 security tests
```

All four must be green. The acceptance file is the **release blocker** — it maps the twelve
required security behaviors one-to-one:

| Test | Asserts |
|---|---|
| `test_p6_01` | Cannot read another user's Gmail without permission |
| `test_p6_02` | Scoped Gmail read allowed with a valid policy |
| `test_p6_03` | Teams read outside allowed scope denied |
| `test_p6_04` | Teams project context readable when permitted |
| `test_p6_05` | A write executes only as `active_user` |
| `test_p6_06` | A write is never executed as `target_user` (engine + connector layers) |
| `test_p6_07` | Audit events created for sensitive reads |
| `test_p6_08` | Audit events created for writes (`actor_for_write_action`) |
| `test_p6_09` | Permission denial returns a safe response (no data leakage) |
| `test_p6_10` | Ambiguous/missing permission triggers the approval flow |
| `test_p6_11` | Connectors are unreachable without permission validation |
| `test_p6_12` | Summaries never expose raw sensitive content (sentinel strings) |

### Test-design rules
- **Inject clocks.** The seeded scenario is date-anchored (Anna OOO 2026-07-01..07-10,
  policies expire 2026-07-20). Always pass `clock=lambda: date(2026, 7, 3)` (inside OOO) or
  `date(2026, 7, 15)` (back in office) — never rely on the real date.
- **Assert invariants, not wording.** Check `allowed` flags, exception types, audit fields,
  and sentinel absence — not exact summary strings, which may change.
- **Sentinels:** mock data plants `SENTINEL_FULL_BODY_DO_NOT_LEAK` and `555-0100` inside the
  full email body. If either ever appears in a response, a privacy regression happened.

## Manual smoke procedure (~5 min; required before any merge to `main`)

```bash
uvicorn assistant.api.app:app --reload   # open http://127.0.0.1:8000
```

| # | As | Do | Expect |
|---|----|----|--------|
| 1 | mark | Search email: Anna / ClientCo / API Integration | Results + source links; **no raw body**; access reason shown |
| 2 | lucy | Same search | **Blocked**, approval request id shown; request visible in `/admin` as pending |
| 3 | mark | Create Jira task **without** the confirm checkbox | Blocked with "requires explicit confirmation"; **no** write audit event in `/admin` |
| 4 | mark | Create Jira task **with** checkbox | "as mark" in actions; write audit event appears |
| 5 | anna | `/connections`: toggle Jira on, then off | Table reflects both changes |
| 6 | mark | Flagship flow (Anna / ClientCo / API Integration) | Combined Gmail+Teams summary, Jira action taken, ≥3 audit events, note "all writes as active_user" |

Any deviation = stop the release and file the regression.

## Per-branch policy

| Branch | What runs | Notes |
|---|---|---|
| `main` | Full automated checks + manual smoke before each tag | Never receives direct commits |
| `mvp` | Full automated checks | Frozen; only cherry-picked critical fixes (tag `v0.1.x-mvp`) |
| `post-mvp` | Full automated checks on every commit | Feature work; keep the suite green at all times, not just at release |

## Future: integration test tier (when real connectors land, v0.3+)

- Mark real-API tests `@pytest.mark.integration`; excluded by default
  (`pytest -m "not integration"` stays the fast, deterministic default).
- Run the integration tier manually or nightly with real sandbox credentials from the
  environment — never committed.
- Every real connector must pass the same guard tests as its mock (shared test parametrized
  over implementations), proving no real connector weakens the permission boundary.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs `ruff + mypy + pytest` (Python 3.12) on
every push and PR to `main`, `mvp`, and `post-mvp`. The job is named **`checks`**.

**Branch protection on `main`:** not currently enforced server-side — GitHub requires the
Pro plan for branch protection on private repositories (the API returns 403 on Free). Until
the repo is upgraded (or made public), protection of `main` is **by convention**: never
commit to `main` directly; merge from `post-mvp` only after its CI run is green. If the plan
is upgraded, enable it with:

```bash
gh api -X PUT repos/SylwesterKwiatkowski/ai-continuity-assistant/branches/main/protection \
  --input - <<'EOF'
{"required_status_checks":{"strict":false,"contexts":["checks"]},
 "enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null,
 "allow_force_pushes":false,"allow_deletions":false}
EOF
```
