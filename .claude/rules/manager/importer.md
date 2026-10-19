---
paths:
  - "manager/**/services/importer/**"
---

# `.bit` importer: pipeline, storage, rebuild and delete

Pipeline, loading and deletion: TS §4.1–§4.3 and §4.6. Per-file algorithm: SR §3.6. File format and validation codes: `.claude/rules/manager/bit-format.md` (also loads here). All load routes (UI or API upload, folder watcher, CLI) use this one pipeline. Only admins create or update policies; a successful import is live immediately (no approval or diff step).

## Pipeline (TS §4.1, SR §3.6)

1. Discover `*.bit` files in `/var/lib/bitscan/bits/` (server administrators) and `/var/lib/bitscan/bits/uploaded/` (written by the manager). Watch both with inotify, `*.bit` only, no subfolders.
2. Read the file into memory once; hash and parse from that buffer. Never re-read it.
3. Parse with `defusedxml` (no DTD, no external entities): at most 5 MB and 5,000 plugins.
4. Validate with every SR §4 rule. One Reject rejects the whole file. BIT001 and BIT002 run first; if either fails, skip the content rules.
5. Upsert `policy`, `family`, `plugin` and `policy_plugin` in one transaction. `version` goes up by 1 only when the file hash changes. Retire plugins that no policy uses any more; never delete them.
6. Write the `bit_import` row in its own transaction, so rejected imports are logged too.

- Per file (SR §3.6): upsert `family` by `family_name`; upsert `policy` by `policy_name` (or rename in place, below); set `file_status`, and `policy_status` too unless `status_overridden`, so a file update never re-enables a profile an admin disabled; clear `deleted_at`; upsert each `plugin` by `plugin_uuid` with `owner_policy_id` = this policy and `state = active`; replace `policy_plugin` with 1-based `sort_order` in document order; retire unreferenced plugins; commit, or roll back the whole file on any error.
- System columns (`version`, `source_file`, `source_sha256`, `execute_sha256`, `status_overridden`, `deleted_at`) are set by the importer, never from the file. `source_file` is the path relative to `/var/lib/bitscan/bits/`.
- `bit_import`: `file_name`, `file_sha256`, `policy_version` (after success), `mode` (`auto`, `manual`, `rebuild`), `outcome` (`success`, `skipped`, `rejected`), plugin counts, `errors` as `[{line, element, code, message}]`, `imported_by` (NULL = system). It is a log: never truncated or rebuilt.
- **Open spec question:** SR §3.5 does not define how `plugins_added`, `plugins_updated` and `plugins_retired` are counted (`work/open-questions.md` #21).
- Automatic imports skip a file whose hash equals the last successful import (`outcome = 'skipped'`). Manual imports and rebuilds never skip.
- A new version is live as soon as it is stored. Already queued jobs keep the commands they were built with.
- Locking: every import, rebuild and delete takes `pg_advisory_lock(hashtext('catalog'))` before its transaction and releases it only after the upload's file rename or deletion.
- Every import is audit-logged and alerts; the alert carries every changed `Execute` and flags paths matching `shadow`, `.ssh`, `.pem`, `.key`, `token` or `credentials`. A rejected import also alerts.
- **Open spec question:** whether `skipped` automatic imports, and each file of a rebuild, raise the immediate "policy imported" alert (TS §4.1, §8.4) (`work/open-questions.md` #23).

## Uploads and folders

- Inside the catalog lock, write the upload to `uploaded/.tmp-<policy_id>-<sha256>` (`O_NOFOLLOW | O_EXCL`) before the import transaction commits, and rename it to `uploaded/policy-<policy_id>.bit` only after it commits, replacing the previous upload. If the import rolls back, delete the temp file: only a successful import keeps the file. Ignore the client file name; keep it only in `bit_import.file_name`.
- A rejected upload leaves the existing file and catalog untouched.
- Uploading a policy whose `source_file` is in the server folder returns 409 `policy_managed_on_server`.
- If a server-folder file and an uploaded policy share a `PolicyName`, the server folder wins: move the policy, delete the uploaded copy and audit-log the move. A rebuild does the same.
- **Open spec question:** an oversize `.bit` upload is a 413 (TS §6.3) and also BIT001 (SR §4.1); ask whether a 413-rejected upload writes a `bit_import` row.
- At start-up (TS §4.1):
  1. Before anything else, finish interrupted uploads: rename a temp file whose hash equals the policy's `source_sha256`, and delete any other temp file.
  2. Then reconcile both folders with the catalog: import new or changed files, and delete (as below) policies whose files disappeared.
- Also at start-up (TS §4.2, no order given): mark `running` tasks `failed`, and run the integrity check (compare row counts and a hash per policy with the files in both folders; alert on any difference).
- **Open spec question:** whether the integrity check runs before or after the reconcile (`work/open-questions.md` #27).

## Rebuild and delete

- Rebuild (`bitscan-manager bits rebuild` or `POST /policies/rebuild`, TOTP session) re-imports every file in both folders, one savepoint per file, upserting by natural key (`policy_name`, `family_name`, `plugin_uuid`). A rejected file keeps its catalog rows and is reported; the rebuild commits as a whole. Policies whose files are gone are deleted; unreferenced plugins retired. Never truncate catalog tables (TS §4.2), and never touch `agent`, inventory, `scan_*` or audit tables. Track it in the `task` table. Every rebuild alerts. Catalog corruption is fixed by rebuild, not restore.
- **Open spec question:** whether a rebuild that rejected some files ends `succeeded` or `failed` in `task.state` (`work/open-questions.md` #20).
- Delete (TS §4.3, `DELETE /policies/{id}`, admin with TOTP session) is soft:
  - set `deleted_at`;
  - set `source_file` to `deleted/<policy_id>`;
  - cancel queued jobs and disable schedules;
  - retire the plugins;
  - remove the uploaded file.

  Every delete alerts and is audit-logged. A server-folder policy returns 409 `policy_managed_on_server`; removing its file deletes it the same way at the next watcher event or rebuild. Uploading the same name later brings it back as a new version.
- **Open spec question:** SR §3.6 adds 1 to `version` only when the file hash differs from `source_sha256`, so an identical re-upload would keep the old version; ask which applies and whether disabled schedules and `status_overridden` survive the revival (`work/open-questions.md` #14).
- Renaming `<PolicyName>` inside the same server-folder file renames that policy in place (same id, plugins and history), unless it is deleted. An uploaded policy is renamed by deleting it and uploading under the new name; BIT015 lets the new policy claim plugins whose owner is deleted or no longer lists them.

Tests (TS §8.3): Unit (parser), Property/fuzz (random and malformed XML: no crash, no partial import), Integration (rebuild on a corrupted catalog; concurrent upload and rebuild serialise, TS §4.1), Security (non-admins refused for upload and delete, hostile upload file names stored safely, BIT015 rejections).
