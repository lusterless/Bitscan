# TASK-138 TEST: `RemoveOnStop=yes` on the capread socket

Verdict: **PASS** (tester-m6c, 2026-10-26). Rigor: full. The unit belongs to the agent's helper sandbox (TS §3.7), so TS §8.2 needs two approvals.

Written by `main` from the tester's text (the harness blocks the tester on report files).

Scope: user decision 2026-10-26 (TASK-138), a recorded deviation from the verbatim TS §3.7 unit (L437–L449). The shipped `bitscan-capread.socket` is its TS block plus `RemoveOnStop=yes` after `SocketMode=0660`, so systemd removes `/run/bitscan/capread.sock` when the socket stops and the agent's next heartbeat reports `[]` (#30). Impl report: work/reports/TASK-138-impl.md.

Tester change: `deploy/tests/check_units_verbatim.py` gets one documented exception (a `DEVIATIONS` table and `apply_deviation()`): exactly that line, at exactly that place, in that unit only. A guard stops the check if the TS block changes under it.

| Criterion | Evidence | Rows |
| --- | --- | --- |
| Every other line and unit stays byte-identical to TS | all/agent/manager rc 0, IDENTICAL ×10 | CHK-M6-160, -167 |
| The exception admits only the one line | 10 unit plants red (second line ×2, moved, removed, `=no`, other line, other unit, duplicate, trailing space, CRLF); 2 spec guards red; control green | CHK-M6-161 |
| `systemd-analyze verify` | clean on 24.04 (9 units + 4 installed manager units) and 22.04 (5 agent units); an invalid value is reported | CHK-M6-162 |
| New `.deb`, reproducible | two builds identical; repro 14/14; new RC d98ef8c3…; the only change from 3b5c98a0… is the one line (+ md5sums) | CHK-M6-163 |
| lintian | test_build_deb.sh 93/93; no E/W/P | CHK-M6-164 |
| Maintainer scripts on 22.04 and 24.04 | 567/567 each, including pre1 → 0.1.0-1; capread units stay disabled after install | CHK-M6-165 |
| Runtime: enable creates the file, disable removes it | new RC on 24.04 and 22.04: present → absent on disable and on stop; old RC control: file stays (the CHK-M6-261 defect) | CHK-M6-166 |

Commands (WSL root, /root/m6tc, throwaway m6c- containers, no port): `check_units_verbatim.py` + plants (L); `units_verify.sh`; `deb138.sh`; `maint138.sh maint`; `maint138.sh rt` (24.04 + 22.04 variant). Scripts: C:/Users/kaiquan.koh/Documents/m6c-scratch/.

Counts: verbatim 3/3 modes green; plants 12/12 red; verify 3/3; test_build_deb 93/93; repro 14/14; maintainer scripts 567/567 × 2; runtime 3/3 (new u24, new u22, old control as expected).

Not run here: the VM re-run of CHK-M6-261 on the new RC (tester-m6, u2404 session 2), shellcheck inside the containers (not installed; scripts unchanged since M4), and CI (no push). G41 on the new RC follows in the gate rows.

Lead's note: the VM re-run CHK-M6-261-r on the new RC passed in u2404 session 2 (W4 log `m6-tester-scratch/w4/s3.txt`): enable gives `['capread']` and entry 1; `disable --now` gives `[]` and entry 2, the socket file is gone, and both entries reach the sink in +0.01 s.
