# TASK-252 TEST (with the TASK-253 and TASK-259 docs walks, TP-M11-16, TP-M11-21): PASS

Tester: tester-m11d, 2026-11-09. Low risk (docs). One walk covers all three docs tasks:
- **TASK-252:** `README.md`, including r1's nightly section.
- **TASK-253:** `deploy/runbooks/manager-operations.md` §1, §6, §7 and `deploy/debian/changelog` `0.2.0~pre2-1`.
- **TASK-259:** `deploy/runbooks/agent-install.md` L7 and L178.

TASK-253 and TASK-259 have short verdict files (`work/reports/TASK-253-test.md`, `TASK-259-test.md`) that point here.

- **Scope:** REQ-289 (1)–(3), REQ-290 (1), (2); PD-51 for the README walk checks (REQ-233 superseded by REQ-289); TS §4.5 L603–L604, §5.3 L1049–L1053, §6.2 L1113, L1120–L1125, §8.3 L1283.
- **Docs under test:** README.md (+114/−10, r1), manager-operations.md (+83/−5), changelog (+16), agent-install.md (+2/−2), as in the tree on 2026-11-09. `e2e.yml` is at `9d4f1a7`.

## How the walk was done

- **Static checks**, in WSL on a copy of the tree (`m11t-scripts/tmp/docs_static.sh`): `check_runbook_text.py`, `check_debian_meta.py`, `dpkg-parsechangelog`, `dpkg --compare-versions`, and greps.
- **The four existing README walk suites** (`test_readme_*_walk_linux.py`), each against a real `serve`. They run with the M11 web UI build, made with `npx vite build --outDir` into `m11t-scripts/webui-build` outside the tree and copied into the WSL copy only (`tmp/readme_walks.sh`).
- **A throwaway M11 walk** (`m11t-scripts/walk/test_readme_m11_walk_linux.py`, in the M9 walk's style):
  - it is copied into the WSL copy only and removed afterwards (`tmp/m11_walk.sh`), because TP-M11-16 keeps the evidence out of the tree;
  - it follows the new README and runbook steps against a real `serve` over HTTPS on PostgreSQL 16, with the fake OpenBao and audit sink, two agents enrolled and answering through the agent API, and the real clock, including the first real retention run;
  - each documented step is one row, with the expected answer taken from the README or the runbook text;
  - tokens and passwords are masked in every log and row file.

## Runs (WSL `/root/m11t`, `CI=true`, PostgreSQL 16 by Testcontainers, `--tb=short`, tokens masked)

| Run | Command | Result |
| --- | --- | --- |
| Static | `tmp/docs_static.sh` | all as below |
| R1 | `pytest -n 2` on the four `test_readme_*_walk_linux.py` (no UI build in the copy) | 2/4 passed, 2 failed. **m5:** "the web UI build is missing" (environment: the build is not in the tree). **m9:** crashed on `sc[0] == ""`, because the every-minute schedule queued no scan within the walk's 100 s bound |
| R2 | `pytest -n 0 test_readme_m9_walk_linux.py` with `WALK_OUT` | 89/90 rows OK. The bad row is the PD-51 one (below); the schedule row passed this time, so R1's crash was a timing flake |
| Fix | `test_readme_m9_walk_linux.py`: (a) PD-51 rewrite of the README-text row; (b) the every-minute schedule bound 100 s → 180 s. A cron `* * * * *` fires up to 60 s after creation and the tick runs every 30 s, so 100 s left too little slack (a flaky test is a bug). Lint: ruff, format, `mypy --strict` clean | — |
| R3 | `tmp/readme_walks.sh` with the UI build: all four README walk suites, `-n 2` | **4/4 passed**, 0 failed, 0 errors, 0 skipped |
| W1 | `tmp/m11_walk.sh` (the M11 walk) | 45/46 rows OK. The bad row was my measurement: "first retention run 10 minutes after start-up" read 571 s on the test's monotonic clock. The manager's own log shows `serving on` at 18:29:44.294Z and the seven `retention step done` lines at 18:39:46.311Z, **602 s** later. WSL2 stepped its wall clock about 31 s during the run, and APScheduler fires on wall time. The row now measures from the log's timestamps |
| W2 | `tmp/m11_walk.sh` after the row fix (the whole walk re-run: it is one test) | **46/46 rows OK**, pytest 1/1 passed, 0 failed, 0 errors, 0 skipped, rc 0 (575 s). The retention row reads "602.1 s (570 s monotonic), 7 step lines", so the clock step happened again and the log-time measure holds |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-380 | M11 walk W2 (`m11t-scripts/walk/test_readme_m11_walk_linux.py`, 46 rows; rows `/root/m11t/logs/m11walk-rows.jsonl`) | PASS | **46/46 rows OK in W2** (W1: 45/46, the one bad row being my monotonic-clock measurement, since fixed). Rows are in the table below. |
| CHK-M11-381 | `docs_static.sh` greps; m9 walk PD-51 row | PASS | README L679: "Compliance jobs past their deadline end `partial`, `failed` or `completed`". No "not part of this version", "later version" or "three scheduled" in the README or either runbook. "four scheduled jobs" is stated. |
| CHK-M11-382 | `check_runbook_text.py` ×3; M11 walk last row | PASS | README `OK 11 sh blocks, 0 findings`; manager-operations.md `OK 24 sh blocks, 0 findings`; agent-install.md has only its 2 known placeholder findings (L79, L123, the `bse_REPLACE…` placeholders, present before TASK-259), nothing new. The m9 walk's no-process-note row (no TASK/REQ/CHK id, tester or M-number in the Scans section) passes in R3. No walk secret is in the serve log. |
| CHK-M11-383 | M11 walk §1 and §6 rows; static §7 review | PASS | **§1:** the runbook's own agent-version SQL (extracted from the block) runs and lists the fleet. **§6:** the runbook's journal grep pattern, applied to the serve log, gives exactly seven `retention step done` lines in the documented order with `skipped` null; a step line has exactly the keys and logger of the runbook's example line; the first run came 10 minutes after start-up (602 s by the log); the checkpoint SQL runs and returns none on a young database; young data stays. **§7** is static only: its `gh` and `git tag` commands were not run (the release owner's steps). `release.yml` matches the checklist: tag or manual dispatch with `version`; tag, `pyproject.toml` and changelog must agree; the double agent build is compared with `cmp`; SHA256SUMS written and checked; draft release only; refuses `~`. `e2e.yml` has `workflow_dispatch`. |
| CHK-M11-384 | `docs_static.sh` | PASS | `dpkg-parsechangelog -S Version` → `0.2.0~pre2-1` (Date `Sun, 08 Nov 2026 00:00:00 +0000`, `unstable`). `check_debian_meta.py --root .` → **OK 82/82**, including CHK-M10-318 (`version 0.2.0~pre2-1 is X.Y.Z-R or X.Y.Z~preN-R`, weekday and strictly decreasing dates) and CHK-M10-319 (`release.yml` refuses a `~` version, and the guard tests the `dpkg-parsechangelog` value). Version order: `0.1.0-1 lt 0.2.0~pre2-1`, `0.2.0~pre1-1 lt 0.2.0~pre2-1` and `0.2.0~pre2-1 lt 0.2.0-1` are all true. |
| CHK-M11-386 | `test_readme_m9_walk_linux.py` (R2 → R3) | PASS | **PD-51, old → new.** CHK-M9-285's README-text row ("results routes 'not part of this version yet'; keys 'in memory, for 24 hours'…; scan state lags") becomes: the Scans section has `### Scan results` and no "not part of this version"; the keys and lag clauses are kept unchanged. Every other row of the four README walks is unchanged (R3, 4/4). |
| CHK-M11-385 | see `work/reports/TASK-245-test.md` | PASS | Done in TASK-245 TEST (the PD-51 job-set and stop-record rows). |

### The M11 walk rows (W2: 46/46 OK)

| Section | Rows (each with the expected answer taken from the text) |
| --- | --- |
| README "Listing scans" | **List:** `GET /scans` newest first with exactly the 12 documented item keys; `target_kind` `agents`, `resolved_count` 2. **Filters:** `agent_id` (upper case accepted), `state`, `created_after` (inclusive) and `created_before` (exclusive), each with an offset, and `policy_id`; 400 for a 32-hex `agent_id` and for a time without an offset. **Cursor:** one made under other filters is 400 `Invalid request: query.cursor`. **Host history:** `GET /agents/{id}/scans` lists the host's scans; an unknown host is 404. |
| README "One scan" | **Body:** the item plus `target` as requested (no resolved list) and `hosts`, by hostname, with the documented host and job keys. **Score:** A1 has 2/1/0/0, score 2/3 (passed ÷ (passed + failed)); A2 has 1/0/0/2, score 1.0, with `not_run` counting the checks with no result. **Ids:** unknown 404, not hyphenated 400. **Deleted profile:** a scan of a profile deleted later is still returned. |
| README "Results" | **Items:** one per check of each host's job, by `agent_id` then place, with exactly the 22 documented keys for a viewer and no `stdout`/`stderr`. **Not run:** `result` null and the result fields null. **Output:** stdout and stderr for an operator session and an admin API token. **Filters:** PASS 3, FAIL 1, ERROR 0, NOT_RUN 2; `status=pass` is 400. |
| README "CSV export" | **Response:** `text/csv; charset=utf-8`, no BOM, CRLF, `attachment; filename="scan-<id>-results.csv"`. **Columns:** exactly the 17 listed for a viewer; operator gets `stdout`, `stderr` added. **Cells:** a stdout `=1+2` becomes `'=1+2`; a not-run check has an empty `result`; `false` and UTC times ending in `Z`. |
| README "Re-evaluation" | **The README's curl command,** run as written with a real admin TOTP session (after the folder policy was edited to version 2, with check 2's ExpectedResult changed and check 3 dropped): 200 with exactly the documented keys, `scan_policy_version` 1, `policy_version` 2, `rows_added` 3, `not_in_version` 1. **Verdicts:** `result` is the new verdict (PASS) with `original_result` FAIL and `reeval_policy_version` 2; the unlisted check keeps its verdict. **Refusals:** 403 for an admin API token; unknown scan 404; deleted profile 409 `conflict`. **Repeat:** a second call adds another set; one `scan.reevaluate` audit entry each, neither with an alert. |
| README "Scheduler" / "Retention" and runbook §6 | **Timing:** the first retention run at start + 602 s (by the log), steps in the documented order, and the log lines are exactly as described. **Data:** nothing young deleted; reads still answer after the run. |
| Runbook §1 | the agent-version query runs and returns the fleet's versions |

### Statements checked against the code or other suites, not walked here

- **Nightly section (r1)** against `.github/workflows/e2e.yml` and `e2e/m11/README.md`: cron `40 1 * * *` and `workflow_dispatch`; a push runs only with `[e2e]` in the head commit message; three machines (the manager container installed by manager-install.md with the OpenBao and sink doubles, plus jammy and noble QEMU/KVM cloud-image guests); matrix `[nightly, compat-a, compat-b]`, each on its own `ubuntu-24.04` runner; compat-a and compat-b as described; artifacts `e2e-report-<run>` with `report.json` and `report.md`; tables in `$GITHUB_STEP_SUMMARY`; red on a FAIL or missing row (`--check-report`). All match. The run itself is the lead's hosted e2e (37/37), not re-run here.
- **Retention table, batches, guards, never-deleted list and the audit-prefix rule:** these match `services/retention/rules.py` and `task.py`, and are pinned by the TASK-242 and TASK-245 suites (clock_doubt, future_rows, the cursor cap, chunk sizes 100, 1,000 and 10,000, one checkpoint per batch, SIGTERM stopping at the next batch).
- **Results cap text, viewer key absence and the role read per request:** TASK-244 TEST (CHK-M11-222, -223, -226).
- **Web UI bullets** (Scans, Run scan, Scan detail with "75.0 %" / "n/a" and the errors beside it, Cancel and Re-evaluate with confirmation, Scan results, Schedules, host history, the role table): these match REQ-279 to REQ-284 and the web suites (TASK-239 and 246–251, tester-m11w). There is no browser in this harness, so they were not clicked through.
- **agent-install.md:** L7 names `0.2.0~pre2-1`; L178 says `0.1.0-1` and `0.2.0~pre1-1` hosts upgrade in place, since `0.2.0~pre2-1` sorts above both (`dpkg --compare-versions`, above). The real install-upgrade of the `0.2.0~pre2-1` package is G38 (maintainer scripts `0.1.0-1` → `0.2.0~pre2-1`) at the M11 gate; it is not part of a docs walk.
- The agent-install.md upgrade sentence and the README's pre-release block agree with the changelog's top entry.

## Not run

- **§7's `gh workflow run`, `gh run list`, `git tag` and `git push`:** the release owner's steps (no tag or release in M11). Static check only.
- **The README's Web UI bullets in a browser:** covered by the web suites.

No product or docs defect found. The two test changes (the PD-51 row and the flaky bound) are mine.
