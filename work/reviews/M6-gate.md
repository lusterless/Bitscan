# M6 GATE REVIEW: first-release gate (closing check)

Reviewer: reviewer-m6. Started 2026-10-26 (pre-read); closed 2026-10-27 after the fold. Scope: TASK-129 to TASK-138, REQ-137 to REQ-149 (`work/tasks.md` "M6 gate": G1–G11, G17, G18, G35–G41, G47–G53, and the mutation table CHK-M6-320..345).

Inputs:
- `work/reviews/TASK-129-130-131.md`, `TASK-132.md`, `TASK-133-134-135.md`, `TASK-136-137.md`, `TASK-138.md`;
- `work/decisions.md`:
  - the 2026-10-26 rows: the time-skew rule L274 and its mandatory form L278, the VM-plant decision L279, the TASK-138 deviation L256, the pre-read rulings, CHK-M6-320x, the network move, option 3;
  - the 2026-10-27 rows L286–L294: the 1,800 MB VM floor, the speed-ups, item 3 alone, **the VM-plant gate exception (L289)**, the unit-level plants, the overnight pre-authorisations, "Item 3 done", the fault-fix pre-authorisation;
- `work/status.md` Drain 4 and after;
- `tests/m6/test-plan.md`; `tests/m6/report.md` (final, 616 lines, incl. "Gate TP-M6-14"); `tests/report.md` (M6 index row); the tester scratch files `m6-tester-scratch/w4/s2.txt`, `s3.txt`, `tokscan-findings.md`, `m6d/g18.out`, `m6d/wheel.out`;
- for the exception mapping: `work/tasks.md` (the M2 to M5 mutation tables), `tests/m2/report.md` to `tests/m5/report.md`;
- the working-tree diff against `8ad50eb`.

**Review batches:**
1. Pre-read (2026-10-26).
2. Batch 2: G18, G5 and its plant, the wheel plants, TP14-timing, F1, the environment rows.
3. The VM-plant exception (§5a).
4. Batch 3: item 3, the unit plants, F5, the no-call annotations.
5. The fold: CHK-M6-209-r2, the CHK-M6-284-ws-fix-r1 row, the "Gate TP-M6-14" section, the fingerprint.

**Verdict: APPROVED (M6 exit gate), with one named exception.** CHK-M6-340..345 (the real-host VM plants) are NOT RUN under the user's sign-off (decisions L289); they run before any M7 code (§5a). I don't block on the exception. **Open findings: 0 blocking, 0 should-fix, 4 nits** (§6: nits 4, 6, 7, 10; none has a gate effect).

## 1. Task reviews

All ten M6 task reviews are APPROVED, and none has an open blocking or should-fix finding.

| Task | Review | Extra rounds | Two approvals (TS §8.2) |
| --- | --- | --- | --- |
| TASK-129, 130, 131 | `TASK-129-130-131.md` | none; one nit on 131 (anchor re-read after a rename, inherent in #89) | no |
| TASK-132 | `TASK-132.md` | none | yes: user's second approval (decisions 2026-10-26) |
| TASK-133 | `TASK-133-134-135.md` | r1 (F1 `apt update`, F2 readyz loop) | no |
| TASK-134 | same | r1–r5 (backups; F3, F4; O2; F5; N3, N4) | no |
| TASK-135 | same | r1 (bare `manager` resolved on PyPI) | no |
| TASK-136, 137 | `TASK-136-137.md` | none; nit: web SBOM not byte-reproducible | no |
| TASK-138 | `TASK-138.md` | none | yes: user's second approval (decisions 2026-10-26) |

## 2. Product diff and the "no product change for a test" rule

**My final check (2026-10-27):** `git diff 8ad50eb --stat` on `manager/bitscan_manager`, `agent/`, `deploy/systemd`, `deploy/dbus`, `web/src`, `manager/openapi.json` and both locks: exactly six files, with no untracked file in those paths.

| File | Task | Checked |
| --- | --- | --- |
| `manager/bitscan_manager/api/user/agents.py`, `services/agents/fleet.py`, `repositories/agents.py`, `repositories/inventory.py` | TASK-131 | the cursor change only; parameterised SQL; no timing constant touched |
| `deploy/systemd/bitscan-capread.socket` | TASK-138 | +1 line `RemoveOnStop=yes` after `SocketMode=0660`, the recorded deviation |
| `agent/.golangci.yml` | TASK-132 | lint config only; rules added, none narrowed |

The other tracked changes are packaging metadata (`manager/pyproject.toml`, `deploy/debian/changelog`, `rules` comments, the removed lintian override), docs and runbooks, the new `release.yml`, tester-owned tests and records. There is no migration, no `web/src` change, no agent Go file and no other unit, and `openapi.json` is unchanged.

The fold's fingerprint row (CHK-M6-TP14-fingerprint) agrees:
- 1,215 files, list sha256 `8d04336a…5866`;
- the product-file hash `4b476004…` is the same in the worktree, in CHK-M6-315's G18 copy and in tester-m6c's gate copy;
- the same 6-file product diff.

So the tree that passed G18 and the gate is the tree under review. The unit plants 342u and 343u ran in throwaway copies, which were then removed.

**Time-skew fixtures (decisions L274, L278).** No fixture row changed product code, a setting default, a unit or a migration:
- CHK-M6-W4-fixture-2 and fixture-5 are one-row updates in the throwaway manager-host database, as `bitscan_owner`, with `audit_log` unchanged and no restart. Fixture-4 changed nothing.
- The `inventory_interval_s` 3,600 PATCH is REQ-147 (4)'s own step.
- The clock move is REQ-147 (1) itself.
- CHK-M6-285-ctl is a seconds-long `chmod` on a throwaway VM, which was then restored.
- CHK-M6-209's and -209-r2's waits were real: the agent's timers are monotonic, which a clock move can't advance, and a restart isn't allowed in those rows (L278).

**Production timing.** My source check agrees with CHK-M6-TP14-timing (PASS, re-run on the final tree): the spec values are unchanged, and there is no test-mode, fast-mode or skew switch.

**My own runs (Windows, final tree, 2026-10-27):** `ruff check manager` clean; `ruff format --check` 234 files; `mypy --strict` no issues in 234 files; `check_units_verbatim.py all` 10 OK (capread with its one DEVIATION line).

## 3. Decisions applied

| Decision | Status |
| --- | --- |
| TASK-138 `RemoveOnStop=yes` (spec deviation, user 2026-10-26) | unit + verbatim-check exception for exactly that line; RC `d98ef8c3…`; CHK-M6-261-r PASS |
| One VM at a time, 1 GB VMs, overlap of u2404 session 2 (user) | REQ-147 (4a), (6), (7) as plan L99–L102; (6) `online` 2 as written |
| Time-skew mandatory (user, L278) | complied with (§2) |
| VM plants CHK-M6-340..345 (L279 → superseded by L289) | **gate exception: NOT RUN under the user's sign-off; run before any M7 code** (§5a) |
| Unit-level plants 342u, 343u (user, L290) | both red |
| Item 3 alone at the 1,800 MB floor (L288); its rulings (L293) | done; 284-ws accepted with -eval; 209-r2 PASS |
| Overnight pre-authorisations (L291, L292, L294) | conditional on this APPROVED with no open blocking or should-fix finding; that condition now holds |
| #96 restart, not reload; #97 remote DB CA; O1 `/run/lock`; O2 PITR step | TASK-133/134 runbooks, tested |
| CHK-M6-320 → CHK-M6-320x (lead) | accepted (§5) |
| Default Switch moved to 172.26.240.1; VM floor 1,800 MB | test environment only; W0 quick re-check CHK-M6-200-w0r PASS twice |

## 4. FAIL rows and their annotations

| Row | Annotation | Holds? |
| --- | --- | --- |
| CHK-M6-200-pre, -pre2, -s1a6, -pre-m6d, -200..265-s3 | environment stop rules; nothing started | yes; superseded by later attempts |
| CHK-M6-201 u2404-1 | Git Bash path rewrite | yes: -201-r PASS |
| W4 CHK-M6-285 rows (substring matcher) | superseded (F5) | yes: CHK-M6-285, -r2, -r3 PASS, and -ctl shows the matcher goes red on a real 0644 token |
| CHK-M6-208 u2404 (jq), u2204 (tree) | test design / harness | yes: -r rows PASS |
| CHK-M6-261 u2404-1 | spec gap → TASK-138 | yes: -261-r PASS; CHK-M6-166 old-RC control |
| W4 CHK-M6-209 ×2 | `--value` order; no-call counts blind to refused calls (a 401 record has no `agent_id`: `api/agent/dependencies.py` L195–L201, `request_log.py` L41, both confirmed) | yes: **superseded by CHK-M6-209-r2** (§5) |
| CHK-M6-209 item 3 (extra assertion) | harness expectation | yes; not a product defect |
| W4 CHK-M6-280/-281 no-call counts | annotated (L286, L605) | yes, and in my reading sound: they guard against requests *succeeding* under a bad pin or CA, which would be authenticated and logged with `agent_id` (nit 10 on the wording) |
| W4 CHK-M6-286 ×2 | the harness's own sudo log | yes: closed by item 3's CHK-M6-286 with controls 1/1, 2/2 |
| W4 CHK-M6-262 | `matches` lists other agents only | yes: item 3 PASS |
| CHK-M6-263 u2204 "unchanged" sub-check | compares across fixture-5 | yes (accepted, L271) |
| CHK-M6-W4-fixture-4 | replaced by fixture-5 | yes |
| CHK-M6-284-ws | harness expectation; -eval PASS | yes. The verbatim agent unit L12–L14 (`ProtectSystem=strict`, `ReadWritePaths=/var/lib/bitscan-agent`, `PrivateTmp=yes`) gives that writable set; both private dirs were empty; the owner sweep found only root-owned files. The fixed rule is now exercised offline (CHK-M6-284-ws-fix-r1, 18/18, incl. an extra writable `/etc` → fail) |

## 5. Gate results

| Gate | Row | Clean | Plant → red |
| --- | --- | --- | --- |
| G1–G4 | CHK-M6-310 | ruff, format, mypy 234 files, both locks, pip check | S608 f-string; one hash digit |
| G5 | CHK-M6-311 | 99.41 % | red exactly at 85 % (+344 → 84.99 %, rc 2; +343 → 85.02 % green) |
| G6, G16 | CHK-M6-312 | byte-identical; client unchanged | cursor field on AgentItem |
| G7–G11 | CHK-M6-313 | 0 issues; static; -race 867/873 (M5 baseline skips) | CHK-M6-337..339, -142, -144 |
| G17 | CHK-M6-314, -160..162 | 10 verbatim (one recorded DEVIATION); verify silent incl. manager units with the real binary | CHK-M6-314-plant ×3; CHK-M6-161 12/12 |
| G18 | CHK-M6-315 | 4,824/4,824, 0 failed, 0 errors, 0 skipped | G53 rows |
| G35, G36 | CHK-M6-316 | 385/389 (4 named skips), 63/63 | M4 rows stand |
| G37–G40 | CHK-M6-317 (mapping) → CHK-M6-102..105, -163..165 | lintian 93/93, maintainer 567/567 on both releases, upgrade 20/20, repro 14/14, SBOM | M4 rows stand (scripts unchanged) |
| G41 | CHK-M6-318 | 23/23 on `d98ef8c3…` | reverse-order list hash → 422 `hash_mismatch` |
| RC = release build | CHK-M6-319 → -319-final, -319-vm | the release run's `.deb` is byte-identical to `d98ef8c3…`, the file installed on the fresh VMs | — |
| G47 | CHK-M6-020..027; control 59/59 | 59/59 | 320x, 321, 322 red; 320 a recorded test-design row |
| G48 | CHK-M6-040..058, r1; CHK-M6-055-e2e, -286-mgr-secrets | walk 59/59, host 19/19; after the end-to-end run: write sweep clean, 0 secrets (control 2/2) | 323..326 red |
| G49 | CHK-M6-110..117, -112-r1 | actionlint, 17/17, 22/22, 34/34 | 327..332 red; GitHub run CHK-M6-118 NOT RUN (no push) |
| G50 | W4 + item 3 + CHK-M6-209-r2 | both hosts; fresh u2404 on the final RC 46/48 (2 accepted harness expectations) and 28/28 | 340 NOT RUN (§5a) |
| G51 | CHK-M6-260..265, -262 | every alert kind tested | 342, 343 NOT RUN (§5a); 342u, 343u red |
| G52 | CHK-M6-280..286 | route groups, refusals, sockets, caps, modes (-ctl), canary (controls), write sweep (-eval) | 341, 344, 345 NOT RUN (§5a) |
| G53 | CHK-M6-120..126 | 434/434 | 333..336 red |
| REQ-142 (4) | CHK-M6-213 (mapping) → CHK-M6-202, -203, -262, -210 | runbook §2, §3a, §7 and purge as written on both VMs | — |
| timing | CHK-M6-TP14-timing | spec values, no test switch | — |
| idle cost | CHK-M6-300 | 0.0028 % of one CPU, VmRSS max 11,088 kB (recorded, no gate) | — |

**CHK-M6-209-r2 (the fold).** It meets all six points I set (§8 of the pre-read):
1. revoke 204;
2. the agent's next call answered 401 (`PUT /inventory`, 44 s after the revoke);
3. the access log counted by request path for 10.0 real minutes: the first refused call, which is the control that the count sees refused calls, then 0;
4. one re-enrol journal line;
5. `ActiveState=active` and `NRestarts=0`, read by name;
6. u2404 restored to `clean`.

It was run on a fresh u2404 from `clean`, on RC `d98ef8c3…`, with the W0 re-check passing again. The behaviour matches `loops/run.go` L133–L149. This closes REQ-146 (9).

**The wheel plants.** 320x substitutes for 320 without lowering the gate. Plant 320 can't create the fault under hatchling 1.32.4, while 320x can, and G47 goes red on the UI rows. CHK-M6-331 covers the same fault in the release workflow, and the secret-relevant ignore patterns still exclude.

**Item 3 and the unit plants.** See the rows (report.md L497–L531). The controls prove each check can fail: 285-ctl (0644 → red); 286's logged lines found 1/1 and 2/2; 286-mgr-secrets matching the real values 2/2; 342u and 343u against a 177/177 control.

### 5a. Gate exception: VM plants CHK-M6-340..345 NOT RUN (user, decisions 2026-10-27 L289)

**The exception.** The six real-host plants of G50–G52 ship as NOT RUN in v0.1.0, under the user's sign-off, because the session safety check blocked them three times. They are the first work item before any M7 TASK IMPL. This lowers the M6 gate as `work/tasks.md` L1389–L1393 wrote it, because those rows prove the real-host checks themselves can fail. It is a named, owner-approved exception, recorded on every row (report.md L571–L582); nothing planted was built or installed. I don't block on it.

**What it gives up:** the proof that the *VM harness rows* turn red on a faulty build. The product behaviour passed on real 22.04 and 24.04 hosts, and each fault has been planted and gone red below the VM level:

| M6 plant | Lower-level cover (recorded red) | Cover |
| --- | --- | --- |
| 340 reversed `list_sha256` | CHK-M6-318-plant (the same package 864c59dc… against a real serve), CHK-M4-350, CHK-M3-357 | full, except the host (container) |
| 341 pin check skipped | CHK-M4-322, CHK-M4-323 (Go TLS tests) | partial: not the installed binary against the real manager. The VM row it targets (CHK-M6-280) would see the fault, since a skipped pin yields authenticated, `agent_id`-bearing requests |
| 342 skew threshold 10 min | **CHK-M6-342u** (exact fault, 9 red), CHK-M3-367 | near-full |
| 343 alert without `detail.alert` | **CHK-M6-343u** (exact fault, 35 red), CHK-M3-368, CHK-M2-135..138 | near-full |
| 344 `bsa_` on a user route | CHK-M3-323, CHK-M5-336; CHK-M6-282 PASS on a VM | near-full |
| 345 token logged at start-up | CHK-M4-339 (a different leak); CHK-M6-286's logged controls on the VM | partial → near-full: detection proven, the planted leak unproven |

The fold's mapping table (report.md L575–L582) matches this table and the earlier tables I checked.

**The fold's NOT RUN list (report.md L584–L600).** I checked it against my pending list, and it is complete:
- CHK-M6-340..345;
- CHK-M6-118 and every GitHub run (no push);
- the deferred load, soak and TS §7 timing checks;
- `new_packages_burst` on a real host (#94);
- the browser approval (#93 (f));
- Debian 12 and arm64;
- CHK-M6-108, the CHK-M6-263 u2404 recorded rows, CHK-M6-320 as a plant, CHK-M6-151 `runner_unavailable`, and shellcheck inside the image.

Each item has a reason and its impact on core function. The impact statements are accurate: no core function is untested at test scale. Fleet-scale latency and CI are unmeasured until the deferred load tests and the push.

**REQ coverage.** Every M6 REQ, REQ-137 to REQ-149, has passing rows, including every acceptance item (REQ-146 (9) through 209-r2, REQ-148 (5) through 284-ws-eval, REQ-140 (5)/(7) through 055-e2e and 286-mgr-secrets). The only gap is the §5a exception.

**Security invariants.** They hold. Nothing in the diff adds a command path, a push or listener, an inventory switch, signing, client certificates, a host-settings route or remediation. TASK-131 keeps parameterised SQL. TASK-138 adds no privilege or listener, and the helper stays disabled by default. The release is a draft with `contents: write` only on publish, and the `.deb` ships with a published SHA-256. On real hosts:
- route groups give 401, and `bsk_` on sensitive actions gives 403 `totp_session_required`;
- there is no listener, the capabilities are 0, and the agent writes only its state folder;
- the token file is 0600, with no token in debconf or `/etc`;
- no token or secret is in any journal or the sink, each check with a control.

The only token leak found was the harness's own sudo command line in W4, fixed and re-checked clean.

## 6. Findings

Resolved during the review: F1 (s2.txt rows copied), F2 (REQ-148 (5) write sweep, -eval), F3 (REQ-140 (5)/(7) after the end-to-end run), F5 (CHK-M6-285 annotations), nit 8 (the CHK-M6-284-ws fix exercised offline, 18/18), nit 9 (the CHK-M6-209 test-plan wording counts by path).

Open, none with a gate effect:
4. nit, `work/requirements.md` REQ-147 (3) and `work/plans/M6-e2e.md` L81: "existing agent among its matches" disagrees with M3's `matches()` and TS §3.2 L187. **Fix:** planner-m6 changes both to "held as `reenrol` with the request's `agent_id` equal to the existing agent's; `matches` lists only other agents". Wording only, in work/ files.
6. nit (owner), `.claude/rules/deploy/packaging-and-units.md`: name the TASK-138 `RemoveOnStop=yes` exception. **Fix:** the user only (`.claude/` is excluded from every pre-authorisation).
7. nit (owner note, later milestone), `manager/pyproject.toml` L53–L57 comment and `work/reports/TASK-129-impl.md`: they misstate why the UI is packed. **Fix:** impl-manager rewords the comment to "kept as a guard in case a hatchling version applies the parent `.gitignore`", or pins hatchling's range in `[build-system]`. Not in M6: no product change after the gate.
10. nit (new), `tests/m6/report.md` L286 and L605: CHK-M6-280/-281 are called "weaker than stated but less affected". In my reading their no-call evidence is sound for what they guard against, a request succeeding under a bad pin or CA, which would carry `agent_id`. **Fix (optional, tester):** reword to "sound for the failure they guard against; refused handshakes never reach HTTP". It changes no result.

## 7. Accepted residual risks (M6 additions; earlier residuals stand)

1. W4 ran on RC `3b5c98a0…` for everything but capread. The final RC `d98ef8c3…` differs only in the capread unit line and its md5sums entry (CHK-M6-163), and the final RC is what item 3 and 209-r2 ran on.
2. Stale inventory: "failed attempts don't refresh `last_inventory_at`" rests on about 1 minute of evidence (user, L271).
3. **VM plants CHK-M6-340..345 NOT RUN (gate exception, L289; §5a).** Carry-over: they are the first work item before M7 code.
4. REQ-148 (5)'s evidence is the evaluation row CHK-M6-284-ws-eval, not the original harness verdict.
5. Owner notes, no M6 change: TS §8.7 L1343 SIGHUP wording; a product guard for the audit cursor after a restore; the #65 (b) re-arm state is in memory only; the web SBOM isn't byte-reproducible; O1 `/run/lock`; the TASK-129 comment (nit 7).
6. TASK-131 nit: a hostname rename between page loads can shift an `/agents` page once (inherent in #89).
7. Not measured: fleet-scale load and latency (deferred by the user), CI on GitHub (no push yet).

## 8. PENDING

None for this verdict.

## 9. For the user

1. **The VM-plant exception (§5a)** is under your sign-off. The PR and the release notes name it, and CHK-M6-340..345 are the first item before M7 code.
2. The overnight chain (L291, L292, L294) may start: this review is APPROVED with no open blocking or should-fix finding. Its own conditions still apply:
   - CI fully green on GitHub, including `release.yml` (CHK-M6-118);
   - fixes during CI only in test or CI files;
   - the tag and the publication only if the draft release's `.deb` is `d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf` and `SHA256SUMS` verifies every asset.
3. The PR names the TASK-138 deviation (TS §3.7 unit + `RemoveOnStop=yes`), the VM-plant exception, the NOT RUN list (report.md L584–L600) and the owner notes in §7 (5).
4. `.claude/rules/deploy/packaging-and-units.md`: the TASK-138 exception (nit 6), yours only.
5. Avoid Windows reboots until the M6 work is wrapped up: the Default Switch address moves on reboot, and the carried VM plants need the current network setup.
