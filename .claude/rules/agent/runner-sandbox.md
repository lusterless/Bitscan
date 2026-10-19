---
paths:
  - "agent/cmd/bitscan-runner/**"
  - "agent/internal/runner/**"
  - "agent/cmd/bitscan-capread/**"
  - "agent/internal/capread/**"
  - "agent/internal/redact/**"
---

# Runner, capread helper and redaction

Spec: TS §3.5 (job execution) and §3.7 (privilege model and units). Default redaction patterns: TS §8.6. The units in TS §3.7 are part of the security design: implement against them, never around them.

## Runner (`bitscan-runner`)

- **Privileges:** runs as `bitscan-runner`, non-root (never uid 0), with only `CAP_DAC_READ_SEARCH`. Its unit stops it and its plugins writing outside the private `/tmp`, using devices, opening IP sockets, executing outside system binary paths, tracing processes, calling non-read-only D-Bus methods, gaining privileges or loading kernel modules (TS §3.7).
- **Socket:** systemd activates it from `/run/bitscan/runner.sock` (`root:bitscan`, 0660, in a root-owned 0755 directory that neither runner nor plugin can replace). Accept only peers with uid `bitscan` (`SO_PEERCRED`), and only whole jobs; there is no "run this string" call.
- **Job checks:** re-check the job's `agent_id` against `/var/lib/bitscan-agent/agent_id`, `pickup_by` (future, at most 25 h away) and the job ids seen in memory. These checks catch mistakes, not attacks; that is an accepted risk (TS §3.7).
- **Process hygiene:** set `PR_SET_DUMPABLE` to 0. Make every descriptor close-on-exec. Accepted: a plugin can signal the runner, which only restarts it (`Restart=always`).
- **Plugin environment:** each plugin gets only stdin from `/dev/null` and its stdout and stderr pipes, plus:
  - `PATH=/usr/sbin:/usr/bin:/sbin:/bin` and an otherwise empty environment;
  - `nice 10` and `ionice -c3`;
  - its own empty temp directory;
  - its `timeout_s`;
  - at most `max_parallel_plugins` running at once.
- **Running a plugin:** run it with `/bin/sh -c <execute>`. Move the runner into its own leaf cgroup (`supervisor`) and put each plugin in a fresh child cgroup. Pass a cancellable `context.Context` through each job.
- **Cleanup:**
  - when a plugin exits or times out, write `cgroup.kill` for its cgroup and delete its temp directory;
  - after each job, kill every process in the runner's subtree except itself, including a plugin that moved itself elsewhere in the subtree;
  - no plugin process may outlive its job.
- **Start-up:** refuse to start unless the host uses unified cgroup v2. Report `runner_unavailable` otherwise.
- **Captured per plugin** (TS §3.5): exit code, redacted stdout and stderr, start and end times, timed-out flag, truncated flag.

## Redaction (before anything leaves the runner)

- Read up to 1 MB of each stream.
- Apply every pattern in the job's `redaction_patterns` (RE2), replacing each whole match with `[REDACTED]` (no capture-group replacement). Redact a `BEGIN … PRIVATE KEY` line with no matching end line to the end of the buffer.
- Then truncate to 64 KB stdout and 16 KB stderr, and set `truncated`. Redacting first means a secret cut by the cap is never partly returned.
- Unredacted output must never reach the agent, the spool or the network.
- The manager seeds the five default patterns exactly as written in TS §8.6 (crypt hashes, PEM/OpenSSH private keys including a cut-off block, `bs[aeku]_` tokens, AKIA/ASIA key ids, `key=value` / `key: value` secrets).
- **Open spec question:** TS §3.5 makes cut-off private-key redaction runner behaviour, while TS §8.6 does it with default pattern 2 (`\z`); ask whether it must still apply when an admin removes that pattern.
- Test fixtures (TS §8.3; AKIA and ASIA key ids from TS §8.6 pattern 4):
  - must be redacted: a shadow hash, a full and a cut-off private key, `key=value`, a `bsa_` token, AKIA and ASIA keys;
  - must stay unchanged: normal output such as `install ok installed`, `PasswordAuthentication no`, `passwd: files`.

## capread helper (`bitscan-capread`)

- Off by default; installed with `--no-enable --no-start`. It is enabled only on the host itself (for example by configuration management); the manager never enables it.
- Runs as a `DynamicUser` with only `CAP_NET_ADMIN` and `CAP_AUDIT_CONTROL`.
- Plugins call `bitscan-capread nft_ruleset` or `bitscan-capread audit_rules`; the client forwards only the request name over `/run/bitscan/capread.sock`.
- Accepts only uid `bitscan-runner` (`SO_PEERCRED`), and only two request names: `nft_ruleset` runs `/usr/sbin/nft -j list ruleset`, and `audit_rules` runs `/usr/sbin/auditctl -l`.
- Each request runs by absolute path with an empty environment, a 10 s timeout and a 1 MB output cap, one at a time.
- It never takes a command line. Never give these capabilities to the runner or to plugins.

Tests (TS §8.3): Unit (redaction fixtures above), Agent (runner timeouts, output caps, redaction), Sandbox (every item in `.claude/rules/testing.md`), Security (expired, foreign and replayed jobs rejected by the runner); amd64 and arm64.
