# TASK-143 REVIEW: structure check (BIT002, BIT016)

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-151, REQ-176. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/services/importer/structure.py` (208 lines, about 165 hand-written), per `work/reports/TASK-143-impl.md`. One file.

TEST: PASS (`work/reports/TASK-143-test.md`, 253/253 on Windows and WSL).
- All 50 `bit002/` fixtures give only BIT002 with `parsed` None, and the first finding on a manifest line.
- The two mis-cased fixtures had wrong manifest lines; the builder found it and the tester fixed the generator.
- These plants turned it red: CHK-M7-334 and 14 extra plants. One survived at first (a case-insensitive root, masked by an attribute finding). The tester added a test, and the plant is now red.

My re-run: included in the 677 unit tests (`test_bit_structure.py`); gates clean.

Spec read: SR §2, §2.1–§2.3, §4 (L250), §4.1 BIT002 and BIT016; TS §1.4 L43; #2, #10, #16, #105 (c), (d), (g); decisions 2026-10-27 L199 (the BIT016 ruling: only BIT001 and BIT002 stop the content rules). TASK-154 §4 step 3 is aligned with it.

## Checks
1. **BIT002 (SR §4.1).**
   - Names are canonical and case-sensitive, at the root and in all three container kinds.
   - Each element occurs once, in order; required elements must be present; there is exactly one `Family` (#10) and at least one `Plugin` (#16).
   - Unknown elements and attributes are refused; only `Policy/@formatVersion` and `Execute/@timeout` are allowed.
   - Non-whitespace text in containers (#105 (d)), children in leaves, and processing instructions (#105 (c)) are refused.
   - Only the first canonical occurrence is descended into, so one fault does not cascade.
2. **#2.** A missing `Operator` or `ExpectedResult` is not BIT002. The field is `None` for BIT010 or BIT011 in TASK-144. Order is still enforced when they are present.
3. **SR §4 order.** Any BIT002 means `parsed` is None and only BIT002 is reported, sorted by line with rule order kept (REQ-155 (5)); BIT016 is masked. BIT016 alone comes with a `ParsedPolicy`, so the content rules still report (L199).
4. **Findings (#105 (g)).**
   - Paths are `Policy/…` and `Policy/PluginsGroups/Plugin[n]/…`, with `@timeout` and `@formatVersion` at their element's line.
   - Names from the file appear only through `quote()` (64 characters, controls escaped), so `element` never holds file text.
5. **ParsedPolicy.** It holds raw, untrimmed values with their start-tag lines; `format_version` and `timeout` are None when absent.

## Findings
None blocking or should-fix.

1. nit, `structure.py:186`: the sort key `f.line or 0` would put a null-line finding first. Every finding here has a line, so it can't happen.
