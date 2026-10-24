# TASK-051 IMPL report: agent repository

REQ: REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082. Spec: TS §5.2 L710–L746 (`agent`, `agent_ip_seen`, `agent_tag`) and L994–L1013 (grants), §3.2 L183–L191, §3.3 L218–L220; #25, #59, #62, #64, #65 (c), #68, #73. Plans: `work/plans/TASK-059.md` (token states, rotation), `TASK-061.md` (sweep), `TASK-067.md` (enrol, relink).

## Files (1)

- `manager/bitscan_manager/repositories/agents.py`: new, about 330 lines (280 code). Over the 190 estimate; a ruling was asked of the lead.

## Rows

- `AgentRow`: every `agent` column, in DDL order. `status` is read as text and `last_seen_ip` through `host()`. The two hash fields are left out of `repr`.
- `AgentListRow`: the #68 `GET /agents` item. It adds `os_id`, `os_version_id` and `os_pretty_name` from a LEFT JOIN on `os_info`, and `tags`, sorted.

## Functions (`AgentRepo(conn)`, inside the caller's transaction; only token hashes, never tokens)

**Lookups:**
- `find_by_token_hash(hash)`, `find_by_prev_hash(hash)`: an unknown hash returns None.
- `find_by_machine_id(machine_id, *, lock=False)`, `get(agent_id, *, lock=False)`: `lock` selects `FOR UPDATE`.

**Insert:**
- `insert(*, machine_id, hostname, agent_version, token_hash, issued_at, expires_at, status, now) -> UUID | None`. Uses `ON CONFLICT (machine_id) DO NOTHING`. It returns None when the machine-id already has a row, so TASK-067 can take the re-enrolment branch in the same transaction. `enrolled_at` = `now` (the Clock). `last_seen_ip` is left to `record_ip`, the one writer (#25 (b)).

**Status and token updates:**
- `set_status(agent_id, status, only_from) -> bool`: changes the row only while its status is one of `only_from`.
- `revoke(agent_id, now)`: `token_revoked_at = COALESCE(token_revoked_at, now)`. This ends the current token and any previous one, because the check reads the row's `token_revoked_at` for both.
- Rotation (TASK-075, #62):
  - `rotate(agent_id, new_hash, issued_at, expires_at)`: old hash → `prev_token_hash`, `prev_token_expires_at = NULL`, and `last_rotation_at = issued_at`.
  - `replace_unused_token(agent_id, new_hash, issued_at, expires_at)`: the lost-response retry. It applies only while `prev_token_hash` is set and `prev_token_expires_at IS NULL`.
  - `mark_new_token_used(agent_id, overlap_until) -> bool`: an atomic first use. It is True for exactly one caller, and sets `prev_token_expires_at`.
- `relink(agent_id, *, token_hash, issued_at, expires_at, hostname, agent_version)`: an approved re-enrolment (#64 (a)–(c)). It takes the request's token and clears `token_revoked_at`, `prev_*` and `last_rotation_at`. Status becomes `enrolled`.

**Heartbeat, inventory and IP:**
- `record_heartbeat(agent_id, now, agent_version, helpers)`: sets `last_heartbeat_at`, `agent_version` and `runner_helpers` (JSONB). Status becomes `online` from `enrolled`, `stale` or `offline` (#73 (a)); other statuses are unchanged.
- `set_last_inventory(agent_id, now)`: for TASK-064, whose file list has no agent repository.
- `ip_last_seen(agent_id, ip) -> datetime | None`, and `record_ip(agent_id, ip, now)`:
  - `ip_last_seen` returns the previous `last_seen_at` for the 7-day rotation rule; call it before `record_ip`.
  - `record_ip` upserts `agent_ip_seen`, keeping `first_seen_at` and moving `last_seen_at`, and sets `agent.last_seen_ip`.

**Tags:**
- `tags(agent_id)`.
- `replace_tags(agent_id, tags)`: a DELETE then an INSERT through `unnest`, all or nothing within the caller's transaction. Tags must be distinct; the service validates them (#68).

**Lists and counts:**
- `list_page(limit, after: (hostname, agent_id) | None)`: keyset paging in `(hostname, agent_id)` order (#68).
- `count_by_status() -> Counter[str]`: for TASK-068 (offline share) and TASK-079 (the gauge).

**Sweep:**
- `apply_heartbeat_ages(now, stale_after, offline_after) -> int`: one `UPDATE … SET status = CASE …` over `enrolled`, `online`, `stale`, `offline` only.
  - `offline` if age > `offline_after`; `stale` if age ≥ `stale_after`; otherwise `online`, but only for an agent that has heartbeat. An `enrolled` agent that never heartbeat stays `enrolled` until it ages into `stale` (plan TASK-061).
  - Only changed rows are written. Because it is one UPDATE, a heartbeat committed meanwhile is re-read before the row changes.
  - `awaiting_approval` and `decommissioned` are never touched.
- `decommission_offline(now, after) -> list[UUID]`: `offline` agents with age > `after` become `decommissioned` with `token_revoked_at` set. It returns their ids, for one audit entry each (#73 (d)).
- `stale_inventory(now, older_than) -> list[UUID]`: `online` agents where `now − COALESCE(last_inventory_at, enrolment base)` exceeds `older_than` (#65 (c)).

**Performance:** the enrolment base comes from one derived table, `b`. It holds one grouped scan of `enrollment_request` (`max(decided_at)` of approved requests per agent) LEFT JOINed to `agent`, and is joined once into each sweep statement. A correlated subquery would have scanned `enrollment_request` once per agent, because the table has no `agent_id` index and none may be added: about 10^8 row reads per sweep at 10,000 agents. `a.last_heartbeat_at` is read from the row being updated, so a heartbeat committed meanwhile is the value used.

**Age base (ruling asked of the lead):**
- `GREATEST(last_heartbeat_at, enrolment base)`, where the enrolment base is `GREATEST(enrolled_at, latest approved decided_at)`.
- This equals #25 (c) for every agent that never heartbeat (`enrolled_at` if auto-approved, else the approval time), and equals `last_heartbeat_at` for normal agents.
- It differs from a literal `COALESCE` in one case: an approved re-enrolment then ages from its approval, rather than from a heartbeat that may be days old, so the next sweep does not decommission it and revoke its new token.
- It is one constant (`_AGE_BASE`).

**Grants:**
- UPDATE on `agent` and `agent_ip_seen`, DELETE on `agent_tag`: all granted by TS §5.2.
- `INSERT … ON CONFLICT DO UPDATE` on `agent_ip_seen` uses that table's UPDATE grant.
- No DELETE on `agent`.
- Every statement is parameterised; `psycopg.sql` composition uses constants and identifiers only (ruff S608 passes).

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass. `mypy --strict`: pass for `bitscan_manager`.
- `pytest -q`: 1198 passed, 451 skipped (the 2 expected TASK-056 failures aside).
- PostgreSQL: **NOT RUN locally** (Docker unavailable); the SQL has been reviewed but never executed. TP-M3-05 in WSL is the first run.

## For the tester

- `apply_heartbeat_ages` and `decommission_offline` take `timedelta` bounds, which the caller passes: 10 min and 30 min, and `decommission_after_days` days. Boundaries as REQ-078 (1): `online` below 10 min, `stale` from 10 min through 30 min inclusive, `offline` above 30 min.
- `list_page` and the other selects never return `token_hash` or `prev_token_hash` in `AgentListRow`. `AgentRow` has them, for the token check only.

## Deviations

None, pending the age-base ruling.

## Revision 1 (lead ruling 2026-10-23, TS §3.3 L218; tester finding CHK-M3-054-age)

- **Finding:** an approved, re-linked agent whose `last_heartbeat_at` was 10 days old became `online` at the next sweep, without a new heartbeat. The status CASE gave `online` whenever the GREATEST age was under 10 min and `last_heartbeat_at` was not null.
- **Fix:** `_TARGET` in `bm/repositories/agents.py` only, which is used by the sweep's status statement.
  - The GREATEST age still decides `offline` (above `offline_after`) and `stale` (from `stale_after`), and still drives decommission and stale inventory, unchanged.
  - **`online`** now needs `a.last_heartbeat_at >= b.enrol_base`, meaning a heartbeat since the enrolment or approval. Below `stale_after` such a heartbeat is the age base itself, so it is also under 10 min old, as TS §3.3 L218 requires.
  - Otherwise the agent is **`enrolled`**: it has no heartbeat since its enrolment or approval, like an agent that never heartbeat. This covers a heartbeat made before the approval (the tester's third case), not only an old one.
- `relink` is unchanged and keeps `last_heartbeat_at`. `record_heartbeat` still sets `online` at once (#73 (a)).
- **Gates (Windows):** ruff, ruff format and `mypy --strict` pass (143 files). The PostgreSQL run is the tester's. The three new tests (`test_approved_reenrolment_ages_from_the_approval`, `test_relinked_agent_goes_online_after_a_heartbeat`, `test_heartbeat_before_the_approval_does_not_make_online`) are expected to pass now.
