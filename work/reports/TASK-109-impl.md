# TASK-109 IMPL: package search query parsing

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-113. Plan: `work/plans/TASK-110.md` ("`parse_search` rules"). TS §7.1 (L1196–L1212); #83, #88.

## Files

- `manager/bitscan_manager/services/packages/__init__.py` (new; re-exports the public names below)
- `manager/bitscan_manager/services/packages/query.py` (new, 187 lines)

No other file changed. Uses `SearchFilter`, `VersionOp` and `INSTALLED_STATUSES` from TASK-110's `repositories/packages.py`. `manager/openapi.json` is not re-exported.

## Interface

`GroupBy`, `MAX_LEN`, `Q_MIN`, `SearchQuery(filter, group_by)` with `shape()` (`"rows" | "package" | "host"`) and `cursor_scope()` (`packages:<shape>:<32 hex>`), `InvalidSearch(params)` (`.params` holds parameter names only, sorted), `parse_search(params)`, and `is_debian_version(value)`, which is public so the planned #87 decoder follow-up can reuse the same check. The extra helper constants (`OS_ID_MAX`, `OS_VERSION_MAX`, `EPOCH_MAX`) are module-level only.

## Rules, in the plan's order (the first failure raises)

1. Text values `q`, `name`, `version`, `arch`, `os`, `tag`, `host` (checked in that order): an empty value, U+0000, or a value longer than `MAX_LEN` is refused (`q`/`name`/`version`/`host` 255, `arch` 16, `os` 49, `tag` 64). A value exactly at the limit is accepted. **Addition:** a lone surrogate code point (U+D800–U+DFFF) is refused as well, on builder-checklist item 1. It is unreachable through Starlette's query decoding, which replaces invalid UTF-8, but it keeps the pure function from passing an unencodable `str` to psycopg.
2. Enums, exact values: `version_op` in `lt|le|eq|ge|gt`, `status` in `installed|any`, `group_by` in `package|host`.
3. `q` under 3 characters gives `("q",)`. `q` together with `name` gives `("name", "q")`.
4. `version_op` without `version` gives `("version", "version_op")`.
5. `version` must have dpkg syntax (epoch 1–10 ASCII digits up to 2,147,483,647; revision after the last `-`, non-empty, `[A-Za-z0-9.+~]`; upstream non-empty, starting with a digit, `[A-Za-z0-9.+~-]` plus `:` only with an epoch). Plain frozenset membership, no regex, no `isalnum`/`isdigit`.
6. `os`: `id` or `id:version`. Refused: an empty part, a second `:`, an id over 32 or a version over 16 characters.
7. `agent_id`: 36 characters, hyphens at 8/13/18/23, ASCII hex elsewhere, then `uuid.UUID` (lower-case output).
8. `status=any` gives `statuses=None`; absent or `installed` gives `INSTALLED_STATUSES` (which includes `hold ok installed`, per the user's #83 (f) answer; see TASK-110 report).

`cursor_scope()` hashes every `SearchFilter` field (`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, enum values as strings, `agent_id` lower-case, `statuses` as a list or null) and is prefixed by the shape.

## Ad-hoc sanity (not a test file)

- All 51 distinct versions in `manager/tests/fixtures/debversion_pairs.tsv` are accepted.
- Refused: `1.0 beta`, `a1`, `1:`, `1.0-`, `:1`, `~1`, an 11-digit epoch.
- Accepted: `1:2:3` and `1.0-1-2`, as dpkg accepts them.
- The REQ-113 (1) examples behave as listed: `q=ab` is refused and `q=abc` accepted, `ne`/`LT`/`removed`/`group_by=name` are refused, both `os` forms parse, and `name=` and `q=abc\0` are refused.
- Equal queries give equal scopes; a changed `q` or `group_by` changes the scope.

## Checks run (from `Bitscan-m5/`, M3 venv)

`ruff check manager`, `ruff format --check manager` and `mypy --strict manager` all pass (219 files). No tests run.

## For the tester

- `params` is a `Mapping[str, str | None]` of the eleven TS §7.1 names; unknown keys are ignored. `limit` and `cursor` are not part of it.
- TASK-111 (`csv_export.py`) lives in the same package; `__init__.py` does not re-export it (import it from `bitscan_manager.services.packages.csv_export`).
