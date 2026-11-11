# TASK-259 TEST: PASS

Tester: tester-m11d, 2026-11-09. Docs (`deploy/runbooks/agent-install.md` L7, L178). Walked with TASK-252 and TASK-253; evidence in `work/reports/TASK-252-test.md`.

| Check | Result | Evidence |
| --- | --- | --- |
| L7 and L178 agree with the changelog | PASS | L7 names `0.2.0~pre2-1`, the changelog's top entry (`dpkg-parsechangelog` → `0.2.0~pre2-1`). L178: `dpkg --compare-versions 0.1.0-1 lt 0.2.0~pre2-1` and `0.2.0~pre1-1 lt 0.2.0~pre2-1` are both true, so both hosts upgrade in place as written. The real package upgrade is G38 at the M11 gate |
| CHK-M11-382 (this file) | PASS | `check_runbook_text.py`: the same two known findings as before (L79, L123, the `bse_REPLACE…` placeholders), nothing new |
| No other `pre1` mention | PASS | grep: only L178's `0.1.0~pre1-1 sorts below 0.1.0-1` (unchanged) and the upgrade sentence |
