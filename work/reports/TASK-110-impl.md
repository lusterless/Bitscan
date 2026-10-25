# TASK-110 IMPL: package search repository and filter types

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-114, REQ-115. Plan: `work/plans/TASK-110.md`. TS §7, §7.1 (L1196–L1215), §7.2 (L1219), §5.2 (L795–L815, L732).

## Files

- `manager/bitscan_manager/repositories/packages.py` (new, 278 lines; about 90 of them are the plan's fixed type declarations and docstrings). No other file changed. `manager/openapi.json` is not re-exported (no route in this task).

## What it provides (the plan's fixed interface)

`VersionOp`, `INSTALLED_STATUSES`, `SearchFilter`, `PackageRow`, `PackageGroup`, `HostGroup`, `RowAnchor`, `AnchorGone`, `like_escape()`, `PackageSearchRepo(conn)` with `rows(f, limit, after)`, `package_groups(f, limit, after)`, `host_groups(f, limit, after)`.

**Deviation from the plan text, per the user's answer:** `INSTALLED_STATUSES = ("install ok installed", "hold ok installed")`. The plan built the literal reading behind one constant until the owner answered #83 (f); `work/decisions.md` (2026-10-24, "M5 breakdown approved") records the user's answer that `hold ok installed` counts as installed. No other status is included (for example, `deinstall ok installed` is not). Tests for `status` omitted should expect held rows to be included.

## SQL (for the second look)

- All statements are `psycopg.sql.SQL` constants composed with `.format(tables=…, where=sql.SQL(" AND ").join(parts))`. The fragment list depends only on which `SearchFilter` fields are set; every value is a named bound parameter (`%(name)s`). Nothing from input reaches fragment text, and ruff S608 passes.
- Base: `agent_package ap JOIN package p … JOIN agent a …` with `a.status <> 'decommissioned'` always first (#83 (e), CHK-M5-329).
- `q`: `(p.name ILIKE %(q_like)s ESCAPE '\' OR p.name %% %(q)s)`, with `q_like = "%" + like_escape(q) + "%"`. `host`: `a.hostname ILIKE %(host_like)s ESCAPE '\'`. `like_escape` escapes backslash first, then `%` and `_` (CHK-M5-325, -326).
- `version_op`: one of five whole fragments from a `Mapping[VersionOp, sql.Composable]`, each `p.version::debversion <op> CAST(%(version)s AS debversion)` (CHK-M5-320). `version` alone: exact text `p.version = %(version)s`.
- `statuses`: `ap.status = ANY(CAST(%(statuses)s AS text[]))`, left out when `status=any`. `os`: `EXISTS` on `os_info` (a second constant when `os_version_id` is set). `tag`: `EXISTS` on `agent_tag`. `agent_id`: `ap.agent_id = %(agent_id)s`.
- Fail-closed on combinations that `parse_search` prevents: `version_op` without `version` binds NULL (no rows), and `os_version_id` without `os_id` binds `os_id` NULL (no rows). Neither is silently dropped.
- Orders and keysets are as the plan's table: rows `p.name, p.version::debversion, p.version, p.architecture, a.hostname, a.agent_id`, package groups `GROUP BY p.package_id` in `p.name, p.version::debversion, p.version, p.architecture`, host groups `GROUP BY a.agent_id` in `a.hostname, a.agent_id`. The keyset is the same tuple in `WHERE`, compared with `>` against typed casts. The Debian and text positions of the anchor version use **separate parameter names** (`k_deb`, `k_version`). psycopg reuses one `$n` for a repeated name, and one untyped parameter cast to both `debversion` and `text` would leave its type ambiguous.
- Cursor anchors hold ids only. The sort values are looked up first (`SELECT … FROM package p, agent a WHERE p.package_id = %s AND a.agent_id = %s`; `package` alone; `agent` alone), and `AnchorGone` is raised when no row is found.
- SELECT only; nothing is written (REQ-115 (5)). #87: no special handling (no `try`, no per-row guard), as planned.
- The rendered statement was checked offline with `as_string(None)` and psycopg's query converter: `%%` becomes `%` for the trigram operator and `ESCAPE '\'` carries one backslash.

## AC mapping

| AC | Where |
| --- | --- |
| Each filter alone, every pair, five-filter combination, three shapes | `_where` fragments, `_ROWS`, `_PACKAGES`, `_HOSTS` |
| `version_op` agrees with dpkg | `_VERSION_OP`, all `::debversion` |
| Paging N + 1 returns each item once, incl. `1.0` / `1.0-0` | text `p.version` tie-breaker after the Debian position in both order and keyset |
| `q=%_` literal | `like_escape` + `ESCAPE '\'` |
| ruff S608 | passes |

## Revision 1 (user ruling 2026-10-24, `work/decisions.md`)

`INSTALLED_STATUSES` is now `("install ok installed", "hold ok installed", "deinstall ok installed")`. A package selected for removal still has its files on the host until the removal runs. This is the only change to `repositories/packages.py` in r1.

In the same round, and outside this task's file list: `manager/pyproject.toml` gets `precision = 2` under `[tool.coverage.report]`, the M3 gate fix (decisions 2026-10-24, G5 rounding gap), so the M5 coverage gate matches M3.

r1 checks:
- `ruff check`, `ruff format --check` and `mypy --strict` on `manager/bitscan_manager` all pass (107 files).
- On the whole of `manager/`, ruff now reports E501/I001 in the tester's new files `manager/tests/package_fleet.py`, `test_csv_export.py` and `test_package_query.py`, and format reports 3 files to reformat. These are tester-owned and were reported to tester-m5.

## Checks run before r1 (M3 tree's venv, this worktree's paths, from `Bitscan-m5/`)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 219 files already formatted.
- `mypy --strict manager`: no issues in 219 source files.
- No tests run (tester's job; no WSL).

## For the tester

- TP-M5-03 can build `SearchFilter` values directly. The default `statuses` is `INSTALLED_STATUSES` (now including `hold ok installed`).
- `limit` is passed through as given; the route asks for `limit + 1`.
- `AnchorGone` covers a removed package (rows, package shapes) and a missing agent (rows, host shapes). Agents are never deleted by the app, so the agent case needs a test-only delete.
