# TASK-260 IMPL: README note on the results CSV memory limit

Implementer: impl-manager-a. The user's decision on #155: the results CSV stays as built, and its memory use is documented as a known v1 limit. Spec: TS §6.2 L1123, §6.3 L1144.

## File

`README.md`: +1 line. No code changed.

## Change

In "Scan results" → "CSV export", straight after the 100,000-row cap bullet:

> **Memory (a known limit of this version):** the manager builds the whole file in memory before sending it. An operator or admin export includes `stdout` (up to 64 KiB per check) and `stderr` (up to 16 KiB). At the 100,000-row cap, with maximal output, it can need several GB of manager memory, about 8 GB in the worst case. For big scans, narrow the filters, or export one host or one status at a time. A viewer's export carries no output and stays small.

How the facts were checked:
- **Output caps:** 65,536 and 16,384 UTF-8 bytes (`services/evaluator/model.py` `STDOUT_CAP`, `STDERR_CAP`). The README's Agent API section already states them.
- **Worst case:** 100,000 × 80 KiB ≈ 8 GB, before quoting overhead.
- **Built in full:** `results_read.results_csv` returns the whole text, and the route sends it in one response.
- **No output for viewers:** a viewer's export uses the statement variant that selects no output and has no `stdout`/`stderr` columns.
- **Filters:** `status` and `agent_id` are the export's filters, so one host or one status at a time is possible.

## Self-check

`python -I deploy/tests/check_runbook_text.py README.md` gives `OK 1 files, 11 sh blocks, 0 findings`.

## Runbook part (impl-deploy, 2026-11-09)

File: `deploy/runbooks/manager-operations.md` (+7 lines). No other file changed.

A new last section, **§8 Known limits**, with one item, "Results CSV memory":
- The manager builds the results CSV in full in memory, and refuses an export of more than 100,000 rows (#146 (e)).
- Operator and admin rows also carry stdout (up to 64 KB) and stderr (up to 16 KB) (TS §4.5 L601), so one export at the cap with maximal output can need about 8 GB of manager memory, and more while the file is written. This is the #155 note's "roughly three times that once it becomes text".
- A viewer's export has no output columns.
- Two actions: size the manager host's memory for the largest operator or admin exports, and narrow big exports with the `status` and `agent_id` filters (the CSV route's two parameters, `api/user/scan_views.py` `results_csv`).
- It is a new section after §7, so §1 to §7 keep their numbers and block order. The M6 and M11 harnesses that read §1, §4 and §5 by position or anchor are unaffected, and the section adds no sh block.

Check: `python -I deploy/tests/check_runbook_text.py deploy/runbooks/manager-operations.md` gives `OK 1 files, 24 sh blocks, 0 findings`.
