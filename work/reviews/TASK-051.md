# TASK-051 REVIEW: agent repository

Reviewer: reviewer. Date: 2026-10-23. REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082. Spec: TS §5.2 L710–L746 (`agent`, `agent_ip_seen`, `agent_tag`) and L994–L1013 (grants: UPDATE on `agent` and `agent_ip_seen`, DELETE on `agent_tag`, no DELETE on `agent`), §3.2 L183–L191, §3.3 L218–L220 (status thresholds, decommission); #25, #59, #62, #64, #65 (c), #68, #73. Rulings: `work/decisions.md` 2026-10-23 rows "M3 W1 rulings" (4) (age base GREATEST, user) and "TASK-051 revision 1" (`online` needs a fresh heartbeat, lead; the as-built `last_heartbeat_at >= base` form accepted). Inputs:
- `work/reports/TASK-051-impl.md`, including "Revision 1";
- `work/reports/TASK-051-test.md` (PASS: 53 tests in WSL, 16 of 16 plants red);
- the revision 1 re-test PASS (CHK-M3-054-age-r1: 55 passed in WSL, 17 of 18 plants red; the survivor is an equivalent mutant).

Files reviewed:
- `manager/bitscan_manager/repositories/agents.py` (new, about 330 lines, 280 code);
- the tester's `manager/tests/test_agent_repo_pg.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. Its consumers TASK-059, 063, 070, 072 and 075 are on it. Size (280 code lines against a 190 estimate) is accepted by the lead as one cohesive repository.

## What was checked

- **Spec conformance.**
  - Lookups by token hash, previous hash, machine-id and id; an unknown value returns None.
  - `insert` uses `ON CONFLICT (machine_id) DO NOTHING`, so a duplicate machine-id takes the re-enrolment branch in the same transaction.
  - `revoke` keeps the first `token_revoked_at`, and that ends the current and the previous token.
  - Rotation (#62): `rotate` sets `prev_token_hash` and `last_rotation_at`. `replace_unused_token` applies only while the new token is unused. `mark_new_token_used` is atomic, so exactly one caller gets True.
  - `relink` follows #64 (a)–(c).
  - `record_heartbeat` makes `enrolled`, `stale` and `offline` agents `online` at once (#73 (a)).
  - `record_ip` upserts `agent_ip_seen` and keeps `first_seen_at` (#25 (b)).
  - Keyset paging uses `(hostname, agent_id)`. `AgentListRow` holds no hash.
- **Sweep (rulings).**
  - The age is `now − GREATEST(last_heartbeat_at, enrol_base)`, with `enrol_base = GREATEST(enrolled_at, latest approved decided_at)`.
  - `offline` above 30 min and `stale` from 10 min, so the REQ-078 (1) boundaries hold at 9m59s, 10m, 29m59s, 30m and 30m1s.
  - After revision 1, `online` also needs `last_heartbeat_at >= enrol_base`, a heartbeat since the enrolment or approval. Below 10 min of age that heartbeat is the age base itself, so it is under 10 min old (TS §3.3 L218).
  - Otherwise the agent is `enrolled`. That branch is reachable only within 10 min of an enrolment or approval, so it cannot demote a working agent.
  - Decommission (`offline` and age over N days) and stale inventory use the same base. A re-linked agent with a 10-day-old heartbeat therefore stays `enrolled`, keeps its approved token, and is decommissioned only N days after its approval. The new tests pin all of this.
  - `awaiting_approval` and `decommissioned` are never touched. The enrolment base is one grouped scan of `enrollment_request`, not a per-agent subquery (no `agent_id` index may be added).
- **Security invariants.**
  - Only hashes reach this module, and `AgentRow` keeps both hash fields out of `repr`.
  - No DELETE on `agent`.
  - Every statement is parameterised. `psycopg.sql` composes constants and identifiers only, and ruff S608 is clean.
- **Tests (my run, Windows).** ruff and format are clean on both files, and `mypy --strict` is clean on the whole tree (148 files). The PostgreSQL cases ran in WSL (tester). The three revision tests cover:
  - the approved re-enrolment ageing from the approval;
  - a re-linked agent going `online` only after a new heartbeat;
  - a heartbeat made before the approval not counting.

## Findings

None.

## Carry-overs (for the consuming tasks)

- **TASK-065.** Do not call `decommission_offline` when `decommission_after_days` is 0 ("never"). Pass `timedelta(days=N)` otherwise. Write one `agent.decommission` audit entry per returned id (#73 (d)).
- **TASK-063 / TASK-075.** Call `ip_last_seen` before `record_ip`, for the 7-day rotation rule.
