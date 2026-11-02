# TASK-231 IMPL: runbook, README and changelog for the compliance runner

Implementer: impl-deploy-m10, 2026-10-30. REQ-258, REQ-255 (the version). Spec: TS §3 L152 (unified cgroup v2, `runner_unavailable`), §3.1 (package, units), §3.3 L224–L226 (spool, `last_error`, `spool_overflow`), §3.6 (`spool_max_mb`), §3.7 L276–L285 (runner), L484 (capread only on the host), L501 (`findmnt --task 1`), L503. PD-42. Depends on TASK-226, TASK-227 and TASK-228 (all reported). The text follows the built code: `cmd/bitscan-agent/main.go`, `cmd/bitscan-runner/main.go`, `cmd/bitscan-capread/main.go`, `internal/agent/loops/{compliance,pull,jobs,heartbeat}.go`, `internal/agent/runnerclient/client.go`, `internal/runner/hygiene_linux.go`, `internal/spool/{spool,manifest,overflow}.go`, `internal/agent/config/config.go`, and `manager/.../services/agents/heartbeat.py`. Low risk (docs), one approval.

## Files (+112 / −2)

- `deploy/debian/changelog` (+17): a new top entry `bitscan-agent (0.2.0~pre1-1) unstable; urgency=medium`, "Pre-release: compliance runner. Not a supported release.", dated `Fri, 30 Oct 2026 00:00:00 +0000`, with the same maintainer line as before.
- `deploy/runbooks/agent-install.md` (+88 / −2). Existing section numbers are unchanged, so the README's links to section 6 still work.
  - Intro: a paragraph on the pre-release `0.2.0~pre1-1`.
  - §1: a **cgroup v2** prerequisite: the `stat -fc %T /sys/fs/cgroup` check gives `cgroup2fs`; the usual cause and fix is `systemd.unified_cgroup_hierarchy=0`, then `update-grub` and a reboot.
  - §4: `bitscan-runner.service` stays inactive until the first compliance job.
  - §6: `0.1.0-1` upgrades in place to `0.2.0~pre1-1`.
  - **New §9, compliance jobs and the runner:**
    - the post-job checks and the `bitscan-runner started` line;
    - how `runner_unavailable` shows: each check without a result is ERROR, the agent's warn line, the reason words (`connect`, `timeout`, `broken`, `protocol`, `refused_<reason>`), heartbeat `last_error` `runner_unavailable: <reason>`, and the manager's `agent last_error` log line;
    - the runner's `start-up refused` reasons and the fix for each;
    - mount checks with `findmnt --task 1` or `/proc/1/mountinfo`.
  - **New §10, the capread helper:**
    - off by default; a plugin gets `bitscan-capread: not enabled`, exit 1;
    - enabled only by an administrator on the host, with no manager route, setting or job;
    - `enable --now` / `disable --now bitscan-capread.socket`, the socket file's owner and mode, a test as `bitscan-runner`, and `not_installed`;
    - `runner_helpers` `["capread"]` / `[]` and the `runner_helper_changed` alert.
  - **New §11, the result spool:**
    - the location, and that it holds only redacted output;
    - `spool_max_mb` 1–50 (default 50) and its refusal line;
    - overflow to `spool_overflow`, the 7-day drop at start (`expired` / `unreadable`, `last_error`), and `spool_bytes` (sent, but not stored by this manager, so the operator checks it with `du`);
    - **the spool cannot be opened** (the lead's request): inventory and heartbeats continue; every compliance job is refused with the logged lines and `last_error` values; a refused job fails at the manager 24 h after hand-out; what to check (directory, not a file or symlink, `bitscan:bitscan` 0700, a writable filesystem with free space) and the restart.
- `README.md` (+9): after the agent-package paragraph, a **"Compliance jobs (pre-release `0.2.0~pre1-1`, not a supported release)"** paragraph:
  - hosts now run compliance jobs, through the sandbox, host-side redaction and the spool;
  - the helper stays off until enabled on the host;
  - the results views and scores come in a later version;
  - a pointer to runbook §9–§11.

  For REQ-258's "results views arrive with M11", the text says "in a later version", because a milestone name would be a process note.

## Checks run (WSL Ubuntu-24.04)

- `dpkg-parsechangelog -l deploy/debian/changelog -S Version` → `0.2.0~pre1-1`. `-S Timestamp` → `1793318400`, and `-S Date` → `Fri, 30 Oct 2026 00:00:00 +0000` (2026-10-30 is a Friday).
- `dpkg --compare-versions`: `0.2.0~pre1-1` sorts above `0.1.0-1` and below `0.2.0-1`.
- `python3 deploy/tests/check_debian_meta.py`: **78/79**. The one FAIL is `changelog: version 0.2.0~pre1-1 is a release X.Y.Z-R (no ~)`. That is the expected conflict below. The weekday and strictly-decreasing-date checks pass.
- A grep of the added lines for `TASK-`, `REQ-`, `PD-`, `M10`, `M11`, `#<n>`, tester, reviewer, lead, `bs[aeuk]_…`, `password` and `TODO`: nothing found. The additions hold no token, password, internal id or process note.

## Known red until tester-m10's rewrite: `package.yml`

`deploy/tests/check_debian_meta.py` (tester-owned, run by `package.yml` L41) requires the first changelog entry to be a release `X.Y.Z-R` with no `~` (#90, M6). The PD-42 entry `0.2.0~pre1-1` breaks that rule. As the lead ruled ("PD-42 against check_debian_meta.py" in `work/decisions.md`), the entry stays as approved and the test is not edited here. **`package.yml` stays red until tester-m10's rewrite of that check lands.**

`release.yml` still refuses `~` versions, so this build can't be published by accident. `build-deb.sh`, `test_build_deb.sh` and `package.yml`'s reproducibility step read the version through `dpkg-parsechangelog`, so they follow the new entry.

## NOT RUN

- **The runbook walk on a sandbox VM** (REQ-258 (1), TP-M10-23). That's the tester's row. VM rows are held (decisions 2026-10-30, "M10 VM sandbox work stopped by the safety check"). The statements were checked against the code paths listed above, not on a host.
- `lintian` on a built `.deb` with the new changelog: the package jobs run it in CI.

## For the tester (TP-M10-23, CHK-M10-315)

Each runbook step below can be followed on a host with the built `.deb`:

- §1 `stat -fc %T /sys/fs/cgroup` → `cgroup2fs`.
- §4 `bitscan-runner.service` inactive before the first job.
- §9 `active` plus `bitscan-runner started` after a job.
- §9 `findmnt --task 1 -n -o OPTIONS --mountpoint /tmp` equals the host shell's output.
- §10 enable: socket active, `srw-rw---- root bitscan-runner`, `sudo -u bitscan-runner /usr/sbin/bitscan-capread nft_ruleset` prints JSON, then `["capread"]` in the next heartbeat. Disable: the socket file is gone, then `[]`.
- §10 with the helper off: `sudo -u bitscan-runner /usr/sbin/bitscan-capread nft_ruleset` → `bitscan-capread: not enabled`, exit 1.
- §11 `spool_max_mb: 51` refuses start-up with the quoted line.
- §11 a regular file at `/var/lib/bitscan-agent/spool` gives the quoted log lines, a refused compliance job and a continuing inventory.
