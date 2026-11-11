# TASK-252 REVIEW: README for scans, results, CSV, score, re-evaluation, retention and the nightly run

Reviewer: reviewer-m11, 2026-11-09. Round 1, covering r1 (the nightly section). Low risk (docs), one approval.

Verdict: APPROVED

**Scope reviewed:** `README.md`, +114 / −10 against `6efe0fb`.

**Checked against:**
- TS §4.5 L603–L604, §5.3 L1049, L1053, §6.2 L1113, L1120–L1125, §8.3 L1283.
- REQ-289 (1)–(3); PD-51.
- The built code: TASK-243, 244, 242 and 245, the UI tasks 246 to 251, and `e2e.yml` (TASK-254).

**Reports:**
- `work/reports/TASK-252-impl.md`, including r1.
- `work/reports/TASK-252-test.md` (PASS). The four README walk suites passed 4/4. The M11 walk passed 46/46 in W2: the W2 row was a placeholder at first, and the tester has now filled it in. `check_runbook_text.py` reports 0 findings.

## Checks

- **Scan results section:** checked against the code and the spec.
  - The scan list filters and item keys are #145 (a), with the hyphenated `agent_id` (TASK-232 r1).
  - It notes that a cursor is invalidated once retention deletes the scan.
  - The host history includes decommissioned hosts.
  - The detail's hosts, jobs and counts are covered, and the score rule (passed ÷ (passed + failed), errors beside it, `null` shown as "n/a") follows TS §4.5 L604.
  - The 22 result keys, *Not run*, and the filters are covered. Output is shown only for operator and admin, with keys absent for viewers and the role read per request.
  - The CSV type, file name, the 17 columns plus the two output columns, the cell forms, the 100,000 cap with its exact text, and formula escaping in every column all match TASK-233, 241 and 244.
  - **Re-evaluation:** admin only, TOTP session, refused for API tokens and after 15 minutes of sink outage. Results are added, never changed. Checks the current version no longer lists, and intake ERRORs, are kept. It runs in the request, and the answer keys are documented. 404 and 409 are covered. One audit entry is written and no alert is raised (#148). This matches TASK-243 and M8.
  - The curl example has a placeholder token on the header line, no secret.
- **Scheduler and Retention:**
  - There are now four jobs. The compliance-job line reads "`partial`, `failed` or `completed`" (REQ-289 (2)).
  - The retention table, the never-deleted list (inventory included, G2) and `db maintain`'s 400-day partitions (`db/maintain.py`) are covered, along with the audit prefix, checkpoint, batches and guards.
  - The log lines quoted are the real texts from `services/retention/task.py`.
  - The walk confirmed the first run at start + 10 minutes (602 s by the log) and the seven step lines.
- **Web UI and API:**
  - The role table puts Run scan and Schedules under operator and admin, matching TASK-251's `ROUTE_ROLES`.
  - The TOTP sentence now includes re-evaluation.
  - The page bullets match the W3 screens.
  - The API list gives each new route its role.
- **Nightly section (r1):** cron `40 1 * * *` and dispatch; a push runs only with `[e2e]`; the three machines; the chain and its pass condition; compat-a and compat-b on their own runners; the artifact names and the failure rule. All of this matches `e2e.yml` as approved.
- **The removed "not part of this version" lines:** they are gone. The PD-51 walk-row rewrite (CHK-M11-386) keeps every other assertion, and the tester's change to the flaky 100 s bound is a test fix.
- **No secret, token or process note:** `check_runbook_text.py` is clean, and the walk's no-process-note row passes.

## Findings

None.
