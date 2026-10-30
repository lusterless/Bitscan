# TASK-190 REVIEW: intake plan (pure)

Verdict: APPROVED (round 2)

Reviewer: reviewer-m9, 2026-10-30. REQ-214, REQ-215, REQ-216 (plan level). High risk, full rigor. **PD-39: the TS §8.2 second approval is now due.** This review is APPROVED with no open blocking or should-fix finding, and TEST is a clean PASS, so the pre-authorisation applies.

Scope reviewed, per `work/reports/TASK-190-impl.md`: one new file, `manager/bitscan_manager/services/jobs/intake_plan.py` (159 lines). It reuses M8's `result_verdict`, `classify`, `EvalSpec` and `Detail` and edits no M8 file. The code is unchanged since round 1.

TEST: PASS (`work/reports/TASK-190-test.md`): r1 110/110, r2 (W) 110/110, and r2-L (Windows) 169/169 with 0 errors. All 9 plants are red, now including CHK-M9-331 (a) with its evidence (9 failed).

Spec read: TS §6.1 L1071, §4.4 L578, §4.5 L587, L596, L599, L603; #12, #116 (d), #121, #124 (a), (b).

My re-run (round 2, Windows venv): `test_intake_plan.py` and `test_job_build.py` give 169/169. ruff is clean.

## Code checks (all pass)
1. **Membership first (#124 (a), TS §6.1 L1071).** Every item is checked against both the `eval_spec` and the payload before any row is built. One foreign plugin refuses the whole batch with a fixed message.
2. **First result wins (#124 (b), TS §4.4 L578).** `existing` (the job and its sibling, from the caller) and earlier items of the batch are duplicates. The first item in batch order wins, and `rows + duplicates = items` (CHK-M9-083). The lock and the sibling lookup are checked in TASK-195 and 199.
3. **Verdict and caps (#121 (b), #116 (d), #12).** `result_verdict` runs on the received text, so the caps are measured as sent. An `oversize` result is stored with `""` for both streams.
4. **#121 (c) replacement and the recompute departure.**
   - U+0000 and surrogates become U+FFFD.
   - When stdout changed, the code re-runs `classify()` on the stored text, only for compared results (no runner error, not `oversize`).
   - I agree with the departure from the plan's "proxy through `result_verdict`" wording. A proxy would measure the caps again on the longer replaced text, against #121 (b) and #116 (d). `classify()` on the stored text is what M8's re-evaluation does for non-`INTAKE_DETAILS` rows, so intake and re-evaluation agree (L596).
   - This implements the approved #121 answer; no new ruling is needed.
5. **Snapshots (TS §4.5 L603).** The name, operator and expected value come from the `eval_spec` entry, and `execute` from the payload, never from the catalog. The rest is kept as sent.
6. **No output in logs or errors.** There is no logging and the errors carry fixed text (CHK-M9-065).

## Findings
1. should-fix, round 1, **resolved**: `test_intake_plan.py::test_caps` used 65 KB strings as test ids, which broke `PYTEST_CURRENT_TEST` on Windows (10 errors, G66 is local too). It now has short `ids=`, and `test_job_build.py`'s 16,384-character parameter got the same fix. I confirmed 169/169 on Windows.
2. should-fix, round 1, **resolved**: the CHK-M9-331 (a) evidence was `PENDING_331A`. It is now recorded (9 failed, `test_caps_are_measured_on_the_received_text` …).
