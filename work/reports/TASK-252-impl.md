# TASK-252 IMPL: README for scans, results, CSV, score, re-evaluation, retention and the nightly run

Implementer: impl-manager-a. REQ-289 (README half). Risk low (docs). Spec: TS §4.5 L603–L604, §5.3 L1049, L1053, §6.2 L1113, L1120–L1125, §8.3 L1283. Written against what TASK-243 (re-evaluate route), TASK-244 (read routes), TASK-242/245 (retention), TASK-246 to 251 (UI) and the nightly harness built. TASK-244 and 245 are in TEST, and TASK-254 (`e2e.yml`) is not built yet. If a test, review or that task changes behaviour, I update the README to match.

## File

`README.md`: +114 / −10. No other file changed.

## What changed

| Section | Change |
| --- | --- |
| Introduction | The `serve` list names results, scores, CSV export, re-evaluation and retention. The pre-release block is "Compliance scans and results (pre-release `0.2.0~pre2-1`…)", the version planned for TASK-253 (changelog). The "come in a later version" sentence is replaced by links to Scan results and Retention |
| Web UI | The role table adds Scans, scan detail and scan results (all roles) and Run scan and Schedules (operator, admin). Re-evaluation is added to the TOTP-session sentence. There are bullets for Scans (filters, Run scan, also on an enabled profile's page), Scan detail (host rows, score "75.0 %" rounded down or "n/a" with the error count beside it, Cancel for operator and admin while unfinished, Re-evaluate for admin), Scan results (filters, both verdicts, output for operator and admin only, Export CSV), Schedules and the host page's scan history |
| API | The Scans bullet lists the five reads (viewer) and re-evaluate (admin, TOTP session) |
| Scans → **Scan results** (new; replaces "…not part of this version yet.") | The scan list (filters, item, cursor after retention), the host history, scan detail (hosts, jobs, counts, score rule and `null` → "n/a"), the results items, Not run, the filters, output only for operator and admin (keys absent for viewers, role read per request), the CSV (type, file name, the 17 columns plus `stdout`/`stderr` for operator and admin, cell forms, the 100,000 cap with its exact text, formula escaping in every column), and re-evaluation (admin, TOTP session, refused for API tokens and after 15 minutes of sink outage, adds verdicts only, unlisted checks and intake ERRORs kept, runs in the request, the answer, 404/409, one `scan.reevaluate` entry, no alert, a curl example) |
| Scheduler | "three" scheduled jobs becomes "four". The compliance-job line now reads "end `partial`, `failed` or `completed`" (REQ-289 (2)). There is a Retention bullet, and a stop note (a retention run stops at its next batch) |
| Scheduler → **Retention** (new) | `bitscan_retention` and `BITSCAN_RETENTION_DSN_FILE`, the interval from the `retention` row, a table of what goes when (400 / 30 / 180 / 90 / 90 days, 3 years, unreferenced packages), what is never deleted, partitions left to `db maintain`, the audit prefix with the `audit.checkpoint` entry and its detail, the batch sizes, the clock, future-row and re-evaluation guards, and the log lines (`retention refused: clock_doubt`, `retention step done`, `retention step failed`) |
| **Nightly end-to-end run** (new, last) | `e2e.yml`: nightly and on demand, the three machines, the chain, the pass condition, the compatibility rows, the report artifact and failure rule, and a link to `e2e/m11/README.md` |

## Self-check

- `python -I deploy/tests/check_runbook_text.py README.md`: `OK 1 files, 11 sh blocks, 0 findings`. That covers no secrets on command lines, no tokens, no process notes, and `bash -n` on every `sh` block.
- `grep` finds no "not part of this version", "later version" or "three scheduled".

## For the tester (README walk, batched with TASK-253's runbook walk in W4)

- The **Nightly** section describes `e2e.yml` as REQ-286 and the harness README specify it. The workflow is TASK-254 (W4), so walk that section after TASK-254 lands.
- The `0.2.0~pre2-1` version in the introduction comes from TASK-253's changelog entry.
- The retention timings come from `services/retention/rules.py` and the scheduler wiring from TASK-245 (first run start + 10 min). The log line texts come from `services/retention/task.py`.

## r1 (2026-11-08): the Nightly section matches the real `e2e.yml`

Main's r1 request, after TASK-254 (impl-deploy) built `.github/workflows/e2e.yml`. Only `README.md`'s "Nightly end-to-end run" section changed. Each point is checked against the workflow.

1. **Schedule:** "every night at 01:40 UTC". The workflow has `schedule: cron "40 1 * * *"` and `workflow_dispatch`.
2. **Push runs:** one new sentence, "A push runs it only when its head commit message contains `[e2e]`". The workflow's `build` job has `if: github.event_name != 'push' || contains(github.event.head_commit.message, '[e2e]')`.
3. **Compatibility:** the old sentence said the same guests run these rows, which was wrong. It is replaced by a "Compatibility" paragraph: two more runs, in parallel, each on its own runner with its own guest and manager host.
   - `compat-a`: this manager with the 0.1.0 agent, every check ERROR `runner_unavailable`.
   - `compat-b`: this agent with the 0.1.0 manager.
   - In the workflow these are the `run` matrix `[nightly, compat-a, compat-b]`, each `runs-on: ubuntu-24.04`.
4. **Report artifacts:** `e2e-report-nightly`, `e2e-report-compat-a` and `e2e-report-compat-b`, each with `report.json` and `report.md`. The tables are also shown on the run's summary page. The workflow names them `e2e-report-${{ matrix.run }}` and appends `report.md` to `$GITHUB_STEP_SUMMARY`.

The pass condition, the three machines, the failure rule and the token sweep are unchanged.

Self-check (r1): `python -I deploy/tests/check_runbook_text.py README.md` gives `OK 1 files, 11 sh blocks, 0 findings`.
