# TASK-106 TEST: bitscan-agent main
**Verdict: PASS** (CHK-M4-264, the run under the verbatim unit from the installed .deb, is at the M4 gate, as agreed). REQ-103, REQ-096; TP-M4-21, CHK-M4-260 to -263, -265; mutation rows CHK-M4-339 and -346 (main). Full rigour (agent).
Commands: `bash e2e/agent_binary.sh <repo> <work>` (root, WSL Ubuntu 24.04; private mount namespace with overlayfs on /etc and /var/lib and tmpfs /tmp; e2e/fake_manager.py with a test CA); `tester3_m4_plants.py t106`.
Counts: 102/102 checks; 10/10 plants red.

| Criterion (TASK-106 / REQ-103, REQ-096) | Evidence |
| --- | --- |
| Against a fake manager the binary enrols (bse_, no machine-id, six body keys), heartbeats, rotates, pulls and uploads (job_id, gzip, list_sha256 recomputed, count = dpkg-query -W) | CHK-M4-260 |
| SIGTERM during a heartbeat, a pull and an upload: exit 0 within 5 s, state complete, no .tmp | CHK-M4-261; SIGTERM-not-handled plant red |
| No token in stdout or stderr (canary sweep); stdout empty | CHK-M4-262; CHK-M4-339 plant red |
| Start-up refusals (http URL, unknown key, bad machine-id, neither token file, no version, missing ca_file, corrupt seen_jobs.json): exit 1, no manager call, one line naming the cause | CHK-M4-263; no-version, refusal-exit-0, seen-error-ignored and no-credentials plants red |
| A refused enrolment (401, 403) and a later 401 leave the process idle until SIGTERM (#81 (a)); the enrol-401 line says a new enrolment token is needed | CHK-M4-263; refused-enrolment-exits and 401-exits-process plants red |
| No listening socket; nothing outside the state dir and the test's agent.yaml changes | CHK-M4-260; CHK-M4-346 and writes-outside-state plants red |
| The start line shows the build version | CHK-M4-265 |
| Under the verbatim unit (W, systemd, user bitscan) | CHK-M4-264: NOT RUN here; runs at the M4 gate from the installed .deb |

Rows: CHK-M4-260..263, -265 (102/102) and CHK-M4-260..265-mut.
