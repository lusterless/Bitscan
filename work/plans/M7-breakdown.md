# M7 breakdown: compliance catalog (`.bit` importer and validator)

Planner: planner-m7, 2026-10-27. Worktree `Bitscan-m7`, branch `m7-catalog`, from main `8ad50eb` (M0 to M5). M6 is still in `Bitscan-m6` and not merged, so the M7 sections are appended at the end of `work/requirements.md`, `work/tasks.md` and `work/open-questions.md` and continue M6's numbering. Phase A only: no code has been written. Nothing is built until you approve.

## Counts

| Item | M7 range | Count |
| --- | --- | --- |
| Requirements | REQ-150 to REQ-185 | 36 |
| Micro-tasks | TASK-139 to TASK-175 | 37 (25 high risk, 12 low risk) |
| Test-plan items | TP-M7-00 to TP-M7-30 | 31 |
| Waves | W1 to W13, then the gate | 13 |
| New gates | G54 to G61 | 8 (plus G1–G6, G12–G16, G18, G34 re-run) |
| Mutation rows | CHK-M7-320 to CHK-M7-371 | 52 (320 to 365 are security rows) |
| New open questions | #98 to #111 | 14, plus 17 re-checked (#1, #2, #9, #10, #11, #13 to #17, #20, #21, #23, #27) |
| New process decisions | PD-33 to PD-36 | 4 |

Owners: impl-manager TASK-139 to 167 (29 tasks), impl-web TASK-168 to 173 (6), impl-bits TASK-174, 175 (2). No agent, unit, packaging or workflow change.

**Migrations: none.** Every catalog table, the `task` table, the `v_plugin` view and the grants are already migrated and match TS §5.2; M7 uses only the granted privileges (never DELETE on `policy`, INSERT only on `bit_import`).

**Spec deviations: none.** Every recommendation stays inside the spec. Three spec-internal points are reported for the owner (rename onto a taken name, #106; the 5 MB cap on a multipart body, #99; the size of the import alert, #100).

## What M7 builds

- **Parse and validate** (TS §4.1 steps 2 to 4, SR §2, §4): read once, `defusedxml` only (no DTD, entities or external references), 5 MiB, element caps; canonical structure; every BIT rule with line numbers; BIT102 through a real POSIX `sh` lexer.
- **Store** (SR §3.6): one transaction per file, natural-key upserts, status override kept, version on hash change, retire never delete; BIT007 and BIT015 across files; server folder wins; rename in place; `bit_import` in its own transaction.
- **Load paths** (TS §4.2, §4.6): upload (temp file `O_EXCL | O_NOFOLLOW`, rename after commit), folder watcher (inotify), start-up (finish uploads, mark tasks failed, reconcile, integrity check), rebuild (savepoint per file, `task` row), CLI `bits rebuild`, all under the catalog advisory lock.
- **Delete** (TS §4.3): soft, `deleted/<id>`, queued jobs cancelled, schedules disabled, plugins retired, 409 for server-folder policies.
- **Routes** (TS §6.2): `GET /policies`, `GET` and `PATCH /policies/{id}`, `POST /policies/import` (multipart, admin, API token allowed), `DELETE /policies/{id}` and `POST /policies/rebuild` (admin TOTP session, API tokens refused, sink gate), `GET /tasks/{id}`, `GET /imports`.
- **Alerts** (TS §8.4): imported (every changed Execute, sensitive paths flagged), rejected, rebuilt, deleted, re-enabled, integrity failed; the import-failure metric.
- **UI** (PD-34): profiles list and detail for everyone; upload, status actions, delete, rebuild and import history for admins.
- **Samples** (#111): Ubuntu 24.04 and 22.04 Level 1 server policies, read-only, BIT102-clean.

## Waves

| Wave | Tasks | What |
| --- | --- | --- |
| W1 | 139, 140, 147, 148, 149, 150, 174, 175 | dependency, importer model, catalog lock, the three repositories, two samples; tester plan and fixtures |
| W2 | 141, 142, 143, 145, 151, 153 | parser, value helpers, structure check, `sh` lexer, store algorithm, alert kinds |
| W3 | 144, 146, 152, 161 | validators, BIT102 rules, delete service, profile routes |
| W4 | 154, 165 | import pipeline, import history route |
| W5 | 155, 156 | uploads, folders |
| W6 | 157, 158, 159 | rebuild, start-up and integrity check, watcher |
| W7 | 160, 166 | catalog service and `serve` wiring, CLI `bits rebuild` |
| W8 | 162 | upload route |
| W9 | 163 | delete route |
| W10 | 164 | rebuild and task routes |
| W11 | 167, 168 | README, web client regeneration |
| W12 | 169, 170, 171, 172 | the four web screens |
| W13 | 173 | web routes and navigation |
| Gate | tester, reviewer | G54 to G61, the mutation table, the closing review |

W8 to W10 hold one route task each because each re-exports `manager/openapi.json` (the M3 rule, PD-24 (a)). A second impl-manager instance can share W1 to W3, where files are disjoint.

## Dependency spine

`TASK-140 (model) → parser 141, structure 143, values 142 → validators 144, lexer 145 → BIT102 146 → pipeline 154 → uploads 155 → start-up 158 → service 160 → upload route 162 → delete route 163 → rebuild route 164 → web regeneration 168 → screens 169–172 → navigation 173`.

Side chains: repositories 148, 150 → store 151 → pipeline 154; lock 147, records 149, alerts 153 → pipeline 154; delete 152 → folders 156 → rebuild 157, start-up 158, watcher 159 → service 160; rebuild 157 → CLI 166; profiles 161 → delete route 163; dependency 139 → upload route 162. Acyclic. Interfaces come first: the model (140), lock and repositories (147–150), alert kinds (153), the `CatalogService` facade (160) and the route contract (#98).

## Two approvals (TS §8.2: importer changes need two)

25 tasks: TASK-140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 162, 163, 164, 166. Your second approval is asked once per wave for that wave's tasks, on TEST PASS and reviewer APPROVED with no open blocking or should-fix finding. No M7 task changes auth code: the delete and rebuild routes reuse the existing TOTP-session check unchanged.

Recommended second looks (PD-35): TASK-139 (a new runtime dependency), TASK-161 (`PATCH` can re-enable a profile), TASK-174 and TASK-175 (sample commands that will run on every host).

## Top risks

1. **BIT102 lexer.** A missed form is a bypass; a false positive breaks real CIS checks. Mitigated by a fail-closed lexer, must-reject and must-pass corpora, nine plants, and #108 fixing the matching scope. BIT102 stays a safety net; the sandbox (M10) is the control.
2. **Parser attacks** (XXE, entity expansion, oversize). `defusedxml` with every forbid flag, caps checked before parsing, element and depth caps (#105), and plants for each flag and cap.
3. **A wrong or empty folder deleting the catalog.** A rebuild or reconcile deletes policies whose files are gone. Deletes are soft (rows kept, revival possible), and the CLI refuses a missing folder (#107).
4. **Session-level lock plumbing** changes `db/pool.py` and `runtime.py` (M2 code). Full rigor, existing pool tests re-run.
5. **Alert size** (#100): an import alert can carry up to about 5 MiB of Executes; a syslog sink that cuts messages at 8 KiB would break the external audit copy. The README states the sink requirement.
6. **Long serial chain** with one impl-manager (13 waves). A second instance for W1 to W3 shortens it.
7. **Merge with M6:** M6 also edits `manager/pyproject.toml` and `README.md`; TASK-139 and TASK-167 touch other sections, so only those two files need a hand merge.
8. **CIS control numbers** in the samples are unconfirmed (TS §8.5); #111 marks them so.

## Open questions and recommendations

None blocks the planning. The ones needed first are marked with their wave.

| Item | Recommendation | Needed by |
| --- | --- | --- |
| PD-33 dependencies | Add `python-multipart` (low-level parser, in memory); inotify through a small stdlib `ctypes` binding, no new package | W1 |
| PD-36 plans | Planner writes the five design plans (parser, lexer, store, pipeline and lock, multipart) after approval, before W2 | W2 |
| #111 samples | Two samples (24.04 extending the SR §1.1 example, and 22.04), each noting the control numbers are unconfirmed; you confirm the numbers before M11 | W1 |
| #105 parser details | 35,014-element and depth-16 caps; CDATA or text in `Execute`; PIs, namespaces, stray text are BIT002; `@timeout` digits only; finding paths like `Policy/PluginsGroups/Plugin[12]/Operator`; messages quote at most 64 characters; no cap on findings | W2 |
| #108 BIT102 scope | Match `/bin/rm` as `rm`, `mkfs.*` as `mkfs`, every command anywhere (pipelines, subshells, substitutions, `-c` scripts), the command behind wrappers (`env`, `sudo`, `busybox` …); fail closed; add nothing to the SR lists | W2 |
| #109 uppercase `PluginId` | Reject (BIT004); lowercase hyphenated form only | W2 |
| #13, #17, #2, #10, #16 | As agreed: strict decimal grammar; trim XML whitespace on every text element; missing Operator/ExpectedResult are BIT010/BIT011; one Family; empty `PluginsGroups` is BIT002, bad timeout BIT017 | W2 |
| #14, #15, #21, #104, #106 | Revival always +1; BIT007 order by existing file, then path bytes; counts as agreed; a deleted policy keeps its plugin rows but keeps no plugin active; on a rename collision the existing name wins and the old policy is deleted | W2 |
| #100 import alert | One alert entry per import with every changed Execute in full and the flagged words (literal reading); README states the sink must take large entries | W2 |
| #101 audit and metric | Actions `policy.import`, `policy.import_rejected`, `policy.move`, `policy.delete`, `policy.status_change`, `bits.rebuild`, …; kinds `policy_imported`, `policy_import_rejected`, `policy_rebuilt`, `policy_deleted`, `policy_reenabled`, `catalog_integrity_failed`; counter `bitscan_import_failures_total{mode}` | W2 |
| #98 route bodies | Field names from the DDL; full plugin list in the detail; import answers 200 with `outcome` and `errors`; delete 204 or 409; rebuild 202 `{task_id}`; internal errors are 503, never a "rejected" row | W3 |
| #9 deleted policies | Not in the list; `?status=` takes `enabled` or `disabled`; the detail shows deleted ones | W3 |
| #110 warnings | Stored in `bit_import.errors` and returned; never reject | W3 |
| #99 upload | Body cap 5 MiB + 64 KiB envelope, file 5 MiB; a 413 writes no row; one `file` part only; client name sanitised and kept only as metadata; the 409 writes an audit entry, no row | W4 |
| #23 alerts on skip and rebuild | Skipped writes only its row; a rebuild alerts once plus per changed policy and per rejected file | W4 |
| #102 watcher and start-up | Close-after-write and move events only; symlinks and odd names skipped; own events ignored; start-up on a background thread with a 503 "catalog is starting" for upload, delete and rebuild until done | W5 |
| #20, #27, #103 | Rebuild with rejected files ends `succeeded`; the integrity check runs after the reconcile and compares file hash, plugin count and ownership per policy | W6 |
| #107 CLI | Folder from the environment, then `manager.env`, then the default; refuse a missing folder; exit 0 committed, 1 failed, 2 configuration | W7 |
| #1 sink gate on delete | Yes: refused during a sink outage, like other sensitive actions | W9 |
| PD-34 UI scope | Profiles list and detail for everyone; upload, status, delete, rebuild and import history for admins; no editor | W11 |
| PD-35 approvals | As in the section above | each wave |
| #11 operators | Keep as written (M8) | — |

Full text, sections and alternatives: `work/open-questions.md`, section "M7".

## Coverage

Covered: TS §1.1 G4 and G5; §1.4; §4.1 every paragraph; §4.2; §4.3; §4.6; §5.2 catalog tables and grants (used as migrated); §6.2 every policy, import, rebuild, task and delete route; §6.3 multipart and the `.bit` cap; §8.1 import controls and parser threats; §8.3 Unit, Property/fuzz, Integration and Security (importer half); §8.4 import alerts and metric; §8.7 `bits rebuild`; SR §1 to §4 in full (operator semantics excepted).

Not in M7, with the milestone: the evaluator and operator semantics (TS §4.5, SR §2.4 table: M8, which reuses M7's number grammar and RE2 helper); scan building, scan refusals for disabled or deleted policies and scan-state derivation after a delete cancels jobs (TS §4.4: M9); the sandbox half of TS §8.3 Sandbox (M10); the import step of the nightly end-to-end run and the results CSV (M11).

## Files written by the planner

- `work/requirements.md` (section "M7 compliance catalog")
- `work/tasks.md` (section "M7 compliance catalog": design notes D1 to D5, tasks, owner notes, test plan, waves, gate, mutation table, open items, coverage)
- `work/open-questions.md` (section "M7")
- `work/plans/M7-breakdown.md` (this file)
