# M3 GATE REVIEW: agent API, enrolment and inventory scheduler (closing check)

Reviewer: reviewer (fresh instance). Date: 2026-10-24. Scope: TASK-048 to TASK-084, REQ-060 to REQ-090 (`work/tasks.md` "M3 gate": G1 to G6, G16, G18, G25 to G34, and the security mutation table CHK-M3-320 to -374).

Inputs:
- every `work/reviews/TASK-0{48..84}.md`;
- `work/decisions.md` (the 2026-10-23 and 2026-10-24 rows);
- `tests/m3/report.md` (the gate rows and "M3 closing");
- `work/reports/M3-gate-g5-fix-impl.md`;
- the working-tree diff against `6fd593c`.

Verdict: APPROVED (M3 exit gate). Two points need the user before the PR is opened (§6).

## 1. Task reviews

All 37 M3 reviews are APPROVED: TASK-048 to TASK-084, including the follow-ups TASK-082, TASK-083 and TASK-084. Several needed further rounds or revisions, and each was re-tested and re-reviewed:
- TASK-048: r1 rounds 2 and 3, then r2 (the 2^53 − 1 bound).
- TASK-053: round 2.
- TASK-059 r1: the 30-day cap on the old token.
- TASK-064 r1: the alert window is marked only on commit.
- TASK-066 r1: an IPv6 zone is refused, with one revoke entry.
- TASK-067 r1: peer zone ids are dropped.
- TASK-070 r1: deciding a `new` request after its re-enrolment twin.
- TASK-071 r1: SIGTERM stays bounded with the database down.
- TASK-075 r1 and r2: rotation order and the concurrent same-token rotate.
- TASK-078 r1: `detail_text`.
- TASK-080 r1 and r2: README.

**No should-fix is open in any M3 review.**

Second approval from the user (TS §8.2) is recorded for every two-approval task: TASK-048 (r1 and r2), 050, 059, 063, 066, 067 (with the two M2 auth-file changes of r1), 070, 072, 073, 074, 075 (r1 and r2), 077, 082 and 083. TASK-084 is not on the list: it changes no agent-route behaviour (ruling 2026-10-23).

## 2. Changes since the task approvals (working tree against `6fd593c`)

| File | Change | Checked |
| --- | --- | --- |
| `manager/pyproject.toml` | `precision = 2` under `[tool.coverage.report]` | Correct. Without it, pytest-cov rounded 84.80 % up to 85 and passed, so the gate was really 84.5 %. pytest-cov 7.1.0 takes `precision` from the coverage config when `--cov-precision` is absent, so CI (`--cov-fail-under=85`) uses it too. This restores `testing.md`'s "at least 85 %" and lowers nothing. |
| `manager/tests/test_serve_linux.py` | The sign-in limit test starts in a fresh calendar minute. The sink-down test reads the queue's complete lines read-only instead of opening a `DiskQueue` on a folder that `serve` owns. | Race fixes only; no assertion is weaker. |
| `manager/tests/test_readme_walk_linux.py` | The D-agent 30-per-minute step starts in a fresh minute. | Race fix only. |
| `manager/tests/test_serve_scheduler_linux.py` | A `SchedulerStopping` failure is allowed only for runs that were in progress at SIGTERM, and no more such failures than those runs. | Matches the TASK-071 r1 ruling and the G27 test. A KeyError plant turns it red (CHK-M3-312-r3). |
| `.gitignore` | `.claude/hooks/` ignored. | No product effect. |
| `.claude/CLAUDE.md` | The user's edit of "Supported hosts". | See §6 (2). |

`manager/bitscan_manager/` and `web/src/` have no change since `6fd593c`.

## 3. Decisions applied or carried over

Each per-task review checked the M3 decision rows against the code. At the gate I re-checked the cross-cutting ones:

| Decision | Status |
| --- | --- |
| Agent contract: nullable keys required, NUL refused except results output, hyphenated UUIDs, 2^53 − 1 counters, recursive `RawValue` with plain `$ref` | TASK-048 r1 r3 and r2; G30 red on its plants |
| Token check before body parsing on every agent and limited route (limit-first route class) | TASK-082, TASK-083; CHK-M3-385, -381 |
| Old token capped at `last_rotation_at` + 30 days; rotation order (24 h before window); lost-response retry; concurrent same-token rotate | TASK-059 r1, TASK-075 r1 and r2 |
| Threshold windows built once in `create_app()` and marked only on commit | TASK-063, 064 r1, 067, 068 |
| Peer zone dropped (`peer.py`), shared by agent and M2 user routes | TASK-067 r1 |
| SIGTERM bounded with the database down; no production cadence knob | TASK-071 r1; G27 |
| Inventory 422 documented; no `HTTPValidationError` anywhere | TASK-074; G6 |
| Audit-log `detail_text` | TASK-078 r1 |
| #70: metrics at `GET /api/v1/metrics`, minimum role viewer; `HealthPath` unchanged | TASK-079, TASK-081 (`/metrics` absent) |
| Import cycle fixed; every module imports alone | TASK-084; CHK-M3-319 |
| G5 measured on Linux (speed rule 2), not lowered; precision fix | CHK-M3-310-gate-r2 |

**M2 carry-overs closed in M3:**
- body caps on the templated agent routes (`RouteCap`, TASK-073 and TASK-074);
- the metrics route (#70 moved it under `/api/v1`, so `HealthPath` needs no change);
- the clock-skew alert (TASK-072). It detects only; see §6 (1).

**Carried to later milestones (not M3 defects):**
- M4:
  - the `upload.py` Protocol seam (TASK-085);
  - two README nits: the old token's 401 after an approved re-enrolment, and the operator's 403 on approve;
  - the 64-bit counters sent within 2^53 − 1 by the Go agent.
- M5: whether `AgentItem.status` becomes the six-value enum in the contract.
- M9: the NUL and lone-surrogate rule for results `stdout` and `stderr`.
- Later touch: the unused `revoke_token` in `repositories/enrolment.py` (TASK-066 nit).
- **Load test:** the TASK-064 snapshot lookup, which has no `agent_id` index, and the TASK-060 64 MiB `bytes(out)` copy were to be measured in the M6 load test (decisions 2026-10-23, W3 ruling (3)). The user has since deferred load and soak tests until after M6 (2026-10-24). These two checks move with them, so M6 ships without measuring them.

## 4. Accepted residual risks (unchanged unless noted)

1. **`db maintain` clock skew** (decisions 2026-10-20, gap check). A forward skew smaller than the partition window plus one month can drop partitions inside retention, up to about 5 months early. TASK-072 now alerts on a skew over 5 minutes between each agent's `clock` and `server_time`. A fast manager clock therefore alerts at every agent's first heartbeat, within about 5 minutes. That is detection only; nothing stops `db maintain`. **Still open for the user** (§6 (1)).
2. **The old token after an unused rotation:** up to 30 days past its real expiry (user, 2026-10-23); documented in the README.
3. **Concurrent rotate waiting on a used rotation** answers 429 and does not count as reuse (TASK-075 r2 boundary, lead).
4. The M2 residuals stand as listed in `M2-gate.md` §3: the psycopg DEBUG line, the syslog sink having no receipt, the vault token lifecycle, and the smaller limits.

## 5. Gate results

The tester's rows are in `tests/m3/report.md`. Each gate is green on the clean tree and red on its planted violation:

| Gate | Row | Clean | Plant → red |
| --- | --- | --- | --- |
| G1–G3 ruff, format, mypy | CHK-M3-306/307/308-gate | 215 files clean | S608, TID251, misformat, untyped function |
| G4 hashed locks | CHK-M3-309-gate | both locks install (dev lock with pytest-xdist) | all 78 hypothesis hashes; both pytest-xdist hashes |
| G5 coverage | CHK-M3-310-gate-r2 | 99.52 % (Linux) | 84.80 % and 83.99 % plants exit 1 after the precision fix (r1 shows the gap it closed) |
| G6 OpenAPI | CHK-M3-304-* per task; reviewer re-export | byte-identical (my export today; sha256 `4a02bb08…`) | per-task plants |
| G16 client | CHK-M3-298 | generated from `openapi.json` `4a02bb08…`, which is the file today; `web/src/api/` unchanged | a changed document without regeneration |
| G18 full suite | CHK-M3-312-gate, -r1 to -r3 | 3959/3959, 0 skipped (hg5c control); `bstester` 48/48 | the G25–G34 plants |
| G25 | CHK-M3-313-gate | 42/42 | CHK-M3-323 |
| G26 | CHK-M3-314-gate | 35/35 | 15-minute check; ack before sink |
| G27 | CHK-M3-315-gate | 45/45 (bstester 48/48) | pool closed before the scheduler stops |
| G28 canary | CHK-M3-302-gate | 2/2 | header, agent body and stdout logged |
| G29 telemetry | CHK-M3-316-gate | 3/3 | `telemetry=` removed |
| G30 contract | CHK-M3-010-019-gate | 569/569 | 4 of 4 |
| G31 agent security | CHK-M3-320-374-gate, CHK-M3-320-321-341-gate | controls green | every G31 row red (320, 321 and 341 re-planted after the `dependencies.py` change) |
| G32 fuzz and decode | CHK-M3-130-139-gate | 129/129 | 4 of 4 |
| G33 sweep and queue | CHK-M3-G33-gate | 54/54 | 5 of 5 |
| G34 invariants | CHK-M3-300/305-gate | 32/32 | 8 of 8 (ad-hoc run routes, `inventory_enabled`, network clients) |

The security mutation table CHK-M3-320 to -374 is red in full. A row was re-planted when its target changed after its last red. The other rows cite their earlier red row, as the 2026-10-23 targeted-run rule allows.

**My own checks on the final tree (Windows):**
- ruff, format and `mypy --strict` are clean (215 files);
- the G6 export is byte-identical;
- `test_module_imports.py` passed 96/97. One subprocess hit the 120 s timeout under load; it is not evidence, and the Linux run is 97/97.

**Not run locally, left to CI on the PR:**
- the `git diff --exit-code` forms of G6 and G16;
- G8 to G10 on Linux runners (the M3 agent tree is the M0 stub);
- G17 with built binaries;
- G18 and G25 to G28 on GitHub runners.

## 6. For the user before the M3 PR is opened

1. **The `db maintain` clock-skew residual** (decisions 2026-10-23: "Still open, for the M3 gate"). Should the TASK-072 alert (detection within about 5 minutes of a fast manager clock, through every agent's heartbeat) close the accepted residual? Or should `db maintain` also refuse drops while a `clock_skew` alert is active? The second option would need a new task.
2. **`.claude/CLAUDE.md` "Supported hosts"** now says "Ubuntu 22.04, Ubuntu 24.04 and Debian 12, on amd64". Debian 12 was dropped on 2026-10-24, so the line still disagrees with decisions.md. The edit also removed "with cgroup v2". The cgroup v2 requirement still stands in TS §3 (the runner refuses to start without it), so restore that phrase unless that was the intent.
3. **CI must be fully green before merge** (checks are advisory on this plan, decisions 2026-10-21). That covers especially G6 and G16 in their `git diff` form, G17, and G18 and G25 to G28 on runners, none of which has run on the committed M3 head yet.
4. **Load-test deferral side effect:** the two M3 cost checks named in §3 now wait for the post-M6 load test.
