# TASK-105 TEST: package CI workflow and lintian overrides
**Verdict: PASS** (local evidence). The GitHub run of package.yml is NOT RUN until pushed. Debian 12: NOT RUN (dropped by the user). REQ-111, REQ-109; TS §3.1 ("must pass lintian"), §8.3. Tester: tester-m4b. One round (CI and metadata) after fix rounds 1 and 2.

Commands: actionlint v1.7.7 and greps (CHK-M4-250); systemd-analyze verify on the packaged units, u22 and u24 (CHK-M4-251-units); lintian 2.117 on 24.04 through `test_build_deb.sh --deb … lintian` (CHK-M4-205); lintian plants L1 to L3.

Criteria:
- lintian passes with every override reasoned and used: PASS (CHK-M4-205, plants red).
- Workflow: Ubuntu-only, amd64-only, every action pinned by SHA, timeouts set, calls the tester's scripts: PASS (CHK-M4-250).
- Each CI job's check is red on its planted fault: proven locally (CHK-M4-251 evidence row); the CI run itself is NOT RUN.

The D-Bus overrides follow the 2026-10-25 ruling (the policy is verbatim TS §3.7 and must not change).
