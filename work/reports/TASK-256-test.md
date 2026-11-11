# TASK-256 TEST: shared scan pieces `ScanTable` and `TargetPicker` (W3 web batch, TP-M11-14)

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11` on `42d0692`, uncommitted IMPL (`work/reports/TASK-256-impl.md`). Shared batch evidence is in [TASK-246-test.md](TASK-246-test.md).
REQ: REQ-279, REQ-282. Spec: TS §4.4 L555, §6.3 L1143; #154 (a), (d), #68, #122 (b), #145 (a).

## Tests

| File | Result |
| --- | --- |
| `web/src/components/TargetPicker.test.tsx` (new) | **37/37** |
| `web/src/components/ScanTable.test.tsx` (new) | **5/5** |

## Acceptance criteria

**CHK-M11-273, the picker and the tag check: PASS.**
- The three forms are offered in order, with All hosts chosen, and no agents request is sent until "These hosts" is picked.
- Tags typed in the field become `{tags}`, and a bad tag gives the fixed rule text.
- These hosts sends `GET /agents?limit=50` through the client with the bearer, paged. The choice survives Next and Previous, and the legend shows "Hosts (2 chosen)".
- #68 boundaries:
  - 64 characters accepted, 65 refused.
  - 32 tags accepted, 33 refused.
  - Every allowed character class passes.
  - `/`, `<`, `a<script>`, `café`, `日本`, `;`, `*`, quotes, `=` and `@` are refused.
  - An empty or separator-only list is refused.
  - A space separates tags.
  - A repeated tag is sent once, which matches #122 (b)'s "distinct". The plan row was corrected from "refused".
- Host count: none chosen is refused, 10,000 is accepted, and 10,001 is refused.
- `<script>` and `onerror` host names render as text. A refused host list shows its problem.

**CHK-M11-274, the conversions: PASS.**
- Each form gives exactly one key.
- `toTarget(fromTarget(t))` equals `t` for `{all: true}`, `{tags}` and `{agents}`. `fromTarget(toTarget(v))` keeps the form and its values.
- A stored target that also has `resolved_agents` still reads as its requested form.
- `describeTarget` names each form, and gives "Unknown target" for `{}` and for `{all: "true"}`. A `<script>` tag stays text.

**CHK-M11-275, the table: PASS.**
- Exactly the six scan states are offered, each with its own label and badge text.
- Rows show created (linked to `scanHref`), profile, version, trigger, target kind with the host count, state and finished.
- A `<script>` or `onerror` policy name renders as text. An empty list has no body rows; the empty-state text is each screen's.

## Plants (red as required)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-375b | `dangerouslySetInnerHTML` policy name in `ScanTable` | lint exit 1, plus 3 tests across 3 files |
| CHK-M11-375c | `dangerouslySetInnerHTML` host name in `TargetPicker` | lint exit 1, plus 2 tests |
| CHK-M11-379a | tag length 65 allowed | the 64/65 row |
| CHK-M11-379b | `<` and `>` allowed in tags | 4 tests (3 TargetPicker, 1 RunScan) |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-273 | `npx vitest run src/components/TargetPicker.test.tsx` | PASS | 37/37 (with -274) |
| CHK-M11-274 | the same | PASS | round-trip and describe rows green |
| CHK-M11-275 | `npx vitest run src/components/ScanTable.test.tsx` | PASS | 5/5 |
| CHK-M11-375 (table, picker) | plants | PASS (red as required) | eslint exit 1 each; 3 and 2 tests red |
| CHK-M11-379 | plants (a), (b) | PASS (red as required) | 1 failed / 37; 4 failed / 54 |
