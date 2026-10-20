# TASK-016 IMPL report: migration m0003 (scanning)

REQ: REQ-023. Spec: TS §5.2 L842–L938 (verbatim), TS §5.3 L1046. Plan: `work/plans/TASK-014.md` (split table, row `m0003_scanning`).

## File (1)

- `manager/bitscan_manager/db/migrations/versions/m0003_scanning.py` (135 lines, mostly SQL): `revision = "m0003"`, `down_revision = "m0002"`. `STATEMENTS` holds 11 static string literals, run in order with `op.execute`. `downgrade()` raises `NotImplementedError("forward-only (TS §5.3)")`.

## What it creates, in spec order

- Types `scan_state`, `check_result`.
- Tables `scan_schedule`, `scan`, `scan_job` (+ partial index `ix_job_pending`), `scan_result` (`PARTITION BY RANGE (job_created_at)`, with the generated `result` column) and its DEFAULT partition `scan_result_default`.
- Function `scan_result_check_job()` (plpgsql, `$$ … $$`) and trigger `scan_result_job_check`.
- Table `scan_result_reeval`.

The monthly partitions are not created here; they come in m0005 (TS §5.3, PD-18). No grants or seeds.

## How the text was produced

The same one-off script as for m0001 and m0002 was run on L842–L938. Differences and guards:
- The block starts at `-- ===== Scanning =====` and ends at `);` before `-- ===== System =====`.
- **The split is dollar-quote aware.** The function body has lines ending in `;` (`RAISE …;`, `END IF;`, `RETURN NEW;`), so splitting pauses between the `$$` markers. The function is one statement ending in `END $$;`.
- Comments removed include the L850 `{"all":true}` comment (the `:word` hazard), the `eval_spec` comment with `:`, and the L878 "Must stay empty" line.
- What remains has no `%` and no `\`. Its only colons are `::check_result` (`::`). The function body has no `:=`, and its `RAISE` message has no `%`.
- Two statements (the `scan_state` enum and `scan_job` with the long `eval_spec` line) have spec lines over 88 characters. Each keeps its text verbatim, with `# noqa: E501` after that literal only.

## Checks run (Windows, offline)

| Check | Result |
| --- | --- |
| Migration lines == comment-stripped spec L842–L938 | True (89 lines) |
| Bind parameters (`sa.text().compile`, psycopg dialect) | none |
| Alembic `as_sql` output | every statement unchanged; function body intact through `END $$;`; no `%%` |
| `RAISE` message | `scan_result.job_created_at must equal scan_job.created_at` (REQ-023 (4)) |
| Script directory | chain `m0003 → m0002 → m0001` |
| Tester's scanner (CHK-M1-059) and forward-only checks: `pytest tests/test_db_migrate.py -k "bind or forward or downgrade or offline"` | 5 passed (3 pg skipped on Windows); full Windows suite 266 passed, 52 skipped |
| Escaping needed in the function body | none: no `:=`, no `:word`, no `%`; the body reaches PostgreSQL byte for byte, as the `as_sql` output shows |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` (29 files) | pass |
| Real PostgreSQL (diff-equal, REQ-023 cases, trigger through the parent and into `scan_result_default`) | **NOT RUN by me** (WSL root runs are blocked for me); the tester's harness covers it |

## For the tester

- `db migrate` prints `m0003`.
- With no monthly partitions yet, every `scan_result` insert lands in `scan_result_default` until m0005. The trigger is cloned to it, so the rejection holds both through the parent and directly.
- The function is `SECURITY INVOKER` (the default) and is owned by `bitscan_owner`.
- Constraint cases still run as the owner (no grants until m0005).
