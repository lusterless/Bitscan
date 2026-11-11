# TP-M11-17 TEST: harness carries (REQ-291) — PASS

Tester: tester-m11e, 2026-11-08. Rows: `work/reports/M11-e2e-test.md`, section "TP-M11-17". Plan: `tests/m11/test-plan.md` CHK-M11-290 to -293.

## Verdict

**PASS.** `e2e/m6/manager_walk.py` runs green against the current `deploy/runbooks/manager-install.md`. Clean run r2 and run r3 on the final file (sha256 `b873035d…90a9`) each gave **72/76 PASS, 0 FAIL, 0 errors, 4 NOT RUN by design**. The `BITSCAN_BITS_DIR` set-up and its start check work, and the start check's plant turns exactly its two rows red and stops the walk with a clear message.

## What changed (test files only)

- `e2e/m6/manager_walk.py`: blocks are found by section and anchor, and a layout row stops the walk when a block is added, removed or changed. The plan covers all 36 blocks: 29 walked and 7 NOT RUN with reasons, recorded as 4 rows (the four rsyslog blocks share one row). The new runbook blocks are walked (§1, §1.1, §1.2, §5 token check and renewal timer, §10 sink check). REQ-291: `BITSCAN_BITS_DIR` is set in `manager.env`, and `bits_dir_check()` runs before §9. The run reports PASS, FAIL or NOT RUN per row and counts them. The secret sweep is row CHK-M11-293. New options: `--runbook`, `--name`, `--log`, `--publish`.
- `e2e/m6/doubles.py`: the OpenBao double now behaves as a token of the §1.2 role (allowed paths only, `renew-self`, 403 elsewhere). Existing callers (`e2e_vms.py`, `ops_walk.sh`) use only encrypt and decrypt on `bitscan-totp`, which are unchanged.

## Commands and counts

| Run | Command | Result |
| --- | --- | --- |
| r1 | `python3 -I e2e/m6/manager_walk.py --tree /root/m11e/tree --rel /root/m11e/rel --work /root/m11e/walk1 --name m11e-mgr --log … --keep` | 71/76 PASS, 1 FAIL (test bug: `grep -c` count 0 tripped the ERR trap), 4 NOT RUN |
| r1 fix re-run | the fixed row's command in the kept container | 1/1 PASS |
| r2 | same, `--work /root/m11e/walk2` | **72/76 PASS, 0 FAIL, 4 NOT RUN** |
| plant r1 | `--runbook` copy without §4's `uploaded/` line | CHK-M11-291 and -292 red as required, walk stopped. §6 also failed for an external pip reason: re-run |
| plant r2 | same, after the §6 evidence change | **48/54 PASS, 2 FAIL (exactly -291 and -292), 4 NOT RUN**, rc 1; no manager started |
| n1 (inside the nightly) | the walk with `--publish` | §6 FAIL: `ReadTimeoutError` from `files.pythonhosted.org` (proxy), 2 of 4 runs. Flaky, so fixed in the environment: the walk writes `/etc/pip.conf` (60 s, 10 retries); the block is unchanged |
| **r3 (final file)** | the walk inside nightly dev run n2, walk sha256 `b873035d…90a9` | **72/76 PASS, 0 FAIL, 4 NOT RUN** |

## Acceptance criteria (REQ-291)

| Criterion | Rows | Result |
| --- | --- | --- |
| (1) `manager_walk.py` runs green against the current runbook | CHK-M11-290 r2 and r3 (M11-e2e-test.md) | PASS |
| Every test manager has `BITSCAN_BITS_DIR` and `uploaded/` with the runbook's owners and modes before serve | CHK-M11-291 (r2; the nightly reuses the walk) | PASS |
| (2) The start check stops with a clear message when the folder is missing | CHK-M11-292 r2 and its plant r2 | PASS |
| No secret in rows, logs or journal | CHK-M11-293 | PASS (0 hits) |

## Notes

- **Known gap (lead: leave as is).** G41's `serve` from the tree (`manager/tests/test_serve_linux.py::env_for`, tester-m11's file) neither creates nor checks `BITSCAN_BITS_DIR`. REQ-291 is met because every M11 test manager is installed by the walk, with the start check.
- **`deploy/tests/check_manager_host.sh`** (lead, 2026-11-08: update it; it is still used by `e2e_vms.py` and `plant_host.sh`). Its `manager.env` row now accepts the three required settings plus only the runbook's optional `BITSCAN_LISTEN` and `BITSCAN_BITS_DIR`, and fails on any other key, a key given twice, or a missing required one. On a walked host: **19/19 PASS**. Control (`BITSCAN_LISTEN` added): PASS. Plants: unknown key, required key removed, key twice: each **FAIL**, rc 1. Rows in `M11-e2e-test.md`.
- **Environment:** WSL ends the distro once no `wsl.exe` client is attached, which stops kept containers. Long runs are single invocations.
