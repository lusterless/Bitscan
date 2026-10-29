# TASK-167 IMPL: README, the M7 user guide

Owner: impl-manager-m7b. REQ-184. Risk: low (docs). Sources: TS §4.1–§4.3 (L513–L551), §4.6 (L607–L615), §8.7 (L1347); SR §1.1, §2, §4; #100 (d) (audit-sink entry size), #102 (b), #107; the TASK-159 carry (hard links); the decisions rows of 2026-10-27/28.

## What changed

`README.md` only. The new section **"Policies"** sits between "Package search" and "Users", about 97 lines. Three stale lines elsewhere were updated:
- The intro's route list now names `/api/v1/policies`, `/api/v1/imports` and `/api/v1/tasks`.
- The intro gains a line on the folder watcher, and `bits rebuild` joins the server commands.
- "Starting the app": `bits rebuild` is now listed among the working commands; it no longer says "not yet implemented".

## REQ-184 coverage

| REQ-184 item | Where |
| --- | --- |
| The `.bit` format in brief, pointing at SR | "Policies" opening paragraph (links SR and its §1.1 example) |
| Loading policies: the server folder | "Loading policies": the watcher, start-up, the #102 (b) name rules, **"don't hard-link files into the bits folder"** (TASK-159 carry), rename in place, BIT007 and the #15 order |
| Loading policies: upload in the UI or with an admin `bsk_` and `curl -F file=@x.bit` | "Loading policies": the upload with a `curl -F file=@…` example, the 200 answer shape, 413, 409 `policy_managed_on_server`, the server folder winning |
| What an import does: validation and the BIT codes, live at once, alerts | "What an import does" |
| Status and the override | "Status, delete and history" |
| Delete | "Status, delete and history": TOTP session, sink gate, 204/404/409, and how a deleted policy comes back |
| Rebuild: UI, API, `sudo bitscan-manager bits rebuild` | "Rebuild": the API with the task result fields (`removed_leftovers`, `not_imported`), the CLI (folder per #107, output lines, exit codes), and start-up (integrity alert, leftovers, 503 Retry-After) |
| The import history | "Status, delete and history" (`GET /imports`) |
| #100 note on audit-sink entry size | "What an import does": "Audit-sink entry size" (about 10 MiB; syslog receivers often cut at 8 KiB) |

Every behaviour statement was written from the code as built:
- `api/user/policies.py`, `policy_import.py`, `imports.py` and `rebuild.py`;
- `cli/bits.py`;
- `services/importer/folders.py`, `watcher.py`, `alerts.py` (alert kinds) and `rebuild.py`.

## Notes for the tester (one docs test against a WSL manager)

- **No secrets or process notes:** the README holds no real token or secret, no task id and no process note (checked with a grep for `bsk_…`, `TASK-` and task-id UUIDs).
- **Web UI wording is generic.** The UI is mentioned only as "or upload in the web UI", plus the existing Profiles page, because the policy screens (TASK-169–173) are being built in parallel. If those screens add their own README lines, impl-web or the lead adds them.
- **Watcher steps** ("a few seconds after", removal deletes) need Linux with inotify; on Windows the watcher doesn't start.
- **The `bits rebuild` step** needs `sudo` and a readable `/etc/bitscan/secrets/app.dsn` on the WSL manager.

## Revision 1 (2026-10-28): 503 after an upload, and the web UI pages (TEST F1)

1. **The 503 line.** From reviewer-m7's routes nit. One bullet is added to the upload answers in "Loading policies". A 503 after an upload, including the import route's "The import was stored but its record could not be written.", means the policy may already be live, so check the policy list or the import history before uploading again. The quoted text matches `_NOT_RECORDED` in `api/user/policy_import.py`.
2. **F1 (tester-m7w): REQ-184's rebuild "UI" path, and the stale role table.** The facts come from `work/reports/TASK-168-173-impl.md` (TASK-169 to 173).
   - **Web UI, "Pages by role":**
     - Profiles and profile detail are added for every role.
     - A new row, Upload policy, Import history, Rebuild catalog, is admin only.
     - The TOTP sentence now also covers deleting a profile and rebuilding the catalog.
   - **Four page bullets:**
     - **Profiles:** the filter, the detail page, the admin buttons (Enable/Disable, Clear override, Delete with confirmation), and Deleted showing no actions.
     - **Upload policy:** Imported or Rejected, plus the findings.
     - **Import history.**
     - **Rebuild catalog:** a link to Rebuild.
   - **"Policies" → "Rebuild":** a new "In the web UI" paragraph. Press Rebuild and confirm; the page follows the task until it succeeds or fails, then lists the files, the files not imported, the deleted policies and the removed leftovers.
   - **"Loading policies":** the upload sentence now names the **Upload policy** page.
   - **Superseded:** the earlier note "Web UI wording is generic" no longer applies.

Nothing else changed.

## Revision 2 (2026-10-28): N1 wording

From tester-m7w's non-blocking note N1, applied at the lead's request; no re-test is needed. The 503 bullet now keeps the general advice for any 503 after an upload: check the policy list or the import history. It adds, in tester-m7w's wording, that after "The import was stored but its record could not be written." you check the policy list (its version and imported time), because that case has no import-history row. One README line changed.
