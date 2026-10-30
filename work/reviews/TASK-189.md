# TASK-189 REVIEW: job and retry builder (pure)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-209 (1)–(4), (6), REQ-210 (1)–(4), REQ-212 (builder level). High risk, full rigor. **PD-39: this task also gets the user's second look** (it builds the commands every host runs), applied under the pre-authorisation on this approval and the clean TEST PASS.

Scope reviewed, per `work/reports/TASK-189-impl.md`: one new file, `manager/bitscan_manager/services/jobs/build.py` (172 lines). It reuses M8's `EvalSpec`, `build_eval_spec`, `parse_eval_spec` and `PluginSpec`, and M3's `PICKUP_WINDOW`. It edits no M8 or M3 file.

TEST: PASS (`work/reports/TASK-189-test.md`). 62/62 in r1; the r0 failure was a test fixture bug (a timeout over 600). The plants are red: CHK-M9-343, -347, -348, -349, -350 (a and b), -351 and -393. CHK-M9-344 (a retry built from the catalog) can't be planted here, because `retry()` takes no catalog input (its signature is pinned by CHK-M9-047). It is carried end to end to TASK-202 (CHK-M9-209).

Spec read: TS §3.5 L248, §6.5 L1165–L1182, §4.4 L566, L577, §4.1 L530, §4.5 L587, L603; SR §1.1; #117, #125 (a)–(c), (g), #126 (a), (b).

My re-run: `test_job_build.py` passes on Windows, and ruff is clean.

## Checks
1. **No ad-hoc command (security invariant, TS §3.3 L213, REQ-212).**
   - `execute` comes only from the `CatalogPlugin`s the queue service passes in, or, for a retry, from the original's stored payload.
   - No function takes command text from a request.
   - The payload is built from a fixed key set. A planted `operator` key is refused by the strict `ComplianceJob` (CHK-M9-347).
2. **Operator and ExpectedResult never sent (TS §3.5 L248).** They go only into `eval_spec`. A recursive walk of 5,000-plugin, 5-plugin and retry payloads finds no `operator`, `expected`, `name` or `eval_spec` key and no expected or display-name value (CHK-M9-040).
3. **Payload (TS §6.5).**
   - Exactly six keys, with `kind` set to `compliance`.
   - uuids are lowercase.
   - `pickup_by` is creation + 24 h in UTC, written `…Z` and truncated to the second (never later than the column, #125 (c)). A naive `created_at` is refused.
   - `redaction_patterns` holds the setting's values in order.
4. **`eval_spec` (#117).** It is `build_eval_spec` over the same plugins in the same order, with `name` set to the `v_plugin` display name. It round-trips through `parse_eval_spec`. The SR §1.1 row is exact (CHK-M9-045).
5. **Unstorable text (#125 (g), M8 carry).** Every `execute`, name, expected value and pattern is checked for U+0000 and lone surrogates before anything is built. The error is fixed and holds no canary.
6. **Retry (#126 (a), (b), TS §4.4 L577, §4.1 L530).**
   - It keeps only the missing plugins, in the original order, with the original's `execute`, `timeout_s` and `redaction_patterns` and the original's `eval_spec` entries.
   - It gets a new `job_id` and a new `pickup_by`.
   - A retry of a retry, an empty `missing`, or a `missing` uuid outside the payload raises.
   - The extra order guard between the payload and `eval_spec` is sound: it fails closed rather than pairing a command with the wrong verdict.

## Findings
None blocking or should-fix.

1. nit, `build.py:229-241`: `payload()` trusts that its `BuiltPlugins` came from `plugins_and_spec` (the unstorable-text check lives there). The only callers are TASK-193 and 198, and the frozen dataclass makes misuse unlikely. No change required; I'll confirm in TASK-198 that no `BuiltPlugins` is built by hand.
