# TASK-111 IMPL: CSV writer with formula escaping

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-116. TS §6.3 (L1142); #84 (c), (d).

## Files

- `manager/bitscan_manager/services/packages/csv_export.py` (new, 40 lines). No other file changed. `manager/openapi.json` is not re-exported.

## Interface (TASK-114's `export_csv` builds on it; M11 results CSV reuses `escape_cell`)

- `escape_cell(cell: str) -> str`: prefixes `'` when the cell starts with a tab or CR, or when, after any run of leading whitespace (`str.lstrip()`, the same whitespace set as `str.isspace()`), it starts with `=`, `+`, `-` or `@`. Every other cell is unchanged (`a=b`, `1-2`, `'=x`, the empty cell, ` 1`, `\n1`).
- `csv_line(cells: Sequence[str]) -> str`: escapes each cell, then quotes it per RFC 4180 (a cell holding `,`, `"`, CR or LF is wrapped in `"…"` with each `"` doubled), joins with `,` and ends with CRLF.
- `write_csv(header, rows) -> str`: the header record, then one record per row. Header cells go through the same escape.
- Cells are `str`; the caller turns UUIDs and counts into text. The caller also encodes to UTF-8 (no BOM, #84 (c)). Every record, including the last, ends with CRLF.

## AC mapping (REQ-116 (1), (2), (4))

Ad-hoc sanity (not a test file):

- Prefixed once: `=1`, `+1`, `-1`, `@a`, `\t1`, `\r1`, ` =1`, `\n+1`, `　-1`, `  \t@a`.
- Unchanged: `a=b`, `1-2`, `'=x`, `''`, `plain`, ` 1`, `\n1`.
- `=HYPERLINK("http://x")` comes out as `"'=HYPERLINK(""http://x"")"`.
- `a,b` and `x\ny` are quoted.

## Checks run (from `Bitscan-m5/`, M3 venv)

`ruff check manager`, `ruff format --check manager` and `mypy --strict manager` all pass (219 files). No tests run.

## For the tester

- Import from `bitscan_manager.services.packages.csv_export` (not re-exported by the package `__init__`).
- A cell starting with LF alone is not prefixed (LF is not a TS §6.3 trigger), but LF followed by a trigger is, because LF is whitespace.

## Revision 1 (lead ruling after review; TS §6.3 L1142 and the security invariant read literally)

The revision only adds escaping. A cell whose run of leading whitespace is followed by **any** trigger now gets the `'` prefix, including a tab or CR (for example ` \tabc`, ` \rabc`, `\n\tx`).

`escape_cell` now splits the cell into its leading whitespace run (`str.lstrip()`) and the rest. It prefixes when the rest starts with `=`, `+`, `-` or `@`, or when the run holds a tab or CR. A tab or CR is itself whitespace, so it always falls inside the run, and "starts with a tab or CR" is the same check with nothing in front. Every cell prefixed before is still prefixed.

The old condition was `cell[:1] in {tab, CR} or cell.lstrip()[:1] in {=, +, -, @}`. It left ` \tabc` unchanged, because `lstrip()` also strips the tab, so it must go red on ` \tabc`.

Ad-hoc (not a test file):
- Now prefixed: ` \tabc`, ` \rabc`, `\n\tx` and a lone `\t`.
- Still prefixed: `\t1`, `\r1`, `=1`, `+1`, `-1`, `@a`, ` =1`, `　-1`.
- Still unchanged: `a=b`, `1-2`, `'=x`, `''`, `plain`, ` 1`, `\n1`, ` `, `a\tb` (a tab that is not leading).

Files: `manager/bitscan_manager/services/packages/csv_export.py` only. Checks: ruff check, ruff format --check and `mypy --strict --config-file manager/pyproject.toml` pass; LF line ends. No tests run.

Tester: re-run `manager/tests/test_csv_export.py` (and TP-M5-07 once TASK-114 is under test). Plant the old condition; it must go red on ` \tabc`.
