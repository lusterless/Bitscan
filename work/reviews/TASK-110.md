# TASK-110 REVIEW: package search repository

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search, speed rule 6), checked closely because it is search SQL (lead, M5 note). Not a two-approval task.

Scope reviewed: `manager/bitscan_manager/repositories/packages.py`, revision 1 (`work/reports/TASK-110-impl.md`). Sources:
- TS §7, §7.1, §7.2, §5.2 (the `package` and `agent_package` tables and their indexes);
- REQ-114, REQ-115, #83 (a)–(f) and #87;
- the user rulings of 2026-10-24: `hold ok installed` and `deinstall ok installed` count as installed.

TEST: PASS (`work/reports/TASK-110-test.md`). `test_package_repo_pg.py` is 58/58 after one test-bug re-run. The plants are red: CHK-M5-320 (text comparison), 325 and 326 (unescaped LIKE), 327, 329 (decommissioned searched), an SQL-text interpolation, and literal-only statuses. The S608 plant is red too.

## Checks
1. Spec:
   - Filters combine with AND (TS §7.1).
   - `version` alone is exact text. `version_op` uses `p.version::debversion <op> CAST(… AS debversion)` and never compares text (TS §7.2). That form can use `ix_package_name_debver`.
   - `q` is `ILIKE` with escaped wildcards, or `pg_trgm` `%` (#83 (a)). Both can use `ix_package_name_trgm`.
   - `host` is a case-insensitive escaped substring (#83 (d)).
   - `os` is exact on `os_info` (#83 (c)), and `tag` is exact on `agent_tag`.
   - Decommissioned agents are always excluded (#83 (e)).
   - `INSTALLED_STATUSES` is the one definition, holding the three user-ruled statuses. This is a recorded owner deviation from the TS §7.1 wording "only `install ok installed`".
   - Item shapes: `host_count` is `count(*)` per `package_id`, which equals the distinct hosts because `(agent_id, package_id)` is the primary key. `package_count` is per `agent_id`.
2. SQL safety, the main risk:
   - Every statement is a `psycopg.sql.SQL` constant. Which constants are used depends only on which filter fields are set, and every value is a named bound parameter. No input reaches fragment text, and the `_anchor` queries are `LiteralString`.
   - `like_escape` escapes the backslash first, then `%` and `_`, with `ESCAPE '\'`. That is correct under `standard_conforming_strings = on` (the PostgreSQL 16 default).
   - The `%%` in `_Q` is the trigram operator, written for a parameterised statement.
   - The repository only reads. The export path sets `REPEATABLE READ, READ ONLY` as the transaction's first statement.
   - Combinations that `parse_search` prevents fail closed (a NULL bind gives no rows) instead of dropping a filter.
3. Paging: each keyset tuple equals its `ORDER BY` tuple, and each is a total order:
   - rows end in `(…, hostname, agent_id)` over unique `(package, agent)` pairs;
   - package groups are unique by `(name, version, architecture)`;
   - host groups end in `agent_id`.

   The separate `k_deb` and `k_version` binds avoid psycopg reusing one `$n` with two types. A cursor holds ids only (#89), and a vanished anchor raises `AnchorGone`.
4. Scope: 1 file, about 280 lines. About 90 of those are the plan's type declarations, so the logic is close to the 200 estimate. No other file was changed except the M3 precision line, which has already been reviewed.
5. Re-run by the reviewer (Windows):
   - ruff check and format on the task and test files: clean.
   - `mypy --strict` on `bitscan_manager`: 110 files, no issues.
   - The tree-wide ruff run shows 5 E501 errors only in `tests/test_webui_serving.py`, the TASK-112 tester file that is still in progress.

## Findings
1. nit (performance, not in M5's gates), `packages.py:150-153`. Broad searches sort by `p.version::debversion` and `a.hostname` over the join. TS §7's "under 1 s at 20 M rows" target belongs to the load test, which the user deferred until after M6. Measure `q=lib` with `status=any` and no other filter there. If it is slow, the likely remedy is a narrower default (for example, require `q` or `name` for the rows shape), not a new index, because the schema is fixed.
