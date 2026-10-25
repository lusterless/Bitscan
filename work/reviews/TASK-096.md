# TASK-096 REVIEW: debconf templates, config, install file, source format

Verdict: APPROVED (unconditional: the Ubuntu 22.04 run is PASS as well)

Reviewer: reviewer, 2026-10-24. One round (packaging metadata, speed rule 6). Not on the two-approval list.

Scope reviewed: `deploy/debian/templates`, `deploy/debian/config`, `deploy/debian/bitscan-agent.install` and `deploy/debian/source/format`, against TS §3.1 L158, L161, L164 and L175, REQ-107, REQ-106, #79, #81 (b) and the TASK-100 install.env ruling (decisions 2026-10-24).

TEST PASS on Ubuntu 24.04 and on the digest-pinned ubuntu:22.04 container (`work/reports/TASK-096-test.md`; CHK-M4-120, -121, -122, -120-u22, -121-u22). Debian 12 is NOT RUN because the user dropped it.

## Checks
1. Spec:
   - The four TS §3.1 L164 questions are present with the exact names.
   - `bitscan/enrol_token` is `password`, the other three are `string`, and none has a `Default:`.
   - The binaries go to `/usr/sbin` (L158) and the policy to `/etc/dbus-1/system.d/` (L161). The `debian/dbus/` source path matches the staging copy in `build-deb.sh:61`.
   - An upgrade or reinstall asks nothing (L175). `dpkg-reconfigure` asks only the token (#81 (b)).
   - When `install.env` is present, every question is skipped, so the file replaces debconf completely (decisions 2026-10-24, TASK-100 rule).
2. Security:
   - `config` reads only `$1` and the existence of two fixed paths. No environment input is read (REQ-107 (4)); CHK-M4-121 confirms this with environment-only inputs.
   - The token canary is found only in `passwords.dat` (root 0600), and never in `config.dat` or in config's output.
   - Nothing is validated or logged in `config`. Clearing the token stays in `postinst` (TASK-100).
3. Scope: 4 files, about 60 lines, all within the task. No edits in other areas.
4. Tests: `test_debconf.sh` runs in a scratch database that keeps the default config/passwords split, and it hashes the host's `/var/cache/debconf` before and after. It covers both preseed orders, a pty negative control, the reconfigure, upgrade and install.env branches, and the environment-only inputs. 6 of 6 plants are red. I accept the evidence as recorded; I did not run debconf on Windows.
5. Correctness:
   - `db_input … || true` handles the 30 return code for a question that is not shown.
   - Resetting `seen` on an empty URL or token lets an interactive `dpkg --configure` recover after a failed first install.
   - `3.0 (quilt)` fits the `-1` revision for a binary-only build.

## Findings
1. nit, `deploy/debian/config:35-36`. `ca_file` and the pin are asked at priority `low`, and `dpkg-reconfigure` later asks only the token. With the default priority (`high`), an interactive operator therefore has no prompt for a private CA or a pin, either at install time or afterwards. They have to preseed or use `install.env`. That is consistent with "optional", but TASK-107 (runbook) must say it. No code change.
2. Note for TASK-100 and TASK-107 (tester's observation; not a TASK-096 defect). A preseed line that types `bitscan/enrol_token` as `string` might leave the token in the 0644 `config.dat`. The runbook's preseed example must use `password`. I will check this in TASK-100 and TASK-107.
