# TASK-133 TEST: manager install runbook (TP-M6-03, G48)

Verdict: **FAIL** (round 1). Tester: tester-m6b. REQ-138, REQ-140. Host: fresh systemd `ubuntu:24.04` container `m6b-host` (`e2e/m6/manager-host.Dockerfile`, no published port) in WSL2. Release files: the wheel the tester built (`bitscan_manager-0.1.0-py3-none-any.whl`, sha256 48712d56…e506), the requirements copy, the four units, and SHA256SUMS. OpenBao and the sink are the test doubles (#93).

Written by `main` from the tester's text (the harness blocks the tester on report files).

Commands and totals:
- `python3 -I deploy/tests/check_runbook_bootstrap.py`: OK (CHK-M6-040).
- `python3 -I deploy/tests/check_runbook_text.py deploy/runbooks/manager-install.md`: OK, 17 sh blocks, 0 findings (CHK-M6-041); 3/3 text plants red.
- `python3 -I e2e/m6/manager_walk.py --tree /root/m6tb/tree --rel /root/m6tb/rel --work /root/m6tb --keep`: **59/61 rows passed, 2 failed** (CHK-M6-044 apt, CHK-M6-050 readyz), 0 errors, 0 skipped. Run 1 had 7 failures: 2 were these same product findings and 5 were test bugs (request_id is an int, a missing `X-Bitscan-Machine-Id` on the simulated agent's calls, sweep-diff parsing, a maintain-output check). Run 2 is the one counted.
- `bash deploy/tests/check_manager_host.sh m6b-host /root/m6tb/tree /root/m6tb/secrets`: **19/19 passed** (after two check-script bugs were fixed: an `[unprintable]` LoadCredential read, and root's systemd lines counted as CLI uids).
- `bash e2e/m6/plant_host.sh m6b-host /root/m6tb/tree /root/m6tb/secrets`: **5/5 plants red** (CHK-M6-323, -324 ×2, -325, -326); the clean host was 19/19 before and after.

Acceptance criteria:
- REQ-138 (1) every step behaves as written: **FAIL**. §3 apt install fails on a fresh host without `apt update` (CHK-M6-044). §9 curl races the start-up (CHK-M6-050). Every other step behaves as written (CHK-M6-043, -044a, -045 to -052).
- (2) the host meets REQ-140: PASS (CHK-M6-049, -053 to -058).
- (3) the Bootstrap block is byte-identical: PASS (CHK-M6-040; plant CHK-M6-323 red).
- (4) paths, owners and modes equal TS §8.7, and non-TLS is refused for all three roles: PASS (CHK-M6-045, -046, -047; plant -324 red).
- (5) no secret on a command line or in history: PASS (CHK-M6-041, -044a psql history, -047 files created empty at 0600 first).
- (6) no secret, task id or process note: PASS (CHK-M6-041).
- REQ-140 (1) to (7): PASS. (7) was checked on the install-walk journal; the after-end-to-end sweep belongs to W4.

Failures (expected vs actual):
1. CHK-M6-044. Expected `sudo apt install postgresql-16 postgresql-16-debversion python3.12 python3.12-venv` rc 0 on a fresh host. Actual: `E: Unable to locate package postgresql-16` (×4 packages), because the package lists are empty and no `apt update` comes first. Diagnosis: a runbook omission. Fix: `sudo apt update` before the install.
2. CHK-M6-050. Expected the §9 block to print `active` and `{"status":"ok"}`. Actual: `curl: (7) Failed to connect to bitscan-mgr.test port 8443`; the same curl 1.5 s later is OK. Diagnosis: `enable --now` returns when the process starts, before it listens. Fix: tell the operator to wait or retry.

Notes: N1 and N2 are optional wording points. O1 is the /run/lock observation on the spec's unit, not a TASK-133 matter. Environment notes are in the report rows (the rshared entrypoint, the trust stores, the Windows UI build, the test doubles).

Tester's notes as sent:
- N1 (§8): the "maintenance run prints `created <name>` or `nothing to do`" text goes to `journalctl -u bitscan-manager-maintain`, not to the §8 block's terminal. Either name the journal or add the command.
- N2 (§5): re-running the first §5 block on an installed host empties manager.env and all six secrets (`install … /dev/null` onto existing files). A one-line "only on a fresh host" warning would cover it.
- O1: under the verbatim bitscan-manager.service, the service user can still write the host's /run/lock (tmpfs, mode 1777); /dev/shm is private. The same happens with the units' sandbox set in a transient unit on the WSL distro's own systemd 255, outside any container, so it is systemd behaviour: ProtectSystem=strict does not make /run/lock read-only. Nothing persistent is writable beyond the two ReadWritePaths, and the manager wrote nothing there.

## Revision 1: PASS
Only deploy/runbooks/manager-install.md changed (sha256 d48da79c…0869). It was walked on a new, fresh `m6b-host` (new container, new secrets and PKI).
- `check_runbook_bootstrap.py`: OK, Bootstrap unchanged (CHK-M6-040-r1).
- `check_runbook_text.py manager-install.md`: OK, 17 sh blocks, 0 findings (CHK-M6-041-r1).
- `manager_walk.py` (r1 runbook): **59/59 rows passed**, 0 failed, 0 skipped. Two fewer rows than round 1: the apt-update fallback row and the separate curl-retry row no longer apply.
- `check_manager_host.sh`: **19/19 passed** on the r1 host.
Results:
- F1 is fixed: §3 `sudo apt update` + `apt install` gives rc 0 on the fresh host (CHK-M6-044-r1).
- F2 is fixed: the §9 block run as one script printed `active`, then two `curl: (7) … Couldn't connect` tries, then `{"status":"ok"}`, rc 0 (CHK-M6-050-r1).
- N1 is fixed: the §8 block now shows `bitscan-manager[…]: nothing to do` from the maintain journal.
- N2's warning is present. §5 still creates every file empty at 0600 before content.
The mutation rows CHK-M6-323..326 were not re-run: they test the checkers, which r1 did not touch. O1 stands as an owner note.
REQ-138 (1)–(6) and REQ-140 (1)–(7) (the walk-scope part of (7)): all PASS.
