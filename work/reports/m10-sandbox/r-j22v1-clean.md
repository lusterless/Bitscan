# Bitscan sandbox suite: cgroup v1

Host Ubuntu 22.04.5 LTS, kernel 5.15.0-198-generic, systemd 249, cgroup tmpfs, package 0.2.0~pre1-1. 2026-11-02 22:37:07 UTC.

**1 PASS, 0 FAIL, 35 NOT RUN** of 36 rows.

| Row | Check | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M10-214 | cgroup v1 host: the runner refuses to start | PASS | no accepted frame ([] timeout) ok; nothing executed ok; journal start-up refused (1) ok / time=2026-11-02T22:37:04.474Z level=ERROR msg="start-up refused" reason="runner: refusing to start: /sys/fs/cgroup is not cgroup2" |
| CHK-M10-221 | bitscan-runner.service inactive until the first job, active after it (REQ-255 (4)) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-200 | systemd-analyze verify of the installed units as written, with the real binaries | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-201 | a plugin cannot write outside its private /tmp and /var/tmp | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-202 | no AF_INET, AF_INET6 or AF_PACKET socket; no IP reachable | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-203 | no exec of a copy of true in /tmp, /var/tmp or /home; /usr/bin/true runs | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-204 | blocked sockets (Docker, containerd, snapd, journald) unreachable; an open test socket is reachable | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-205 | no ptrace or process_vm_readv of the runner; its mem and environ give EACCES | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-206 | the runner's socket is not among a plugin's fds; runner.sock can't be replaced, renamed or unlinked; nothing can be created in /run/bitscan | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-207 | D-Bus: state-changing calls refused by the bus policy; read-only calls work | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-208 | no privilege gain, module load, clock or hostname change, or block device open | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-209 | a plugin can read /etc/shadow (CAP_DAC_READ_SEARCH); its CapEff and CapBnd are 0x4 | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-210 | cgroup layout: each plugin in its own p-<n>, the runner in supervisor, only supervisor left (REQ-238 (2)-(4)) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-211 | plugin environment, fds, niceness 10, I/O class idle, temp dir, uid, parallel cap (REQ-239) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-212 | no plugin outlives its job (REQ-240 (1)-(10)) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-213 | exit codes on the host: exit 3 -> 3, kill -9 $$ -> 137, unknown command -> 127 | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-215 | planted unit with CAP_SYS_ADMIN: the runner refuses to start (REQ-237 (4)) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-216 | peer check: root and a member of group bitscan closed without a reply; a non-member gets EACCES | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-217 | capread with the real nft and auditctl; helper CapEff 0x40001000 under a dynamic uid; runner and plugins 0x4 | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-218 | helper disabled: exit 1 and the fixed line; file-based checks still work | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-219a | capread units disabled and inactive after install (REQ-254 (1), first part) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-219b | runner_helpers [] -> ["capread"] -> [] in the heartbeat | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-223 | clone3 under the verbatim unit: ENOSYS or not (fact for the owner) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-344v | redaction before truncation at the 64 KiB boundary, at the runner reply (the agent forwards it as is) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-222 | every bits/samples plugin under the sandbox: no error, timeout or 126/127; stdout equal to root's outside (#143) | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-280 | an expired job (pickup_by passed) sent straight to the socket is refused and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-281 | a foreign job (another agent_id) is refused and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-282 | a replayed job (same job_id) is refused and runs nothing the second time | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-283 | a wrong peer (root, a member of group bitscan) is closed without a reply and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-284 | a bare string request is refused malformed and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-285 | a plugins list without a job is refused malformed and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-286 | a second request frame on one connection is never run | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-287 | an inventory job is refused not_compliance and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-288 | an unknown key ("command") beside the job is refused and runs nothing | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-289 | capread refuses every name but its two, runs nothing for them, and serves only bitscan-runner | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
| CHK-M10-220 | canary sweep: no execute, stdout, stderr, pattern or token canary in any journal; no TCP/UDP listener of theirs | NOT RUN | host booted with cgroup v1: only CHK-M10-214 runs here |
