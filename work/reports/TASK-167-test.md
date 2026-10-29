# TASK-167 TEST: README, the M7 user guide (TP-M7-28)

**Verdict: PASS (round 2, on TASK-167 r1)**
- Round 1 was FAIL on F1, below. r1 fixed F1 and added the "503 after an upload" line; see "Round 2" at the end.
- The live WSL walk (CHK-M7-305) is still NOT RUN; main decides whether it is needed at the gate.

Tester: tester-m7w. Worktree `Bitscan-m7`, branch `m7-catalog`, `README.md` uncommitted. Windows 11 + Git Bash. Low risk (docs): one test run and one review.
REQ-184. Sources checked against: `manager/openapi.json`, `manager/bitscan_manager/cli/{bits,users,__init__}.py`, `config/startup.py`, `api/user/{policies,policy_import,imports,rebuild}.py` (auth dependencies), `services/importer/folders.py` (name rules, order), SR §4.1–§4.2, TS §4.3, §6.2.

## Scope
- main scoped this run to a static walk of the new "Policies" section: commands and routes against `openapi.json` and `cli/bits.py`, links, no secrets or ids, and the hard-link line, one row per REQ-184 item.
- The task row's live walk against a WSL manager (CHK-M7-305, REQ-184 acceptance (1)) is **NOT RUN** here. This run is Windows only and the W environment belongs to tester-m7. Behaviour that only a live manager can show is listed under "Not run".

## Commands
- `python -I deploy/tests/check_md_links.py README.md` → `OK 21 relative links checked, 0 findings`, exit 0.
- `python -I %TEMP%\m7w-scripts\readme_walk.py <worktree>`: a read-only script outside the tree. It extracts the section's routes, field lists, enums, statuses and CLI statements and compares them with the sources. It printed 66 rows: 64 true, 2 false (F1).
- Manual reading of the section against the code paths named above.

## Rows

| Check | Item | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-306 (a) | Every route and method named in "Policies" exists in `openapi.json` | PASS | named = the 8 M7 operations exactly (GET/PATCH/DELETE `/policies/{id}`, GET `/policies`, POST `/policies/import`, POST `/policies/rebuild`, GET `/imports`, GET `/tasks/{id}`); 0 unknown; the `{policy_id}` and `{task_id}` placeholders match the `{id}` parameters |
| CHK-M7-306 (b) | Every `{field, …}` list matches its schema | PASS | ImportResult (9), PolicyItem (14), detail adds exactly `deleted_at` and `plugins`, ImportItem (12), TaskItem (7), TaskResult (5), TaskFile (5), ImportFinding (4), TaskFailure (1), RebuildStarted `{task_id}` |
| CHK-M7-306 (b) | Enums and PATCH bodies | PASS | `mode` auto/manual/rebuild; ImportItem `outcome` success/skipped/rejected; ImportResult `outcome` success/rejected; `state` running/succeeded/failed; PatchPolicy has only `policy_status` and `status_overridden` |
| CHK-M7-306 (b) | Statuses stated | PASS | import 200/409/413/503; DELETE 204/404/409/503; PATCH 409; rebuild 202/503; all appear in the openapi responses |
| CHK-M7-306 (b) | Who may call what | PASS | PATCH `require_role("admin")` (session or API token); DELETE and POST rebuild `require_totp_session()`; GET `/imports` and `/tasks/{id}` admin; upload admin (API token allowed, TS §6.2 L1084) |
| CHK-M7-306 (c) | `sudo bitscan-manager bits rebuild` and each statement about it | PASS | dispatch in `cli/__init__.py` (`["bits"]` → `bits_main`, subcommand `rebuild`); DSN `/etc/bitscan/secrets/app.dsn` (`APP_DSN_FILE`); actor `cli:root`; folder `BITSCAN_BITS_DIR` → `/etc/bitscan/manager.env` → `/var/lib/bitscan/bits`; `uploaded/` must exist; output lines `success <file> policy <id> version <n>`, `rejected <file> (<n> findings)`, `not imported`, `removed leftover`, `deleted policy <id>`, summary; exit 0/1/2 as in `bits.py` |
| CHK-M7-306 (c) | `curl -F file=@x.bit` example | PASS | `curl -s https://manager.example:8443/api/v1/policies/import -H 'Authorization: Bearer <token>' -F file=@cis-ubuntu-24.04.bit` |
| CHK-M7-306 (c) | Folder rules | PASS | `.bit` suffix, no leading dot, `O_NOFOLLOW`, 255-byte cap (`folders.py` L50–L122); new files ordered by `p.encode("utf-8")` (L257), matching "sorts first byte by byte" |
| CHK-M7-307 | Links resolve | PASS | 21 relative links, 0 findings, including `#policies` and `docs/spec/bit_Schema_Reference.md` |
| CHK-M7-308 | No real token or secret | PASS | 0 hits for `bs[usae]_` + 20 or more chars, private keys or password values in the whole README; the curl uses `<token>` |
| CHK-M7-308 | No task id or process note | PASS | 0 hits in "Policies" for `TASK-`, `REQ-`, `CHK-`, `PD-`, `#nn` question refs, team roles, `work/` or UUIDs; 0 `TASK-`, `CHK-` or `PD-` in the whole README |
| CHK-M7-309 | "don't hard-link files into the bits folder" line | PASS | "**Copy or move files into the folder; don't hard-link files into the bits folder.**" |
| CHK-M7-309 | REQ-184: `.bit` format in brief, pointing at SR | PASS | opening paragraph links SR and its §1.1 example; `<PolicyName>` is the key, file names never are |
| CHK-M7-309 | REQ-184: loading, server folder | PASS | "**The server folder.**" (watcher, start-up, name rules, rename in place, BIT007, order) |
| CHK-M7-309 | REQ-184: upload in the UI or with an admin `bsk_` and `curl -F` | PASS | "Use a session or an admin's `bsk_` API token, or upload in the web UI", plus the curl |
| CHK-M7-309 | REQ-184: what an import does (validation, BIT codes, live at once, alerts) | PASS | "What an import does"; BIT102 examples are all in SR §4.2 L279–L285 |
| CHK-M7-309 | REQ-184: status and the override | PASS | the PATCH bodies; "Later file updates then change only `file_status`" (TS §4.3 L548) |
| CHK-M7-309 | REQ-184: delete | PASS | TOTP session, API token refused, 15-minute sink gate, 204/404/409, `policy_managed_on_server`, revival |
| CHK-M7-309 | REQ-184: rebuild through the API and the CLI | PASS | "Through the API" and "On the server" |
| CHK-M7-309 | **REQ-184: rebuild through the UI** | **FAIL (F1)** | no UI path for rebuild anywhere in the README |
| CHK-M7-309 | REQ-184: import history | PASS | `GET /api/v1/imports` with fields, mode and outcome |
| CHK-M7-309 | REQ-184: #100 audit-sink entry size | PASS | "**Audit-sink entry size.**" (about 10 MiB; syslog often 8 KiB) |
| CHK-M7-309 | **The Web UI section names the M7 screens** | **FAIL (F1)** | "Pages by role" (README L227–L232) still lists only the M5 pages: no Profiles, Upload policy, Import history or Rebuild catalog |

## F1 (owner: impl-manager-m7b, README; the page names come from impl-web's TASK-173)
- **Expected (REQ-184):** the guide covers "rebuild (UI, API, `sudo bitscan-manager bits rebuild`)".
- **Actual:** the Rebuild section has only "Through the API", "On the server" and "At start-up".
- **Related stale text:** the Web UI section's "Pages by role" table (README L227–L232) shows only Hosts, host detail, Package search, TOTP and Password for every role, and the two Enrolment pages for admins. The UI now also has:
  - **Profiles** and profile detail for every role, with the admin status actions and Delete (TOTP session);
  - **Upload policy**, **Import history** and **Rebuild catalog** for admins (TASK-173; nav labels and hashes in `work/reports/TASK-168-173-impl.md`).
- **Diagnosis:** the impl report says the UI wording was kept generic because the screens were built in parallel. Its line "plus the existing Profiles page" has no matching text: "Profiles" appears nowhere in the Web UI section.
- **Suggested fix (the owner decides wording):** add the four pages to the "Pages by role" table. Add one line in "Rebuild": "In the web UI: **Rebuild catalog** (admin, TOTP-verified session), then confirm; the page follows the task until it succeeds or fails and lists the files." Optionally mention **Upload policy** and **Import history** in their sections.
- **Re-test:** re-run `readme_walk.py` (the two rows) and `check_md_links.py`.

## Not run (live behaviour; CHK-M7-305, WSL manager)
- That the watcher imports "a few seconds after" a file is written or moved in, and that removal deletes. This needs inotify on Linux.
- That the curl upload, PATCH, DELETE, rebuild and `sudo bitscan-manager bits rebuild` behave as written against a running manager.

The static rows above show that each statement matches the code as built. main decides whether the live walk is still needed at the M7 gate.

## Observation (no change requested)
"The codes `BIT001`–`BIT017` and `BIT102` reject the file" reads as a range. SR §4.1 L250 retires BIT006 and BIT009, so the range has gaps, but every live code in it is Reject; the statement is true.

## Round 2 (TASK-167 r1; README sha256 `1a651f0c…88191b`)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M7-309 rebuild through the UI (F1) | `readme_walk.py` | PASS | "**In the web UI (admin, TOTP-verified session).** On **Rebuild catalog**, press **Rebuild** and confirm…", matching `Rebuild.tsx` and CHK-M7-389 (confirm, one POST, polls to succeeded or failed, then files, not imported, deleted policies, leftovers) |
| CHK-M7-309 Web UI names the M7 screens (F1) | `readme_walk.py` + reading | PASS | "Pages by role": Profiles and profile detail for every role; Upload policy, Import history and Rebuild catalog admin only (matches `ROUTE_ROLES`, CHK-M5-280). The TOTP sentence covers profile delete and rebuild (TS §6.2). The page bullets match CHK-M7-312 to -314 and -388: filter All/Enabled/Disabled; admin Enable or Disable, Clear override, Delete with confirmation; Deleted shows no actions; Imported or Rejected with findings; history newest first |
| CHK-M7-309 upload names the UI page | `readme_walk.py` | PASS | "an admin's `bsk_` API token, or the web UI's **Upload policy** page" (my needle was loosened to this meaning; the wording changed, the item didn't) |
| r1 line: a 503 after an upload | reading against `api/user/policy_import.py` | PASS | the quoted text is the route's `_NOT_RECORDED` (L46), raised as 503 `about:blank` when the catalog committed without its `bit_import` row (L164–L166); "may already be live" is right for it. See N1 |
| All other 306 to 309 rows | `python -I readme_walk.py <worktree>` | PASS | **66/66 true** (routes, field lists, enums, statuses, CLI, no token, task, check or process id, hard-link line) |
| CHK-M7-307 links | `python -I deploy/tests/check_md_links.py README.md` | PASS | `OK 22 relative links checked, 0 findings` (the new `#rebuild` resolves) |

N1 (non-blocking, for the reviewer):
- **Issue:** for the quoted 503, "Check the policy list or the import history" can find the import only in the policy list. That case is by definition the one where the `bit_import` row was not written, so the import history has no entry.
- **Risk:** a reader who checks only the history and re-uploads does no harm; a manual re-import of the same content changes nothing.
- **Clearer wording:** "check the policy list (its version and imported time); this case has no import-history row".

Round 2 verdict: **PASS** (static walk). The live walk (CHK-M7-305) is still NOT RUN; see "Not run".
