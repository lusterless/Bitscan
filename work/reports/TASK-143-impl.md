# TASK-143 IMPL: structure check (BIT002, BIT016)

Implementer: impl-manager-m7. REQ-151, REQ-176. Risk high (two approvals). Spec: SR §2, §2.1-§2.3 (names, order, occurrence), §4 (BIT001/BIT002 first; otherwise every failing rule), §4.1 BIT002, BIT016; TS §1.4 L43; answers #2, #10, #16, #105 (c), (d), (g). No plan file; it builds on TASK-140's model and TASK-141's `ParseResult`.

## File

`manager/bitscan_manager/services/importer/structure.py` (new, 208 lines with docstrings; about 165 hand-written). No other file changed.

## Interface

```python
@dataclass(frozen=True, slots=True)
class StructureResult:
    parsed: ParsedPolicy | None      # None when any BIT002 finding was made
    findings: tuple[Finding, ...]    # BIT002 only (sorted by line), or BIT016 only, or empty
def check(root: Node, pi_lines: Sequence[int] = ()) -> StructureResult
```

TASK-154 calls `check(result.root, result.pi_lines)` after `parse_bit` returns no finding.

## Rules

- Root must be `Policy`. Otherwise one BIT002 at the root line, and nothing else is checked.
- Each processing-instruction line from the parser gives BIT002 "Processing instructions are not allowed." (#105 (c)). Namespaces never get here: the parser reports them (TASK-141 §4a (1)).
- Containers `Policy` (PolicyName, PolicyDescription, PolicyStatus, Family, PluginsGroups), `Family` (FamilyName) and each `Plugin` (PluginName, PluginDescription, PluginId, Execute, Operator, ExpectedResult) are each checked once for:
  - **unknown child** (case-sensitive, so `<policyName>` is unknown): BIT002 at the child's line, element = the container path;
  - **duplicate:** BIT002 at the second occurrence. A second `Family` is BIT002 (#10);
  - **out of order:** BIT002 at the first child that comes after a later-ordered sibling;
  - **missing:** BIT002 at the container's line, element = the missing element's path. `Operator` and `ExpectedResult` are exempt (#2): a missing one leaves the field `None` in `ParsedPlugin` for BIT010 / BIT011;
  - **non-whitespace text** (anything but space, tab, CR, LF; #105 (d)): BIT002 at the container's line;
  - **unknown attribute:** BIT002 at the element's line.
- `PluginsGroups` holds only `Plugin` elements (any other is unknown), and at least one (#16: an empty or self-closing `PluginsGroups` is BIT002). `Plugin[n]` counts only `Plugin` elements.
- Leaves (the three policy fields, `FamilyName`, the six plugin fields) may hold no element: BIT002 at the child's line. Attributes allowed: only `Policy/@formatVersion` and `Execute/@timeout`.
- Paths follow #105 (g): `Policy/PolicyName`, `Policy/Family/FamilyName`, `Policy/PluginsGroups/Plugin[2]/Operator`, `.../Execute/@timeout`. A finding about an unknown element or attribute uses the parent's path and quotes the name with `model.quote()` in the message, so no unbounded file text gets into `element`.
- Only the first occurrence of each canonical element is descended into; duplicates and unknown elements are not, so one fault gives no cascade.
- Any BIT002 gives `parsed=None` and the BIT002 findings sorted by line (stable, so same-line findings keep rule order). BIT016 is then not reported (REQ-151 (6), fixture `plus-bit016.bit`).
- **BIT016:** with no BIT002, `@formatVersion` present and not exactly `1.0` (no trimming; `1.00` and an empty value fail) gives BIT016 at the `Policy` line, element `Policy/@formatVersion`. **The `ParsedPolicy` is still returned**, so the content rules run too (SR §4: only BIT001 and BIT002 stop them). See "For the planner" below.
- `ParsedPolicy` holds the raw, untrimmed values with their start-tag lines and paths. `format_version` is `None` when the attribute is absent (stored as `1.0` by TASK-151). `timeout` is `None` when absent.

## Checks run (Windows, scratch script outside the tree)

- All 180 fixtures in `bits/tests/manifest.json` were run through `parse_bit` then `check`:
  - **178 match**: every BIT002 fixture gets only BIT002 and `parsed=None`, with the first finding on a manifest line; every BIT016 fixture gets only BIT016, with the manifest line and element and a `ParsedPolicy`; every content and valid fixture gets no structural finding and a `ParsedPolicy`.
  - **2 differ, apparently in the manifest:** `bit002/miscased-policyName.bit` and `bit002/miscased-plugin.bit` give `lines: [2]`, but line 2 of both files is the fixture comment. I get BIT002 "PolicyName is missing." (line 3, `Policy/PolicyName`) plus "Unknown element "policyName"." (line 4). The plugin fixture gets "PluginsGroups holds no Plugin." (line 10) plus the unknown `plugin` (line 11). By the pattern of the other missing-element rows, the lines should probably be [3, 4] and [10, 11]. Reported to tester-m7b.
- SR §1.1 example: no finding. Values and lines: `formatVersion` 1.0 at line 2, `PolicyName` at 3, `FamilyName` at 7, `Plugin[1]` at 10, `Execute` at 14 with `timeout` "30" (path `.../Execute/@timeout`, line 14), `Operator` at 17, `ExpectedResult` at 18. `Execute` keeps its untrimmed CDATA.
- `content/bit010-missing.bit`: no finding; plugin 2 has `operator=None` (#2), plugin 1 has its operator.
- Lines for sample faults: missing `PolicyName` → 3; `PolicyStatus` after `Family` → 9; text in `Plugin` → 11; `<b>` in `PolicyName` → 4; `Execute/@user` → 15.

## Static gates

- `ruff check` and `ruff format --check` on the file: clean. `mypy --strict --config-file manager/pyproject.toml` on it: clean.
- A whole-tree `ruff check manager` currently fails only in `services/importer/shlex_posix.py` (another builder's TASK-145, in progress: E501 and F821 `_flush`). That file is not mine.

## Builder checklist

- 11 and 12: messages are fixed text; element or attribute names from the file appear only through `quote()` (64 characters, controls escaped).
- 15 does not apply.

## For the tester (tester-m7b; TP-M7-05, `test_bit_structure.py`)

- The two mis-cased fixture lines above.
- `check` returns BIT002 findings sorted by line. For a mis-cased or unknown required element there are two findings: the missing one at the container line comes first, then the unknown one at its own line.
- BIT016 comes with a `ParsedPolicy` (not `None`).

## For the planner

The TASK-154 plan §4 step 3 says "On BIT002 or BIT016, return them". SR §4 stops the content rules only for BIT001 and BIT002. This module therefore returns a `ParsedPolicy` together with BIT016, so the content findings are reported as well. TASK-154 should continue to `validate` when the only structural finding is BIT016.
