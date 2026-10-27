# TASK-141 REVIEW: safe `.bit` parser (BIT001)

Verdict: APPROVED (revision 1)

Reviewer: reviewer-m7, 2026-10-27. REQ-150, REQ-176, REQ-180. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/services/importer/parse.py` (237 lines, about 175 hand-written), per `work/reports/TASK-141-impl.md` (including Revision 1). One file.

TEST: round 1 FAIL, then PASS at rev 1 (`work/reports/TASK-141-test.md`).
- The round-1 failure: UTF-16 without a BOM parsed clean, because expat auto-detects UTF-16 despite `encoding="utf-8"`.
- 276/276 (Windows and WSL), plus fuzz 4/4 (10,500 inputs).
- These plants turned it red: CHK-M7-320, -321, -322, -323, -347 and nine extra plants. Three equivalent mutants are named with reasons.

My re-run on Windows: `test_bit_parse.py`, `test_bit_values.py`, `test_bit_structure.py` and `test_bit_fuzz.py` gave 677 passed. Ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` are clean (274 files).

Spec read: TS §4.1 L516–L517, §8.1 L1251; SR §4, §4.1 BIT001; plan `work/plans/TASK-141.md` (D1, with §4a as built and accepted by the planner); #57, #105 (a)–(g). Security invariants: defusedxml only, no DTD or external entities, no `re`.

## Checks
1. **defusedxml only (invariant, TS §4.1).**
   - One `DefusedXMLParser(forbid_dtd=True, forbid_entities=True, forbid_external=True)`, fed the buffer once.
   - Nothing from `xml`, `lxml` or `re` is imported (AST test; ruff TID251).
   - The tests prove each of the three layers on its own, by planting the other two away: no canary read, no listener connection, under 64 MiB.
2. **Encoding, before XML (D1, #105 (f)).**
   - Empty and over 5 MiB inputs are caught first (the parser is never built).
   - UTF-16 and UTF-32 BOMs are refused.
   - Any NUL byte is refused (rev 1). That is safe, because U+0000 is never an XML 1.0 character, and it closes expat's encoding auto-detection.
   - Then a strict UTF-8 decode, with the line of the first bad byte.
   - The declaration's `version` and `encoding` are read with byte operations.
3. **Caps (#105 (a), plan §4a).** Exceeding 35,014 elements gives BIT002; nesting over 16, BIT002; over 8 attributes, BIT002; the 5,001st `Plugin` gives BIT017 (TS L517). Each boundary is tested both ways.
4. **Namespaces (§4a (1)).** expat runs with namespaces on, so `start_ns` and unbound-prefix errors give one BIT002 from the parser (#105 (c)).
5. **Findings.**
   - Exactly one finding or a tree, never both.
   - `element` is null; messages are fixed text. Expat's undefined-entity text, which would name the entity, is not quoted.
   - Lines come from expat's `CurrentLineNumber`, checked against an independent scanner on all valid fixtures and both samples.
   - Programming errors propagate (#98 (j)), never as a pass.
6. **Tree.** CDATA and text are joined in order and comments dropped. Processing instructions are recorded in `pi_lines` for TASK-143. Attribute order is kept. A 5 MiB file parses in about 0.03 s with a 13 MiB peak.

## Findings
None blocking or should-fix.

1. nit, `parse.py:175`: a declaration that `_pseudo_attributes` cannot scan is left to expat. That is safe, because the parser is created with `encoding="utf-8"` and NUL bytes are already refused; the 7 non-UTF-8 declaration tests confirm it. No change.
