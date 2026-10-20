# TASK-016 REVIEW: migration `m0003` (scanning)

Reviewer: reviewer. Date: 2026-10-20. REQ-023. Spec: TS §5.2 L842-938, TS §5.3 L1046. Inputs: `work/plans/TASK-014.md` (split table row `m0003_scanning`), `work/reports/TASK-016-impl.md`, `work/reports/TASK-016-test.md` (PASS; WSL, `CI=true`, 328 passed, 11 mutations red), `tests/m1/report.md` CHK-M1-090 to -095, -096-pre, -050-r4.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268).

## What was checked

- **Verbatim against the spec, by my own script.** TS L842-938 read from the spec file, each `--` comment outside string literals removed, plus trailing whitespace and blank lines, then compared line by line with the joined `STATEMENTS` (11 statements). Result: 89 lines, identical. Only comments were removed.
- **The plpgsql function and trigger:**
  - `CREATE FUNCTION scan_result_check_job() … AS $$ … END $$;` is a single statement;
  - the function body in the spec (L919-925) has no comments, so the stored source is the spec text;
  - `str(text(stmt).compile(dialect=postgresql.psycopg))` equals the literal for all 11 statements, so `text()` changes nothing;
  - there are 0 bind parameters, no `:=`, no `%`, and the three `::` casts pass through unchanged;
  - `CREATE TRIGGER scan_result_job_check BEFORE INSERT ON scan_result FOR EACH ROW EXECUTE FUNCTION scan_result_check_job();` is defined on the partitioned parent, which PostgreSQL 16 clones to every partition. The tester shows it fires through the parent and directly into `scan_result_default`, with the spec's message (CHK-M1-093).
- **Structure, as written in the spec:**
  - `scan_result … PARTITION BY RANGE (job_created_at)` and `scan_result_default PARTITION OF scan_result DEFAULT`;
  - no monthly partitions (they belong to m0005), and the default partition is empty after migrate (CHK-M1-096-pre);
  - `ix_job_pending ON scan_job(agent_id) WHERE state = 'queued'`;
  - the `scan_job` CHECKs `(kind = 'compliance') = (scan_id IS NOT NULL)` and `kind = 'inventory' OR eval_spec IS NOT NULL`, plus the `kind` set;
  - `eval_code IN (0, 1, 2)`, and `result check_result GENERATED ALWAYS AS (…)`;
  - ON DELETE actions: `scan.schedule_id … ON DELETE SET NULL`, `scan_job.scan_id`, `scan_result.job_id` and `scan_result_reeval.job_id … ON DELETE CASCADE`.
- **Nothing extra:** no grants, seeds (`INSERT`), `SET ROLE`, `RESET` or `search_path`.
- **Forward-only:** `revision = "m0003"`, `down_revision = "m0002"`, and `downgrade()` only raises `NotImplementedError`.
- **E501 `noqa`:** the only lines over 88 characters are the 120-character `scan_state` enum line (`:16`) and a 105-character spec line (`:104`). Each `noqa` sits after its own literal's closing quotes (`:17`, `:109`), so each covers only that literal.
- **Tests:**
  - `test_schema_scanning.py` (10 pg cases, written from the spec before the migration was read) covers REQ-023 (1) to (7);
  - the direct-to-default cases use a 2000-01-01 job, so they stay valid when m0005 adds the monthly partitions;
  - 11 mutations each turn a test red, including the trigger switched to `BEFORE UPDATE`;
  - ruff, format and `mypy --strict` are clean (30 files).

## Findings

None.
