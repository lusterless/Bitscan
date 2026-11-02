## Summary

Milestone M10, the compliance runner. Agents now run the compliance jobs M9 queues. `bitscan-agent` hands each job to `bitscan-runner` over its systemd-activated socket. The runner executes each plugin in its own cgroup with a sandboxed environment, redacts the output before truncating it, and returns the results. The agent spools them on disk and posts them to the manager. The optional `bitscan-capread` helper gives plugins read-only access to the nftables ruleset and audit rules.

Implements TS §3, §3.3, §3.5, §3.7, §8.4 and §8.6 for REQ-234 to REQ-263 (TASK-209 to TASK-229 and TASK-231). No manager product change, no migration and no agent-contract change. New dependency: `golang.org/x/sys` (PD-41). Package version `0.2.0~pre1-1`: a pre-release with no tag, which `release.yml` refuses to publish (PD-42).

## Changes

- **Runner protocol:** one connection per job, carrying length-prefixed JSON frames. A second job is refused `busy`. The peer must be uid `bitscan` (SO_PEERCRED), and only whole jobs are accepted, so there is no command call (#130).
- **Job checks in the runner:** `agent_id`, `pickup_by` (at most 25 h ahead) and an in-memory replay set. These catch mistakes, not attacks (TS §3.7).
- **Running a plugin:**
  - The runner moves itself into a `supervisor` leaf cgroup, and each plugin gets its own child cgroup.
  - Each plugin runs as `/bin/sh -c` with stdin from `/dev/null` and an empty environment apart from `PATH`, at nice 10 and I/O class idle, with its own temp directory and its timeout.
  - At most `max_parallel_plugins` run at once.
  - `cgroup.kill` runs at exit. After each job the whole subtree is swept, so no plugin process outlives its job.
- **Process hygiene:** `PR_SET_DUMPABLE` 0 and close-on-exec on every fd. Start-up refuses cgroup v1, the wrong capability sets, or a missing systemd socket.
- **Redaction (RE2):** each stream is read up to 1 MiB, every pattern is replaced with `[REDACTED]`, and a cut-off private key is redacted to the end. Only then is output truncated to 64 KiB stdout and 16 KiB stderr. The patterns cross-check span for span against the manager's google-re2.
- **Spool:** writes are crash-safe (tmp, fsync, rename, dir-fsync) and the spool holds only redacted results. On overflow the oldest results become `spool_overflow` markers first. An in-flight batch is released during back-off, so the oldest results are still the ones dropped first and every plugin is still reported (TS §3.3).
- **Results sender:** batches of at most 50 items and 1.5 MiB, start notice first and the final flag last. Each retry is rebuilt as a fresh batch.
- **capread:** a DynamicUser helper with `CAP_NET_ADMIN` and `CAP_AUDIT_CONTROL` only. It answers two fixed requests, `nft -j list ruleset` and `auditctl -l`, with an empty environment, a 10 s timeout and a 1 MiB cap, and accepts uid `bitscan-runner` only. It is off by default.
- **G2 (inventory can't be disabled):** a missing compliance handler, or a spool that can't be opened, refuses compliance jobs and sets `last_error`, while inventory keeps running.
- **Lint (REQ-256):** process execution is allowed only at the three named sites.
- **CI (agent.yml):** the M0 stub step is replaced by start-up refusal checks under strace. The runner's delegated cgroup tests run as `bitscan-runner` under `systemd-run -p Delegate=yes` on ubuntu-22.04 and ubuntu-24.04.
- **Docs:** the runbook gains runner, capread and spool sections; the README gains one paragraph; the changelog gains `0.2.0~pre1-1`.

## Decisions (`work/decisions.md`, 2026-10-30 and 2026-11-01)

- Open questions #130 to #143 and PD-41 to PD-45 took the planner's recommended answers. Builder and reviewer questions took the safer option, each recorded.
- **User decisions (2026-11-01):**
  - **VM sandbox checks are a named exception:** G76, the VM half of G78, G79, the VM plant halves, TASK-230 (sandbox CI), TASK-231's runbook walk and G41 are not run. They must run before any M11 code and before any release.
  - **CHK-M4-223 is rewritten.**
  - **Nits:** every recorded nit is accepted as built.
  - **Spec notes:** three are recorded for the owner, with no spec edit:
    - the 1 MiB read-limit fragment (TS §3.5);
    - #140's in-flight reading (TS §3.3);
    - #133's always-on cut-off key rule.
  - **G38** is evidenced by this PR's `package.yml` run.
- **Older checks changed by requirement** (old to new listed in the reports; no gate lowered):
  - CHK-M4-223 → CHK-M10-271;
  - CHK-M4-100 → CHK-M10-272;
  - CHK-M6-100 → CHK-M10-318, plus a new CHK-M10-319 that pins `release.yml`'s `~` refusal;
  - the PD-45 compliance rows replace the #74 placeholder rows.
- **TS §8.2 second approval** (user, pre-authorised) for TASK-209 to TASK-228. One approval each for TASK-229 and TASK-231.

## Testing

- **M10 gate PASS** (`work/reports/M10-gate-test.md`; closing review `work/reviews/M10-closing.md`, APPROVED):
  - agent suite in WSL with `-race`: 1335/1341, 6 skipped;
  - the delegated runner rows as `bitscan-runner`: 37/37;
  - G36: 64/64;
  - full manager suite: 11,211/11,211; services coverage 98.53 %;
  - G1–G11, G17, G35, G37, G39, G40 and G71–G75 green;
  - mutation table CHK-M10-320..393: 74/74 red.
- **The runner and capread under their verbatim units in WSL:** all 37 service and 5 socket directives for the runner, and all 23 and 5 for the helper. Shown there:
  - `agent_id` is read through the 0700 state dir;
  - the capability sets are exact;
  - 8 plugins run under TasksMax and MemoryMax;
  - the socket has its mode and owner;
  - nft output through the helper is byte-equal to root's.
- **Defects found and fixed before merge:**
  - an in-flight batch blocked spool overflow during an outage (TASK-220 and TASK-223 r1);
  - a plugin that left its cgroup hung the runner past its timeout (TASK-224 r1);
  - dropped capture errors could send cut output as complete (TASK-224 r2);
  - the runner's main thread was left at nice 10 (TASK-221 r2).
- **Windows:** 25 pre-existing M4 rows fail. M4's state store fsyncs a directory, which Windows refuses, and the TLS chmod row is Windows-only. The agent targets Ubuntu only.
- **First runs in this PR's CI:** the delegated rows on 22.04 (systemd 249, kernel 5.15), and `package.yml`'s G38 upgrade test.
- **Per-task records:** `tests/m10/report.md`.

## Follow-ups

- **Before any M11 code:** the VM sandbox checks on `bitscan-u2204` and `bitscan-u2404`, plus G41, in a fresh session in default permission mode. On a real host this covers:
  - the cgroup v1 boot;
  - `/proc/<runner>/mem` returning EACCES under `~@debug`;
  - the 22.04 seccomp answer for `fchmodat2`;
  - `auditctl`;
  - the `.deb` install;
  - the first compliance run against the real manager.
- **Post-M10 nits:** the full list is in the closing review. Examples: spool sequence reuse after a failed dir-fsync; a 25 h cap on remembered refused job ids; a start-up check that `/tmp` is a private mount; the version check in `test_build_deb.sh` covering all three binaries; the runbook's placeholder token tripping `check_runbook_text.py`.
- **Carried over:** TASK-146 (BIT102 review and r2), to a fresh session. **M11:** the read views, CSV, re-evaluate and the UI.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
