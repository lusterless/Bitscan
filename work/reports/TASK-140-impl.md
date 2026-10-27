# TASK-140 IMPL: importer model

Implementer: impl-manager-m7. REQ-152, REQ-155. Risk high (importer; two approvals). Spec: SR §2 (limits), §2.4 (operators), §3.3 (`control_ref` 32), §3.5 (`errors` item), §4 / §4.1 (codes, severities, retired codes); open questions #57 (MiB), #105 (g) (finding fields, quoting), #2 (missing `Operator` / `ExpectedResult`), #17 (trim before length checks).

## Files (new)

| File | LOC | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/__init__.py` | 30 | Package docstring and re-exports. |
| `manager/bitscan_manager/services/importer/model.py` | 225 | Below. |

Hand-written lines are about 150, the rest docstrings and blank lines. No database, file, clock or log access. No `re` or `xml` import.

## Interface (what W2 builds on)

- `Severity(StrEnum)`: `REJECT = "reject"`, `WARN = "warn"`.
- `Code(StrEnum)`: BIT001-BIT005, BIT007, BIT008, BIT010-BIT017, BIT101, BIT102, BIT103 (18 codes). BIT006, BIT009 and BIT018-BIT020 are absent, so `Code("BIT006")` raises `ValueError`.
- `SEVERITY: Mapping[Code, Severity]` (read-only `MappingProxyType`): `WARN` for BIT101 and BIT103 only; every other code, BIT102 included, is `REJECT` (SR §4.1).
- Limits (`Final`):
  - `MAX_BIT_BYTES = 5 * 1_048_576` (#57);
  - `FORMAT_VERSIONS = ("1.0",)`, `FORMAT_VERSION_DEFAULT = "1.0"`;
  - `POLICY_STATUSES = ("enabled", "disabled")`;
  - `PLUGINS_MIN = 1`, `PLUGINS_MAX = 5_000`;
  - `TIMEOUT_MIN = 1`, `TIMEOUT_MAX = 600`, `TIMEOUT_DEFAULT = 60`;
  - `CONTROL_REF_MAX = 32`.
- `LENGTH_LIMITS: Mapping[str, tuple[int, int]]` (read-only), keyed by element name, (min, max) in characters after trimming: `PolicyName` (1, 128), `PolicyDescription` (0, 4000), `FamilyName` (1, 128), `PluginName` (1, 255), `PluginDescription` (0, 4000), `Execute` (1, 16384), `ExpectedResult` (0, 4000).
- `OPERATORS` (the 14 operators, in the `plugin_operator` enum order of `m0001_catalog.py`), plus `NUMERIC_OPERATORS`, `REGEX_OPERATORS`, `PRESENCE_OPERATORS`.
- `Finding(line: int | None, element: str | None, code: Code, message: str)`, a frozen, slotted dataclass:
  - `__post_init__` coerces `code` through `Code(...)`, so a plain `"BIT001"` is accepted and a retired or unknown code raises `ValueError`;
  - `severity` and `rejects` are **properties derived from `SEVERITY`**, not a stored field, so a finding can never carry a severity that differs from its rule's (SR §4: "Severity is given per rule");
  - `to_json() -> FindingJSON` returns exactly `{line, element, code, message}`, with `code` as a plain `str`; `FindingJSON` is a `TypedDict`.
- `quote(value) -> str` (#105 (g), REQ-155 (3)): the first `QUOTE_MAX = 64` characters in double quotes, then `...` when the value was longer. Backslash becomes `\\`; `\n`, `\t` and `\r` become those escapes; other C0 controls and DEL become `\xNN`. Every later message builder (TASK-143, 144, 146) should use this one helper.
- `plugin_path(index, element=None)` gives `Policy/PluginsGroups/Plugin[<index>]`, with `/<element>` appended when given (for example `Execute/@timeout`), per #105 (g).
- `Node(name, line, attributes: tuple[tuple[str, str], ...], text, children: tuple[Node, ...])`, frozen, the shape the TASK-141 plan §2 asks for. TASK-141's collector keeps mutable frames and builds each `Node` at `end()`.
- `RawValue(text, line, path)`, frozen: the value as written (not trimmed), the start-tag line (for an attribute, its element's line) and its #105 path.
- `ParsedPlugin(index, line, plugin_name, plugin_description, plugin_id, execute, timeout, operator, expected_result)`, frozen:
  - `operator` and `expected_result` are `RawValue | None`; None means the element is missing (#2: BIT010 / BIT011, not BIT002);
  - `timeout` is None when `@timeout` is absent;
  - `path` property.
- `ParsedPolicy(line, format_version: RawValue | None, policy_name, policy_description, policy_status, family_name, plugins)`, frozen.

Choices for the reviewer (none changes spec behaviour):
- `quote` and `plugin_path` are in the model so every validator builds REQ-155 messages and #105 paths the same way. REQ-155 is linked to this task.
- The operator lists are SR §2.4 constraints (`Operator`, SR §2.3). TASK-144 (BIT010, BIT012-BIT014) and M8 read them from here.
- The TASK-151 types (`Candidate`, `RuleKeys`, ...) are not here: the TASK-151 plan puts them in `store.py`.

## Acceptance points

1. Every SR §4.1 code has its SR severity: `SEVERITY` covers all 18 `Code` members; only BIT101 and BIT103 are `warn` (checked: `[c for c in Code if SEVERITY[c] is WARN] == ['BIT101', 'BIT103']`).
2. BIT006, BIT009, BIT018, BIT019 and BIT020 are absent: each raises `ValueError` in `Code(...)` and in `Finding(...)`, and so does `bit001` (case-sensitive).
3. Each limit equals its SR §2 value: see the list above (SR L98-L122, SR §3.3 L202 for 32).
4. `json.dumps(Finding(1, "Policy/PolicyName", "BIT001", "x").to_json())` gives `{"line": 1, "element": "Policy/PolicyName", "code": "BIT001", "message": "x"}`, exactly four keys.
5. Every class is a `@dataclass(frozen=True, slots=True)`: assigning to a field raises `FrozenInstanceError`, and the mappings are read-only (`TypeError` on assignment).

## Static gates (Windows, `manager/.venv`)

- `ruff check manager`: All checks passed. `ruff format --check manager`: all formatted.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI command): Success, no issues in 236 source files.

## For the tester

- `Finding` takes four positional fields. `severity` is read-only and derived, and cannot be passed to the constructor.
- `quote("")` is `""` (the two quote marks). Values over 64 characters get `...` appended after the closing quote.
- On Windows, heredoc-fed Python can mangle backslashes in the input; build backslash test values with `chr(92)` or in a test file.
