# TASK-068 IMPL report: fleet threshold alerts

REQ: REQ-079. Spec: TS §8.4 L1291, §3.4 L242, §5.3 L1047; #44, #65 (b), (c), (g), #66, #71. Plan: `work/plans/TASK-061.md`, step 5. It depends on TASK-056 and TASK-065, both approved.

Carry-overs applied:
- commit-only "fired" marking for every window (decisions 2026-10-23);
- windows built once per process;
- the re-arming offline-share window (#65 (b));
- queue age counts only the queued jobs of online agents (#66).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/scheduler/fleet_alerts.py` | new, 165 lines |
| `manager/bitscan_manager/services/audit/thresholds.py` (TASK-056) | `OncePerPeriod.due/mark` and `ReArm.due/mark` added |
| `manager/bitscan_manager/repositories/jobs.py` (TASK-054) | `default_partition_has_rows()` added |

**Outside the task's file list: the second and third rows.** I needed them:
- The commit-only rule needs a check that does not mark at the same time. `fire()`, `update()` and `sync()` keep their approved behaviour; the existing `tests/test_thresholds.py` gives 19 passed.
- SQL belongs in a repository (layering rule), and no repository had the default-partition check. `SELECT EXISTS (SELECT 1 FROM scan_result_default)` works because `bitscan_app` has SELECT on every table.

## API

`FleetAlerts(clock)` is built **once per process** by the scheduler (TASK-071). It holds four windows:
- offline share: `ReArm`;
- queue age: `OncePerPeriod` (1 h);
- stale inventory: per-agent `ReArm`;
- default partition: `ReArm`.

`.run(db, now, stores=pg_fleet_stores) -> list[str]` returns the names of the checks that failed.

**Each check runs in its own transaction.** It reads, and writes its alert entry or entries with `raise_alert`, where the counter rises on commit. Only **after** the `with db.transaction()` block exits cleanly is the window marked. A rolled-back or failed alert therefore leaves the window free, and it fires on the next run. A failing check is logged as `fleet alert check failed` with `{"check", "exc_type"}` only, and the other checks still run.

## Checks

All entries have actor `system`, action `alert.<kind>` and `detail.alert = true` (#71). No detail holds a hostname or a token.

| Kind | Rule | Repeat |
| --- | --- | --- |
| `agents_offline` | `offline / eligible > 5 %`, where eligible means every status except `decommissioned` and `awaiting_approval`; uses `AgentRepo.count_by_status()` | again only after the share was at or below 5 % (#65 (b)); target `fleet`; detail `{offline, eligible, over_share}` |
| `job_queue_age` | `now − JobRepo.oldest_queued_for_online() > 1 h`; that is the oldest queued job of an **online** agent (#66); exactly 1 h is not an alert | at most once per hour; detail `{oldest_age_s}` |
| `inventory_stale` | `AgentRepo.stale_inventory(now, 2 × inventory_interval_s)`: online agents whose `last_inventory_at`, or their enrolment base if they never uploaded, is **more than** twice the interval old. The interval is read from settings on each run | one entry per agent, `target agent:<id>`, then not again until that agent leaves the stale set (its next upload) (#65 (c)); detail `{older_than_s}` |
| `default_partition_rows` | `JobRepo.default_partition_has_rows()` | once when rows appear, again only after the partition was empty (#65 (g)); target `scan_result_default` |

## Local gates (Windows)

- ruff and ruff format: pass.
- `mypy --strict`: clean for `bitscan_manager`. The only error is in tester-b's in-progress `tests/test_enrolment_tokens_api_pg.py:226`.
- `pytest -q`: 2158 passed, 827 skipped, 0 failed.
- Scratch probe with a fake database and fake stores:

| Step | Result |
| --- | --- |
| 5 of 100 eligible offline (59 ineligible ignored) | no alert |
| 6 of 100 offline | alert |
| still 6 | none |
| back to 5 | none (re-armed) |
| 6 again | alert |
| queue age exactly 1 h | none |
| queue age 1 h + 1 s | alert |
| same hour | none |
| an hour later | alert |
| two stale agents | two entries; bound passed as 12 h for the 21,600 s interval |
| one uploads | nothing |
| it goes stale again | one entry |
| partition rows with a failing commit | not marked |
| next run | alert |
| still rows | none |
| emptied, then rows again | alert |

- PostgreSQL (TP-M3-22, including a row planted as owner in `scan_result_default`): **NOT RUN locally**; WSL.

## For tester-b

- The window marking is commit-only. To show a rolled-back alert fires again, make one check's transaction raise, then run again.
- When TASK-071 wires `FleetAlerts`, it builds the object once and calls `.run()` after `run_sweep()`.

## Deviations

The two small additions outside the file list, explained above.

## Touched approved files (lead OK, work/decisions.md 2026-10-23)

| Approved file | Owning task | Change |
| --- | --- | --- |
| `manager/bitscan_manager/services/audit/thresholds.py` | TASK-056 | `OncePerPeriod.due()` and `.mark()`; `ReArm.due()` and `.mark()`. `fire()`, `update()` and `sync()` are unchanged in behaviour. |
| `manager/bitscan_manager/repositories/jobs.py` | TASK-054 | `JobRepo.default_partition_has_rows()`, a read-only `SELECT EXISTS (SELECT 1 FROM scan_result_default)` |

The reviewer should read both changes. tester-b should re-run the TASK-056 suite (`tests/test_thresholds.py`) and the TASK-054 suite (`tests/test_jobs_repo_pg.py`, WSL) along with this task's tests. Locally, `tests/test_thresholds.py` gives 19 passed.
