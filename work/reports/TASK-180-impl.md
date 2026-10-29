# TASK-180 IMPL: the `eval_spec` contract

Implementer: impl-manager-m8b. REQ-195 (REQ-202 by its imports). Risk high. Spec: TS §5.2 L880, L888, L907–L910; §4.5 L587, L603; §3.5 L248; §6.5 L1165–L1180. Answer applied: #117. Built against TASK-176's `model.PluginSpec`.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/evaluator/eval_spec.py` (new, 127 lines) | `NAME_MAX`, `EXPECTED_MAX`, `EvalSpecError`, `EvalSpec` (with `get()`), `build_eval_spec()`, `parse_eval_spec()` |

No file outside the task's list was changed.

## Interface (frozen for M9 once W2 passes)

```python
NAME_MAX: Final = 400                      # plugin_name_snap VARCHAR(400)
EXPECTED_MAX: Final = 4000                 # importer LENGTH_LIMITS["ExpectedResult"][1]
class EvalSpecError(ValueError): ...       # fixed messages only

@dataclass(frozen=True, slots=True)
class EvalSpec:
    plugins: tuple[PluginSpec, ...]        # payload order; eq/hash over this only
    def get(self, plugin_uuid: UUID) -> PluginSpec | None: ...

def build_eval_spec(spec: EvalSpec) -> dict[str, Any]
    # {"plugins": [{"plugin_uuid": str(uuid), "name", "operator", "expected"}, ...]}
def parse_eval_spec(value: object) -> EvalSpec   # value = decoded JSONB / json.loads output
```

## Design

- **The rules live in `EvalSpec.__post_init__`**, so a spec that M9 can build always parses. The rules are:
  - 1 to 5,000 entries (the importer's `PLUGINS_MIN`/`PLUGINS_MAX`);
  - each operator is one of `importer.model.OPERATORS`;
  - `name` is 1–400 characters;
  - `expected` is 0–4,000 characters;
  - no duplicate `plugin_uuid`.

  It also builds a read-only index for `get()`. The index is a `MappingProxyType`, excluded from `eq`, `hash` and `repr`.
- **`parse_eval_spec` adds the structural checks**, then constructs `EvalSpec`, which applies the rules above. The structural checks:
  - top level is a `dict` whose keys are exactly `{"plugins"}`;
  - `plugins` is a `list` of 1–5,000 items (checked before any entry is parsed, so a huge list is refused at once);
  - each entry is a `dict` whose keys are exactly the four;
  - every value is a `str` (a `bool` or a number is refused);
  - `plugin_uuid` is exactly the lowercase hyphenated 36-character form (`str(UUID(v)) == v`), so uppercase, braced, `urn:` and 32-hex forms are refused. The `ValueError` from `UUID()` is suppressed (`from None`).
- `build_eval_spec` writes the keys in the #117 order and never writes `execute` or `timeout_s`. `PluginSpec` has neither field, so it cannot.
- Imports: `dataclasses`, `types`, `typing`, `uuid`, `collections.abc`, `evaluator.model` and `importer.model` only (REQ-202 (1)). No logging.

## Acceptance points (REQ-195)

1. Round trip `parse_eval_spec(json.loads(json.dumps(build_eval_spec(x)))) == x`: the build output is plain JSON types, and `EvalSpec` equality is tuple equality over `PluginSpec`.
2. `EvalSpecError` for every listed case. Scratch check: all 18 refused: not an object; `[]`, `{}` and an empty list; an extra top key; `plugins` not a list; an extra entry key (`execute`); a missing key; an uppercase, braced or 32-hex uuid; operator `like`; name `''` or 401 characters; expected 4,001 characters or a number; a duplicate uuid; 5,001 entries. Name 400 and expected 4,000 are accepted. Every message is a fixed string.
3. `EvalSpec.get(uuid)` returns the entry or None (checked in the scratch run).
4. SR §1.1: built from `PluginSpec(u, "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed", "equals", "install ok installed")`, the output has exactly `plugin_uuid`, `name`, `operator` and `expected`.

## Mutation plants (M8 table)

- **CHK-M8-344:** in `_entry`, change `item.keys() != _ENTRY_KEYS` to `not _ENTRY_KEYS <= item.keys()` (accepts an extra key), or delete the `if p.plugin_uuid in index` check. Expect G62 red.
- **CHK-M8-345:** add `"execute": ""` to the dict in `build_eval_spec`. Expect G62 red (the SR §1.1 row and the round trip).
- Extra boundary plants:
  - drop `len(value) != 36` and the `str(parsed) != value` check (uppercase or braced uuid accepted);
  - `<= NAME_MAX` → `< NAME_MAX` (the 400 row);
  - remove the `isinstance(value, str)` check in `_text`.

## Gates (worktree root, worktree's own `manager/.venv`)

- `ruff check manager`: All checks passed.
- `ruff format --check manager`: 321 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`, and with `--platform linux`: no issues in 321 files.

## For the tester

- The parser takes an already-decoded value, not text. psycopg returns JSONB as `dict`.
- Lone surrogates and U+0000 in strings are not refused here. They cannot come from the catalog (PostgreSQL `text` holds neither), and JSONB refuses both on write, so M9 would fail at its insert.
