# TASK-096 TEST: debconf templates, config, install file, source format

**Verdict: PASS** on Ubuntu 24.04 (W) and Ubuntu 22.04 (W-c, `ubuntu:22.04` pinned by digest `sha256:0a9887931b0e38af2e3487ed39e29436b0535c4f3f52e57745baaf79d1898956`, disposable container). Debian 12 is NOT RUN because the user dropped it from v1.

REQ-107, REQ-106; TS §3.1 L158, L161, L164; #81 (b). Tester: tester-m4b. One round (packaging metadata, standard rigor).

## Commands
- W (root): `bash deploy/tests/test_debconf.sh` (new) → 68/68 passed, 0 failed, 0 errors, 0 skipped, plus the host-isolation check (host `/var/cache/debconf` unchanged) PASS.
- W-c ubuntu:22.04 (root, `BITSCAN_TEST_DISPOSABLE=1`): `bash deploy/tests/test_debconf.sh /repo` → 68/68 passed, 0 failed, 0 errors, 0 skipped (rows CHK-M4-120-u22, -121-u22).
- L and W: `python -I deploy/tests/check_debian_meta.py` (extended) → 75/75 passed.
- Development runs with my own test bugs (fixed in the test, not product defects): run 1 55/64 (template enumeration in the perl helper; confmodule sends `GO ` with a trailing space), run 2 66/68 (debconf reports a missing Default as ""), run 3 68/68.
- Plants, in throwaway copies, each after a 68/68 or 75/75 control: 6 of 6 red (rows CHK-M4-120 to -122).

## Acceptance criteria
- A preseeded non-interactive configure sets all four questions: PASS, CHK-M4-121 (both preseed orders; values exact and seen; no prompt in the pty probe).
- `bitscan/enrol_token` is stored only in `passwords.dat`: PASS, CHK-M4-120 (Type password) and CHK-M4-121 (canary only in `passwords.dat`, root 0600).
- The install file maps the three binaries to `/usr/sbin` and the policy to `/etc/dbus-1/system.d/`: PASS, CHK-M4-122.
- Extra (REQ-107 (4), #81 (b), TS L175): environment variables are ignored, reconfigure asks only the token, upgrade asks nothing, `install.env` suppresses the questions. All PASS (CHK-M4-121 evidence).

## New test files
`deploy/tests/test_debconf.sh`, `deploy/tests/debconf_protocol.py`; extended `deploy/tests/check_debian_meta.py` (`check_install`, `check_source_format`).

## Observation for TASK-100 and TASK-107 (not verified, not a TASK-096 defect)
Plant p1 showed that debconf stores a value according to the template's type when it saves. A preseed line that declares the token as `string` before the package's templates exist might therefore leave the token in the 0644 `config.dat`. The runbook's preseed example must use `password`. I will check this ordering in TASK-100 or TASK-107.
