# M4 GATE REVIEW: Go agent and `.deb`, pre-release 0.x (closing check)

Reviewer: reviewer. Date: 2026-10-25. Scope: TASK-085 to TASK-107, REQ-091 to REQ-112 (`work/tasks.md` "M4 gate": G7 to G11, G17, G35 to G41, and G1 to G6 with G18 for TASK-085, plus the security mutation table CHK-M4-320 onwards).

Inputs:
- every `work/reviews/TASK-0{85..99}.md` and `TASK-10{0..7}.md`;
- `work/decisions.md`, the 2026-10-24 and 2026-10-25 rows;
- `tests/m4/report.md`, the gate rows CHK-M4-300..311, -264, -311-plant, -G18, -G5-plant, -gate-notrun, -010..019-gate and "M4 closing";
- the working-tree diff against `6fd593c`.

Verdict: APPROVED (M4 exit gate). Before the M4 PR, the user must decide or acknowledge the points in §6.

## 1. Task reviews

All 23 M4 reviews are APPROVED (TASK-085 to TASK-107). Several needed further rounds, and each was re-tested and re-reviewed:

| Task | Extra rounds |
| --- | --- |
| TASK-087 | r1, the FIFO refusal |
| TASK-093 | r1, Retry-After clamped to 24 h |
| TASK-094 | r1, process-group kill |
| TASK-097 | rounds 1–4; round 4 moves `go mod download` and `go mod verify` first |
| TASK-099 | r1, every Drop answer waits 24 h |
| TASK-100 | r1 (key tracking, `/etc/bitscan` owner and mode) and r2 (debconf fds closed, `mv -fT`). Review round 1 was CHANGES_REQUESTED on the tests; round 2 closed it with a writer-uid trace and the G38 plants. |
| TASK-101 | r1, the "new enrolment token" line |
| TASK-102 | r1, `-trimpath` on the SBOM tool, so the SBOMs are byte-identical |
| TASK-105 | fix rounds 1 and 2, the lintian overrides, including the six D-Bus lines |
| TASK-107 | r1 (D2 warning), r2 (CA under `/etc`) and r3 (cloned host: remove both machine-id copies) |

**No blocking or should-fix finding is open in any M4 review.** The optional nits the lead left as built are listed in decisions 2026-10-25 ("Optional reviewer nits left as built", and TASK-093 r1). None of them changes behaviour.

**Second approval from the user (TS §8.2)** is recorded for every M4 two-approval task, that is the 15 agent tasks plus TASK-100:
- W1, 2026-10-24: TASK-086, 087, 088, 089, 090 and 091;
- 2026-10-25: TASK-094, 095, 098 and 099 (with r1), then TASK-100, then TASK-093 (with r1), 101 (with r1) and 104;
- TASK-103 and 106 under the user's overnight pre-authorisation. That authorisation was applied on a clean PASS plus "APPROVED, no open blocking or should-fix findings (and no nits)" (decisions 2026-10-25, "Pre-authorised approvals applied").

TASK-085 is not on the list, because its refactor changes no behaviour (the TASK-084 rule).

## 2. Changes outside the task file lists (working tree against `6fd593c`)

| File | Change | Checked |
| --- | --- | --- |
| `manager/pyproject.toml`, `manager/tests/test_serve_linux.py`, `test_readme_walk_linux.py`, `test_serve_scheduler_linux.py` | The M3 gate fixes, applied in place of a merge (decisions 2026-10-25). | All four files are byte-identical to `ff1fb4f` (sha256 compared). They are the same changes I approved in `M3-gate.md` §2: `precision = 2` and three race-only test fixes. |
| `README.md` | TASK-085's two sentences. Line 3 changed to "Ubuntu 22.04 and Ubuntu 24.04 (amd64, cgroup v2)". | Line 3 is byte-identical to M5's, so the READMEs still match at merge. No Debian 12 or arm64 mention is left. |
| `agent/.golangci.yml` | One gosec G204 exclusion, limited to `^internal/inventory/command\.go$` (lead ruling, TASK-094). | Checked in TASK-094: no wider than that one file and that one rule. `//nolint` is still banned, and the grep is clean. |
| `agent/go.mod`, `agent/go.sum` | `go.yaml.in/yaml/v3` v3.0.5 is linked. `jsonschema/v6` (with `regexp2` and `x/text`) is test-only (PD-25). | `go version -m bitscan-agent` lists only yaml v3 (CHK-M4-303). |
| `deploy/tests/check_units_verbatim.py` | Extended to the D-Bus policy (tester). | It is red on a one-character policy change (CHK-M4-362). |
| `.github/workflows/agent.yml`, `package.yml` | TASK-097 and TASK-105. | Reviewed. |

**My own checks on the final tree (Windows, `GOOS=linux`, from `agent/`):**
- `gofmt -l .` prints nothing.
- `golangci-lint run ./...` reports 0 issues.
- The nolint/linkname grep finds nothing.
- A grep of non-test code for `net.Listen`, `exec.Command` and `InsecureSkipVerify` finds only the `exec.CommandContext` in `internal/inventory/command.go`. That is the fixed #35 list, and the call is excluded only there.
- `grep -i arm64|aarch64` over the workflows and `deploy/debian/` finds nothing.

## 3. Decisions applied or carried over

| Decision | Status |
| --- | --- |
| arm64 and Debian 12 dropped from v1 (user, 2026-10-24) | Builds, CI and tests are amd64 only, on Ubuntu 22.04 and 24.04 (CHK-M4-303, -250). The `.claude/CLAUDE.md` line is open; see §6 (3). |
| #74: idle runner and capread; compliance jobs answered `runner_unavailable` in batches of 50 or fewer | TASK-103. Runner and capread are the M0 stubs (CHK-M4-303). |
| #75: no proxy, no redirects; #79: pin of the leaf | TASK-093, TASK-089 (CHK-M4-327, -328, -322, -323) |
| #80: hold-off of 10 min 30 s from the last unscheduled upload | TASK-091 and TASK-104. G41 shows it on a real host (688 s). |
| #81: re-enrolment; refused enrolment or 401 stays idle; #82: purge only the agent's files | TASK-098, 100, 101, 106, 107; G38 |
| install.env (A)–(E), r1; D2 (runbook warning only) | TASK-100, TASK-107 |
| TASK-099 r1 (every Drop waits 24 h); TASK-093 r1 (Retry-After clamp) | Done, with second approval |
| G41 plant: "list_sha256 unsorted" is an equivalent mutant on a real host, because `dpkg-query -W` already prints in byte order | Replaced by a reverse-order plant, which is red (422 `hash_mismatch`). The unsorted case stays covered by `TestListSHA256MatchesManager` with unordered input (CHK-M4-112). I accept this. It is not a lowered gate: G41's purpose (a manager-refused hash stops the chain) is proven. |

**Carried forward (not M4 defects):**
- **Before any supported (non-0.x) release:** the owner must answer #28 (decided for 0.x as #74) and the agent-N against manager-N−1 compatibility question in `CLAUDE.md`. Decisions 2026-10-20 say 0.x is not supported as N−1.
- **M10:**
  - the `net.FileListener` and `x/sys/unix` lint exceptions for the runner and capread;
  - revisiting "a dropped batch ends the job" (TASK-103) when real results exist.
- **After M6 (load and soak deferred by the user):**
  - the TASK-064 snapshot lookup and the TASK-060 64 MiB copy;
  - the CHK-M4-266 idle cost (see §6 (4)).
- **TASK-087 loader (accepted as is, decisions 2026-10-25):** userinfo, query and fragment in `manager_url` are not refused. No data leaks.

## 4. Accepted residual risks (M4 additions; the TS §8.1 and M2/M3 residuals stand)

1. **Compromised `bitscan-agent`.** The agent's job checks catch mistakes, not attacks (TS §3.7, §8.1). Nothing in M4 changes that.
2. **Without a pin**, a holder of a publicly trusted certificate for the manager's name can impersonate the manager. Pinning stays optional; the runbook recommends it.
3. **A string-typed token preseed** leaves the token in `config.dat-old` until the next debconf save. The exposure starts at the operator's own `debconf-set-selections`. The runbook warns and gives two clean-ups (D2).
4. **An existing non-system `bitscan` account** is reused by postinst. The TASK-100 nit 6 was not taken, because the spec has no uid or shell rule.
5. **A CA file under `/home`, `/root` or `/tmp`** passes postinst but is hidden from the agent's sandbox. The runbook says to keep it under `/etc`.
6. **Three faults together in TASK-099**: a failed save, a lost retry answer, and then a restart. In that case the agent can start on a token the manager has discarded, and the host then needs re-enrolment.
7. **A dropped rotate answer** is not shown as `last_error`. The old token stays valid, and the rotate waits 24 h.

## 5. Gate results

The tester rows are in `tests/m4/report.md`. Each gate is green on the clean tree and red on its planted violation:

| Gate | Row | Clean | Plant → red |
| --- | --- | --- | --- |
| G7 gofmt | CHK-M4-300 | nothing printed | a misformatted line in `run.go` |
| G8 lint + nolint grep | CHK-M4-301 | 0 issues; grep empty | `net.Listen` (CHK-M4-346), `InsecureSkipVerify` (-321), `//nolint` |
| G9 download + verify | CHK-M4-302 | all modules verified | an altered yaml h1 line (CHK-M4-365) |
| G10 static amd64 build | CHK-M4-303 | 3 static ELF x86-64, `CGO_ENABLED=0`, stubs exit 1 | a non-test `import "C"` |
| G11 `go test -race ./...` | CHK-M4-304 | 867/873, 0 failed, 6 named skips (4 schema_gap; 2 root-only skips pass as `bstester`, 11/11) | a planted failure |
| G17 verbatim + systemd-analyze | CHK-M4-305 | 10/10 identical; systemd 249/255 rc 0 with packaged binaries | `ProtectHome` removed; policy `Get`→`Set` (CHK-M4-362) |
| G35 contract | CHK-M4-010..019-gate | 363/367 (4 lone-surrogate skips, ruled) | proven in TASK-086 (CHK-M4-353, -354, rename); files unchanged since |
| G36 agent security | CHK-M4-306 | 63/63 | every G36 row red in its task. TASK-093 r1 and TASK-101 r1 were re-planted after their changes. |
| G37 lintian | CHK-M4-307 | 4/4, lintian 2.117 | L1–L3 (TASK-105) |
| G38 maintainer scripts | CHK-M4-308 | 547/547 on 24.04 and 22.04 | CHK-M4-357..361 and both `set -e` plants; the writer-uid plants |
| G39 reproducible | CHK-M4-309 | 14/14; `.deb` `0fc4b93b…fd94`; SBOMs byte-identical | R1 (`-trimpath` removed), R2 (timestamp) |
| G40 SBOM | CHK-M4-310 | 89/89 | R5 (a module dropped) |
| G41 `.deb` vs real M3 manager | CHK-M4-311, -311-plant | 23/23 | reverse-order `list_sha256` → 422 `hash_mismatch`, and the chain stops |
| verbatim unit from the `.deb` | CHK-M4-264 | 15/15 on 24.04 and 22.04 | `net.Listen` plant |
| G1–G6, G18 (manager, TASK-085 and the M3 fixes) | CHK-M4-G18, -G5-plant | 3990/3990, 0 skipped; G5 99.52 % | G5 red at 80.09 % |

**No gate was lowered.**
- Every M4 gate in `work/tasks.md` was run with its own command or the stronger agent.yml r4 form. G9 adds `go mod download` before `go mod verify`, which tightens it.
- G41's plant was replaced, with the reason given (§3).
- G5 keeps 85 % with `precision = 2`.
- Debian 12 and arm64 were removed by the user's scope decision. That was not a gate change made at the gate.

**Not run (CHK-M4-gate-notrun):**
- the GitHub Actions runs of `agent.yml` and `package.yml` (not pushed);
- the Debian 12 and arm64 parts (dropped from v1 by the user);
- the CHK-M4-266 idle cost (no gate);
- load and soak (deferred until after M6 by the user).

## 6. For the user before the M4 PR is opened

1. **CI must be fully green before merge.** Checks are advisory on this plan (decisions 2026-10-21).
   - `agent.yml` and `package.yml` have never run on GitHub.
   - G10, G17 with built binaries, G37 to G40 on runners, and the install tests on both Ubuntu runners are proven only locally.
   - So is `actionlint` on the real event payloads.
2. **The branch must be merged properly at commit time.** The M4 worktree is cut from `6fd593c` and carries main's M3 gate fixes as working-tree copies, not as a merge. They are byte-identical to `ff1fb4f`, so merging main (`3ccf2b0`) should apply cleanly for those four files. Re-run G18 on the merged head if anything else differs. Nothing is committed yet; no commit is authorised overnight.
3. **`.claude/CLAUDE.md` "Supported hosts".** The M4 tree's committed copy still says "Ubuntu 22.04, Ubuntu 24.04 and Debian 12, on amd64 and arm64, with cgroup v2". The user's own uncommitted edit in the main tree says "Ubuntu 22.04, Ubuntu 24.04, on amd64", which matches v1 but drops "with cgroup v2" (TS §3 still requires cgroup v2; raised in `M3-gate.md` §6 (2)). The user decides the final text and whether it is committed with the M4 PR.
4. **Recorded spec deviations the PR must name** (TS §8.2: name the sections implemented):
   - Debian 12 and arm64 are dropped (TS §3.1 L152, §8.3 L1279);
   - #82: purge keeps a non-empty `/etc/bitscan` (TS §3.1 L166 says purge removes it);
   - the D-Bus lintian overrides (the policy is verbatim TS §3.7, against "must pass lintian" read strictly).
5. **The idle cost (TS §3.3 L216 target: < 0.1 % CPU, < 30 MB RSS)** has not been measured. It has no gate (testing.md open question). Suggest measuring it on the two M6 VMs, or deciding that it stays with the deferred load and soak tests.
