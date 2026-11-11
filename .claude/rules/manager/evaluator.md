---
paths:
  - "manager/**/services/evaluator/**"
---

# Result evaluation

Spec: TS §4.5, SR §2.4 (operator definitions) and SR §1.1 (the canonical example's PASS/FAIL). Evaluation runs in the API process when each result arrives (TS §2.1), never on the agent.

- Implement exactly one pure function: `evaluate(operator, expected, stdout, exit_code, timed_out, truncated) -> 0 | 1 | 2`, where 0 = PASS, 1 = FAIL and 2 = ERROR (anything else is stored as 2). Unit-test every operator and every ERROR case.
- Evaluate against the job's `eval_spec`, the Operator and ExpectedResult recorded when the job was queued, never against the current plugin row. Each `scan_result` copies plugin name, Execute, Operator and ExpectedResult from the job's `eval_spec` and payload, and is stored with its verdict in one insert.
- Input is the redacted stdout returned by the runner (including `[REDACTED]` substitutions), so evaluation and re-evaluation see the same text. Only stdout is compared; stderr is kept as evidence.
- Normalise before comparing: CRLF becomes LF, then trim leading and trailing whitespace from both stdout and expected. The comparison is case-sensitive. TS §8.5 asks content authors to confirm these normalisation rules too: implement them as written and ask before changing them (`work/open-questions.md` #11).
- Operators (exactly these 14; TS §8.5 asks content authors to confirm them, so implement them as written and add none; `work/open-questions.md` #11):
  - text: `equals`, `not_equals`, `contains`, `not_contains`;
  - RE2 (multiline, a search: `^`/`$` anchor per line): `regex`, `not_regex`. Never use Python `re`;
  - numeric: `eq`, `ne`, `gt`, `ge`, `lt`, `le`. The whole trimmed stdout must be one decimal integer or float with an optional sign;
  - presence: `empty`, `not_empty`.
- **Decided** (`work/open-questions.md` #13, owner-approved): a number is `[+-]?[0-9]+(\.[0-9]+)?` with ASCII digits only: no exponent, `nan`, `inf`, `_`, hexadecimal, or leading or trailing point, so `.5` and `5.` are not numbers. Numbers compare as exact decimals, and the same grammar serves stdout and BIT012.
- The command's own exit code never decides PASS or FAIL. Return ERROR only for:
  - a timeout;
  - exit code 126 or 127, or 128 and above;
  - stdout truncated at 64 KB;
  - a numeric operator with non-numeric stdout;
  - a runner error (`spool_overflow`, `runner_unavailable`);
  - output over the caps. The manager rejects stdout over 64 KB or stderr over 16 KB as ERROR `oversize`, whatever the agent claims.
- `eval_detail` holds the evaluation detail, for example `stdout not numeric` or `spool_overflow` (TS §5.2); results over the caps are ERROR `oversize` (TS §4.5).
- **Decided** (`work/open-questions.md` #113, owner-approved): no. `truncated` means stdout was cut at 64 KB, and only that is ERROR `stdout truncated`; the runner cuts stderr at 16 KB without setting the flag.
- **Decided** (`work/open-questions.md` #12, owner-approved): result intake stores runner errors and oversize output as ERROR (`eval_code` 2, `eval_detail` the `error` value or `oversize`) before `evaluate()` is called. The `evaluate()` signature stays as specified, and these results stay ERROR on re-evaluation.
- Host compliance score = PASS ÷ (PASS + FAIL), excluding ERROR and *Not run* (plugins with no result), shown with the error count beside it. When PASS + FAIL = 0 the score is NULL, shown as "n/a".
- Re-evaluation (`POST /scans/{id}/reevaluate`, admin, TOTP session, audit-logged) adds `scan_result_reeval` rows against the policy's current version, each recording that `policy_version` and `reevaluated_by`; it is the only way a shown verdict changes, and only through the admin route. Views, CSV exports and scores use the latest re-evaluation for each job and plugin, otherwise the original result. The API returns both `result` and `original_result`. Plugins no longer in the current version keep their original verdict.

Tests (TS §8.3): Unit (every operator and every ERROR case, normaliser, evaluator; ≥ 85 % line coverage on `manager/services` = `manager/bitscan_manager/services/`), Integration (verdict uses the queued `eval_spec` after a catalog change; re-evaluation adds rows only; TS §4.5).
