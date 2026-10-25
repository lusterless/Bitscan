# TASK-085 IMPL: M3 carry-overs (upload.py Protocol seam, two README sentences)

Owner: impl-manager. Worktree `Bitscan-m4` (cut from `6fd593c`). REQ-112. Sources: `work/decisions.md` 2026-10-23 ("`services/inventory/upload.py` has no Protocol seam" and "All M3 tasks approved; README nits carried to M4"), `work/reviews/TASK-080.md` nits 2 and 3. TS §3.4 L239–L244.

## Files

- `manager/bitscan_manager/services/inventory/upload.py`
- `README.md`

No other file changed. `manager/openapi.json` is **byte-identical**: a fresh export compared equal with `cmp`.

## upload.py: the stores(tx) seam, no behaviour change

This follows the `services/scheduler/sweep.py` pattern:
- `UploadJobs` Protocol (`get_for_agent`, `complete`, `fail`, as `JobRepo` has them).
- Frozen `Stores(tx, jobs, inventory, agents, audit)`. The `inventory` and `agents` types reuse `ingest.py`'s `InventoryStore` and `AgentStore`; `audit` is `services.users.AuditSink` (`audit` and `alert`).
- `pg_stores(tx)` builds `JobRepo`, `InventoryRepo`, `AgentRepo` and `TxAudit(PgAuditRepo(tx.conn), tx.on_commit)`, the same objects as before.
- `StoresFactory = Callable[[Tx], Stores]`.

`classify`, `refuse_unread` and `store_upload` each take a trailing `stores: StoresFactory = pg_stores`, so the route (`api/agent/inventory.py`) and every caller are unchanged. `_audit` takes it explicitly. Each `db.transaction()` calls `stores(tx)` once, then uses only the store attributes. Every branch, condition, ordering, transaction boundary, audit detail and answer is as before:
- `classify`: no `job_id` gives unscheduled; a dispatched inventory job completes; a failed or completed job is unscheduled; anything else is audited and gets 409.
- `refuse_unread`: a job is failed only on 413 while it is dispatched.
- `store_upload`: 429 with `Retry-After` before decoding; a 413 or 422 decode refusal fails a `completes` job; `ingest` and `complete` share one transaction; `AgentGone` gives 401 `token_revoked`.

Diff size: about 50 hand-written lines changed or added.

## README: two sentences, under "Approving enrolments"

1. Approve, re-enrolment bullet: "A call with the old token then gets 401 `unauthorized`." This matches `test_enrolment_requests_api_pg.py` L511, `problem(beat(env, old), 401, "unauthorized")`.
2. A new bullet: "An operator who calls approve or reject gets 403 `totp_session_required` with an API token or a session not verified with TOTP, and 403 `forbidden` with a TOTP-verified session."
   - **This differs from REQ-112's wording** ("an operator calling approve gets 403 `totp_session_required`"), which is only true for some tokens.
   - `auth/dependencies._gate` checks the TOTP session before the role.
   - The M3 test (`test_enrolment_requests_api_pg.py` L704–L710) pins `env.token(op)`, whose harness default is a TOTP-verified session (`test_users_api_pg.Env.token`, `verified=True`), to 403 `forbidden`, and `env.token(op, "api")` to 403 `totp_session_required`.
   - REQ-112 AC (4) asks that the sentences match the behaviour, so the README states both. Reported to `main`.

## Checks run (from `Bitscan-m4/manager`, M3 venv)

- `ruff check`, `ruff format --check` and `mypy --strict` on `bitscan_manager` all pass (103 files).
- The OpenAPI export is byte-identical.
- No tests run (TP-M4-24 is the tester's; no WSL).

## For the tester (TP-M4-24)

- Fakes: pass `stores=lambda tx: Stores(tx, fake_jobs, fake_inventory, fake_agents, fake_audit)` and a fake `Database` whose `transaction()` yields an object with `conn` and `on_commit`. `ingest` needs only the fake stores, a `BurstWindow` and `on_commit`.
- The TASK-074 inventory route suites should pass unchanged (CHK-M4-366).
- The M4 tree's `manager/pyproject.toml` does **not** have the M3 gate fix `precision = 2`. I was asked to add it to M5 only; the lead's note says the M4 tree takes the M3 gate-fix commit before its gate.

## Revision 1 note (lead ruling 2026-10-25; text only)

- `README.md` line 3 now reads: "Bitscan is a manager + agent platform that inventories Ubuntu endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported hosts are Ubuntu 22.04 and Ubuntu 24.04 (amd64, cgroup v2)." Debian 12 and arm64 were dropped from v1 by the user's 2026-10-24 decisions.
- Nothing else changed. The M5 tree got the same line (TASK-128 r1), so both trees agree at merge.
- No re-run is needed for M4 (lead: text only).
