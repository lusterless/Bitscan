# TASK-260 TEST: PASS

Tester: tester-m11d, 2026-11-09. This is docs only: the #155 results CSV memory limit is documented as a known v1 limit, by the user's decision (decisions.md 2026-11-09 (1), option (a), no code change).
- `README.md` +1 line: Scan results → CSV export, the "Memory (a known limit of this version)" bullet, from impl-manager-a.
- `deploy/runbooks/manager-operations.md` +6 lines: a new §8 "Known limits", from impl-deploy.

See `work/reports/TASK-260-impl.md`.

## Checks

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Factual, against the code and spec | read both notes against `services/jobs/results_view.py`, `results_read.py`, `services/evaluator/model.py`, TS §4.5 L601 and the decision | PASS | See the factual check below. |
| `check_runbook_text.py`: no new findings | `m11t-scripts/tmp/docs_static.sh` (WSL) | PASS | README.md `OK 11 sh blocks, 0 findings`. manager-operations.md `OK 24 sh blocks, 0 findings`; §8 adds no sh block. agent-install.md (unchanged) still has only its 2 known placeholder findings. |
| The README walk tests still pass | `m11t-scripts/tmp/readme_walks.sh readme260 -n 2` on the four `test_readme_*_walk_linux.py` (WSL, `CI=true`, PostgreSQL 16, with the M11 web UI build copied into the WSL copy only) | PASS | **4/4 passed**, 0 failed, 0 errors, 0 skipped (254 s) |
| The two notes agree | read side by side | PASS | Same facts and the same advice. The README says "64 KiB / 16 KiB" (exact for the 65,536 / 16,384-byte caps); the runbook says "64 KB / 16 KB" as the spec does. |

**Factual check of both notes:**
- **The whole file is built in memory before it is sent.** True: `results_read.results_csv` reads every row, then `csv_text` builds the text, before the route makes the response.
- **The 100,000-row cap.** True: `CSV_MAX_ROWS = 100_000`.
- **Operator and admin rows carry stdout up to 64 KiB and stderr up to 16 KiB.** True: `STDOUT_CAP = 65_536` and `STDERR_CAP = 16_384`; the manager stores over-cap results as ERROR `oversize` with empty streams (TS §4.5 L601).
- **"About 8 GB" in the worst case.** True: 100,000 × 80 KiB ≈ 8.2 GB, before the text and bytes copies; the runbook says "and more while the file is written".
- **A viewer's export has no output columns and stays small.** True: `include_output` is false for viewers, and `csv_header(with_output=False)` has no `stdout` or `stderr` (TASK-244 TEST CHK-M11-222).
- **The advice to narrow with the `status` and `agent_id` filters.** True: both filters exist on `results.csv`.
- **Neither note claims what the code doesn't do:** no streaming, no setting, no other cap.

## Notes

- **No secret or process note:** neither note has a token, DSN, task id or process note, and the checker agrees.
- **Container:** a container labelled `m11t-timing` was running in WSL during this check. It isn't from any of my runs, so I left it alone.
