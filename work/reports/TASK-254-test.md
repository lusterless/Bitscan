# TASK-254 TEST (TP-M11-20): `.github/workflows/e2e.yml` — PASS on every row run; CHK-M11-373 and -374 NOT RUN (awaiting the user)

Tester: tester-m11e, 2026-11-09. Rows: `work/reports/M11-e2e-test.md`, section "TP-M11-20". REQ-286.

## Verdict

**Every row that was run is PASS. Three rows are NOT RUN, each with its reason.** The hosted plants CHK-M11-373 and -374 need throwaway branches pushed to GitHub, which is beyond the overnight push authorisation (the lead, 2026-11-08); the user decides. `actionlint` is not installed. Under the M10 rule (decisions 2026-10-30 (2)), M11 does not merge with a NOT RUN row until the user decides, so this TEST is reported but not closed.

| Row | Result | Evidence |
| --- | --- | --- |
| REQ-286 (1): an `[e2e]` run on the M11 branch, green with every row PASS | **PASS** | Run 42488215323 on `5671c82`: build success; nightly 19/19, compat-a 10/10, compat-b 8/8; every gate green; artifacts `e2e-report-{nightly,compat-a,compat-b}` |
| A push without `[e2e]` runs nothing | **PASS** | Run 42485349317 on `9d4f1a7`: both jobs skipped |
| The step scripts as written (local) | **PASS** | 12/12 extracted and `bash -n` OK; no `${{ }}` inside a script. Collect release folder: 6 files; a seventh → rc 1; the printf fix re-tested. Fetch images. Download v0.1.0: 12/12 published sums OK. The harness step: root-only log and work folder; the pre-check refusal path → gate red. Row report. Gate |
| REQ-286 (2), local form: the gate red on a FAIL row, a missing row, no report | **PASS** | rc 1 for each, with the named problem |
| CHK-M11-373, hosted (a FAIL row) | **NOT RUN**: awaiting the user's OK to push a throwaway branch | Spec in the report: branch `m11-e2e-plant-373`, one line in `nightly.py` `sweep()` |
| CHK-M11-374, hosted (an expected row removed) | **NOT RUN**: awaiting the user's OK | Spec in the report: branch `m11-e2e-plant-374`, one line in `nightly.py` `results()` |
| REQ-286 (3): `actionlint` | **NOT RUN**: not installed here | Instead, the YAML was parsed and every step script checked |

Known gap: there is no Hyper-V form of `guests.sh`. `e2e.yml` documents the standing-approval fallback as manual only, and it cannot run.
