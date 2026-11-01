# M10 breakdown: agent runner and sandbox (planner-m10, 2026-10-30)

Worktree `Bitscan-m10`, branch `m10-runner`, from main `328b097` (M9 merged). Full text: `work/requirements.md` "M10", `work/tasks.md` "M10", `work/open-questions.md` "M10", and the design plans `work/plans/TASK-209.md` (protocol), `TASK-215.md` (cgroups and process start), `TASK-210.md` (redaction and capture), `TASK-212.md` (spool and posting).

## 1. Counts

- **30 REQ** (REQ-234 to REQ-263), **23 TASK** (TASK-209 to TASK-231), **25 test-plan items** (TP-M10-00 to TP-M10-24), **6 waves** plus the gate, **9 new gates** (G71 to G79), **74 mutation rows** (CHK-M10-320 to CHK-M10-393; 45 security rows, 23 also planted on a VM).
- **14 open questions** (#130 to #143) and **5 process decisions** (PD-41 to PD-45), each with a recommended answer; **none is a spec deviation**. Reused as agreed: #4, #28, #29, #30, #31, #57, #60, #74, #78, #113, #114, #116, #121, #124 (f).
- **No manager change, no contract change, no migration, no unit change.** One new Go module if PD-41 (a) is taken (`golang.org/x/sys`).
- Approvals (PD-43): the TS §8.2 second approval for TASK-209 to TASK-228 (20 tasks); the lead's second look at TASK-230; one approval for TASK-229 and TASK-231.

## 2. Waves and owners

| Wave | Runner side (impl-agent-r) | Agent side and capread (impl-agent-a) | Deploy (impl-deploy) |
| --- | --- | --- | --- |
| W1 | 209 protocol, 210 redaction, 211 lint + `x/sys` | — | — |
| W2 | 213 job checks, 214 capture + result, 215 cgroups, 216 hygiene + start-up refusals, 217 socket activation + peer check | 212 spool store, 218 runner client | — |
| W3 | 221 plugin start | 219 spool overflow, 220 results sender, 222 capread server | — |
| W4 | 224 executor, 225 serve loop | 223 compliance handler + heartbeat, 226 capread client + main | — |
| W5 | 228 runner main | 227 agent main | — |
| W6 | — | — | 229 agent CI, 230 sandbox CI, 231 runbook + README + changelog |
| Gate | sandbox suites on the VMs and hosted runners, security suite, first compliance run, mutation table, closing review | | |

Testers: tester-m10 (Go unit and Linux suites, from W1) and tester-m10b (the driver, probe and VM harness from W1, the sandbox rows from W5).

## 3. Dependency spine

`211 → 215 → 221 → 224 → 228 → 230` is the longest path (six waves). Interfaces come first: the protocol and redaction APIs in W1; the spool, client, cgroup and socket APIs in W2; the `Executor` interface (plan TASK-209 §4) lets the serve loop (225) be built beside the executor (224). The graph is acyclic and every wave is file-disjoint (one recorded exception: `spool.go`, TASK-212 in W2 and only the `Put` call site in TASK-219 in W3).

## 4. Top risks

1. **Getting a plugin into its own cgroup from its first instruction under the verbatim unit.** Go's `UseCgroupFD` needs `clone3`, which systemd may refuse with ENOSYS under `RestrictNamespaces=yes`; the plan uses a cgroup hop under a spawn lock instead, and sets niceness and I/O class on a locked, discarded thread (so `Pdeathsig` must not be used). The gate records the `clone3` fact. If the VMs show that the verbatim unit blocks a needed call (for example `ioprio_set`, or a read-only cgroup tree), it is a **spec question for the user**, not a unit edit.
2. **Same-uid interference.** Plugins run as `bitscan-runner`, so they can move the runner between cgroups, kill its cgroup or signal it. The design re-checks its own cgroup before every kill and accepts a runner restart (the TS §3.7 L283 class); no plugin survives because systemd kills the service cgroup. Recorded as an accepted residual in #138 (c).
3. **Redaction correctness at the boundaries:** a secret across the 64 KiB cut, a key cut by the 1 MiB read, a cut inside a UTF-8 rune (which would make the manager store `oversize`), invalid UTF-8, explosive or empty-matching patterns. Covered by #133, #134, fuzzing and 14 mutation rows.
4. **Go `regexp` versus the manager's `google-re2`.** Both are RE2 syntax but not identical; a pattern one accepts and the other refuses makes every job `runner_unavailable: refused_bad_patterns`. The shared-corpus cross-check (REQ-243 (3)) proves the five defaults match the same; a mismatch on an admin pattern is visible, never silent.
5. **Memory under `MemoryMax=256M`** shared by the runner and up to 8 plugins: bounded by the 1 MiB capture per stream, the 4 MiB growth guard and one-at-a-time redaction.
6. **VM availability and safety-check refusals.** Mitigated by running the same sandbox suite on GitHub-hosted `ubuntu-22.04` and `ubuntu-24.04` runners on every relevant PR (G77), with a named lower-level cover for each VM row (section 6). M10 does not merge while a VM row is NOT RUN until the user decides.
7. **WSL may not offer unified cgroup v2.** Then the delegated-cgroup tests run only in CI and on the VMs; the pure packages still run locally.

## 5. Open questions and recommended answers (short form)

| Item | Recommended answer |
| --- | --- |
| #130 protocol | One Unix connection per job; 4-byte length + JSON frames (request ≤ 32 MiB, reply ≤ 1 MiB); request `{v: 1, job, max_parallel_plugins}`; replies `accepted`/`refused <word>`/`result`/`done`; 30 s and 60 s deadlines; one connection at a time (`busy`); either side closing ends the job; no agent-side peer check (systemd owns the listener). |
| #131 runner failures (refines #28) | Connect error, 30 s silence, `refused`, a broken connection or a bad frame → every plugin without a result is posted `runner_unavailable`, final batch, never resent, `last_error` `runner_unavailable: <word>`. If the agent itself stops mid-job, no final batch: the manager's retry handles it (TS §4.4 L577). |
| #132 runner job checks | `agent_id` file read per job; `now < pickup_by ≤ now + 25 h`; in-memory seen set kept to `pickup_by` + 1 min, bounded at 100,000 (full → refuse); 1–5,000 distinct plugins, `timeout_s` 1–600, `max_parallel_plugins` 1–8; fixed check order. |
| #133 cut-off key rule (marker `runner-sandbox.md:43`) | Always applied by the runner, whatever the pattern list holds; from the first BEGIN with no END after it to the end of the buffer. |
| #134 redaction details | Bytes per #57; drain beyond 1 MiB; invalid UTF-8 → U+FFFD first; Go `regexp`, literal replacement in list order; refuse > 50, non-compiling or empty-matching patterns; growth guard at 4 MiB (whole stream → `[REDACTED]`); rune-boundary cut; `truncated` for stdout only; one plugin redacted at a time. |
| #135 temp directory (refines #31) | Fresh 0700 `/tmp/bitscan-p-<random>` as working directory, no `TMPDIR`; private `/tmp` and `/var/tmp` emptied after each job. |
| #136 plugin start | cgroup hop under a lock (not `clone3`); niceness and I/O class on a locked, discarded thread; exact argv, environment, stdin; no `Pdeathsig`; exit code or 128 + signal; a cgroup failure stops the job. |
| #137 start-up refusals | `PR_SET_DUMPABLE` 0 first; refuse euid 0, capabilities beyond `CAP_DAC_READ_SEARCH`, non-unified cgroup, no delegation or `cgroup.kill`, bad `LISTEN_*`. |
| #138 sweep | Depth-first `cgroup.kill` of every cgroup but `supervisor`; pidfd SIGKILL of every other pid in `supervisor`; move back if moved; accepted residual: a plugin can make the runner restart, never survive. |
| #139 spool layout | Per-job manifest (no commands) and item files, atomic through `os.Root`; size in bytes on disk; drop answers drop only that batch; interrupted jobs never get a final; 7-day local expiry. |
| #140 overflow | Oldest full results first, across jobs, into `spool_overflow` markers that keep uuid and times; the new item becomes a marker if needed; oldest markers dropped last; in-flight batches protected. |
| #141 posting | ≤ 50 items and ≤ 1,572,864 bytes uncompressed; always gzip; post at 50 items, the size bound, 30 s after the oldest unsent item, or job end; one sender; back-off 10 s → 5 min. |
| #142 capread wire | Request `name\n` (≤ 32 bytes); reply `ok` + stdout, or `error <word>`; stderr never sent; over 1 MiB → `error too_large` with nothing sent; sequential; client exit 0/1/2. |
| #143 "full CIS set passes" | Every `bits/samples/` plugin, under the sandbox, has no error or timeout, no exit 126/127, and the same normalised stdout as root outside the sandbox. |
| PD-41 | Add `golang.org/x/sys`, pinned, used only by runner, `sdsock` and capread. |
| PD-42 | Changelog `0.2.0~pre1-1`; no tag or release; the supported `0.2.0` after M11's N / N−1 tests. |
| PD-43 | Two approvals for TASK-209 to 228; the lead's second look at TASK-230; one approval for TASK-229, 231. |
| PD-44 | Sandbox suite on hosted runners on every relevant PR (G77) plus the VMs at the gate (G76); planted builds as throwaway `.deb` files on freshly restored VMs; a NOT RUN VM row names its cover and waits for the user. |
| PD-45 | Rewrite only the M4 #74 compliance checks to REQ-245, with an old → new CHK list. |

**Spec-internal notes (report only):** `PrivateTmp=yes` also makes `/var/tmp` writable (TS §3.7 L324 says only `/tmp`); the cut-off rule appears in both TS §3.5 and TS §8.6 pattern 2 (#133); the manager accepts patterns with `google-re2` while the runner matches with Go `regexp` (#134 note); the runner's seen set is in memory only, so a replay after a runner restart is caught by the agent alone (accepted by TS L285).

## 6. VM plan

Hosts: `bitscan-u2204` and `bitscan-u2404` (Hyper-V, 2 vCPU, 2 GB each, `clean` checkpoint), driven by `e2e/m6/vm.sh` (restore, start, ssh, put). Before each run: restore `clean`, start, copy the `.deb` and the test bundle (driver, probe, suite), install with a dummy preseed, stop `bitscan-agent.service`, write a test `agent_id`; after: collect the JSON row report, restore `clean`. Memory floors as M6 (the VMs need 4 GB together; check `vm.sh mem` first).

| Row group | VM | Lower-level cover |
| --- | --- | --- |
| Plugin cannot write, open IP sockets, exec outside system paths, gain privileges, load modules, change clock or hostname | G76 | G77 on both hosted runners; G17 |
| Blocked Docker, containerd, snapd, journald sockets (planted test listeners) | G76 | G77 (real `/run/docker.sock` there); G17 |
| `ptrace`, `process_vm_readv`, `/proc/<pid>/mem`, inherited socket, socket replacement | G76 | G77; TP-M10-09, TP-M10-10 |
| D-Bus state-changing calls refused, read-only calls work | G76 | G77; G17 |
| No plugin outlives its job; cgroup layout; environment; niceness and I/O class | G76 | G77; TP-M10-08, 15, 17 (CI, `systemd-run -p Delegate=yes`) |
| Runner refuses on cgroup v1 (`systemd.unified_cgroup_hierarchy=0` on u2204, then restore) | VM only | TP-M10-09 (injected statfs and `/proc/self/cgroup`) |
| capread with real `nft` and `auditctl` (auditd installed on the VM), capabilities | G76 | G77 (`nft` only); TP-M10-14 |
| Every sample plugin under the sandbox (#143) | G76 | G77 |
| Planted-fault builds (the 23 VM rows) | one throwaway `.deb` per plant on a restored VM | the same plant on a throwaway branch through G77, and the unit row named in the mutation table |
| First compliance run with the M9 manager in WSL (G79, u2404) | VM + WSL | the same walk against the fake manager in G77; TP-M10-16 |

Runs only in WSL or containers (no VM): the pure Go suites (also Windows), the Linux runner suites when WSL has `cgroup2fs`, the RE2 cross-check (`manager/tests/`), G37–G41 (packaging and the inventory chain against the real manager).

## 7. Uncovered by design, and carry-overs

- **M11:** the results UI, `POST /scans/{id}/reevaluate`, CSV exports, the read views, the nightly end-to-end run on three VMs, the N / N−1 matrix (and the `CLAUDE.md` N / N−1 marker), the retention task.
- **Not supported:** Debian 12 and arm64 rows of TS §3.1 and §8.3 (owner decisions 2026-10-24).
- **Deferred by the user:** load tests; the CI performance-gate question (`testing.md` marker).
- **Carry-over, not planned into a wave:** **TASK-146** (the BIT102 review, its TS §8.2 second approval and r2) for a fresh session (decisions 2026-10-30 (3)). M10 can merge without it: the runner sandbox is the control (SR §4.2).
- **For the user (`.claude/` edits, not done by the team):** replace the markers `runner-sandbox.md:18`, `:27`, `:43` and `agent.md:36` with the decided behaviour once #130, #135, #133 and #131 are applied; `runner-sandbox.md:57` and `agent.md:58` still list Debian 12 and arm64 for the agent tests.

## 8. Product choices for the user's morning review (decisions 2026-10-30 (4))

Each fails closed or follows standard practice, and none deviates from the spec: #130 (frame format and deadlines), #131 (no final batch after an agent restart; `last_error` words), #132 (seen-set bound 100,000), #133 (cut-off rule always), #134 (empty-match refusal, 4 MiB growth guard, U+FFFD before matching), #135 (no `TMPDIR`; `/tmp` and `/var/tmp` emptied per job), #136 (cgroup hop, no `Pdeathsig`), #137 (capability self-check), #139 (drop answers drop one batch; 7-day local expiry), #140 (oldest markers dropped last), #141 (30 s cadence, always gzip), #142 (`too_large` sends nothing), #143 (equivalence with root), PD-41 (`x/sys`), PD-42 (`0.2.0~pre1-1`).
