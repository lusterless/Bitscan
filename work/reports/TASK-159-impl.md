# TASK-159 IMPL: folder watcher (inotify binding, events, self-event record)

Owner: impl-manager-m7b. REQ-164. Risk: high (importer; two approvals). Depends on TASK-156 (APPROVED; r1 renames).

Spec and rulings: TS §4.1 L528 ("watches both folders (inotify, `*.bit` files only, no subfolders)"), L526 (locking), §4.6 (L612, L615); #102 (a)–(d); PD-33 (b).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/inotify.py` | new: the stdlib `ctypes` binding | 73 |
| `manager/bitscan_manager/services/importer/watcher.py` | new: `Watcher` | 155 |
| `manager/bitscan_manager/services/importer/own_changes.py` | new: `OwnChanges`, `OWN_CHANGES` (#102 (c)), a neutral module (ruling "#102 (c) wiring" (a)) | 51 |

`folders.py` changed as TASK-156 r2 (see that report). No other file was changed.

**Size: 279 lines against an estimate of 190**, accepted by the lead (ruling "#102 (c) wiring").
- The #102 (c) recorder that the brief asked for here (`OwnChanges`, thread-safe, 60 s expiry, a match used up once, lazy hashing) is about 45 lines.
- The binding is 73 lines against PD-33's "about 60": it adds the event parser and the `select`-based timeout, so the watcher can stop.

## inotify.py (PD-33 (b))

- **`available()`** is `sys.platform.startswith("linux")`.
- **`Inotify()`** calls `inotify_init1(IN_NONBLOCK | IN_CLOEXEC)` through `ctypes.CDLL(None, use_errno=True)`.
- **`add_watch(path, mask) -> wd`** calls `inotify_add_watch`, with the path passed through `os.fsencode`.
- **`read(timeout) -> list[Event]`** waits with `select.select`, then calls `os.read(fd, 64 KiB)` and parses `struct inotify_event` (`"iIII"` plus a NUL-padded name). Each `Event` has `wd`, `mask` and `name` (`os.fsdecode`, so an invalid UTF-8 name decodes to surrogates).
- **`close()`** closes the descriptor.
- The constants are the Linux ABI values, written as literals because `os.O_CLOEXEC` is missing on Windows.
- Errors raise `OSError` with the errno.

## watcher.py

### Events (#102 (a))

| Event | Action |
| --- | --- |
| `IN_CLOSE_WRITE`, `IN_MOVED_TO` | `folders.import_path(session, clock, bits_dir, rel)` in `auto` mode |
| `IN_DELETE`, `IN_MOVED_FROM` | delete the live policy whose `source_file` is that path, if any: `catalog.policy_by_source_file_for_update`, then `delete.delete_in_tx(reason="file removed", actor="system")`, then `delete.remove_after_commit` |
| `IN_Q_OVERFLOW`, `IN_IGNORED`, `IN_DELETE_SELF`, `IN_MOVE_SELF`, an unknown watch descriptor, or `uploaded` itself created, moved or deleted (an `IN_ISDIR` entry of the server folder) | re-add both watches, then `folders.reconcile` |

- **A deleted file that is back.** If the file exists again when its deletion is handled (for example an editor that deletes and rewrites), it is imported instead of deleting its policy. This keeps disk and catalog equal (TS L526) and avoids a delete-then-revive. It is a small refinement of #102 (a), and errs toward keeping the policy.
- **Which names count.** Only direct entries of the two folders count (TS L528; inotify doesn't report entries in subfolders). The name must end in `.bit` and not start with `.`, so `n.txt`, `.n.bit` and `.tmp-…` are ignored. `IN_ISDIR` entries are ignored, apart from `uploaded`. A name `folders.storable` refuses is skipped with one fixed log line.
- **Batching.** The events from one read are coalesced, and the last event for a path wins. Each path is then handled in its own `db.session()` under `catalog_lock(session)` ("each event handled under the catalog lock").
- **Failure.** If handling fails (for example the database is down), one error line logs only the exception type. A full reconcile then follows, retried every `RETRY` = 10 s, the same interval #102 (d) uses at start-up. Events read while it waits are covered by that reconcile.

### Lifecycle (for TASK-160)

- `Watcher(db, clock, bits_dir, own=OWN_CHANGES)`.
- `open() -> bool` adds the watches (mask `IN_CLOSE_WRITE | IN_MOVED_TO | IN_MOVED_FROM | IN_DELETE | IN_CREATE | IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK`) on the server folder and on `uploaded/` if it exists; `uploaded/` is added later if it appears. Where inotify is missing, it logs one line ("folder watcher not started: inotify is not available here") and returns False. A failed `inotify_init1` or `add_watch` logs one line with the exception type and returns False.
- `run(stop: threading.Event, poll=1.0)` loops until `stop` is set, checking it at least once per `poll` seconds, then closes the descriptor. It calls `open()` itself if needed and returns at once where that fails, so it is safe on Windows.
- **Suggestion for TASK-160:** call `open()` before the start-up reconcile and `run()` after it. Changes made during the reconcile are then queued and handled, instead of being lost between the reconcile and the watch.
- **Carried (already open for TASK-160):** a handler waiting on the catalog lock has no timeout, so `stop` takes effect only after that wait ends.

### The #102 (c) record: `own_changes.OwnChanges` and `OWN_CHANGES`

- **Where it lives.** `own_changes.py` imports nothing from the importer (only `threading`, `time`, `collections.abc` and `typing`). So every writer (`uploads`, `delete`, `folders`) and `watcher.py` import it with no cycle, and `watcher.py` now imports `folders` and `delete` at module level.
- **Record before the call** (ruling (b)). A writer calls `wrote` or `removed` just BEFORE its `os.replace` or `unlink`, under the catalog lock, so even an inotify event read at once finds its record.

- `wrote(rel, sha256)`: call just before renaming a file into place.
- `removed(rel)`: call just before unlinking a `*.bit` file.
- `rel` is relative to the bits folder, for example `uploaded/policy-7.bit`.
- Records expire after 60 s (`time.monotonic`), and each record is used up by one matching event.
- `drop_write(rel, current)` matches only if the file's SHA-256 now equals the recorded one. It computes the hash through `folders.read_file`, and only when an unexpired record for `rel` exists, so a real admin edit right after one of ours is still handled.
- `drop_removal(rel)` matches on the path; the file is gone, so it has no hash.
- The watcher also checks the record only after taking the lock for that path. A record made before a call that then fails can drop one real event at that path within 60 s; the reconcile at the next start-up covers that case.

## Wiring (ruling "#102 (c) wiring" (b)–(c))

Each writer imports `from bitscan_manager.services.importer.own_changes import OWN_CHANGES` and makes one call just before its rename or unlink.

| # | File and site | Call | Done by |
| --- | --- | --- | --- |
| 1 | `uploads.py`, `UploadStage.after_commit`, before `os.replace(temp, final)` | `OWN_CHANGES.wrote(f"uploaded/policy-{policy_id}.bit", sha256)` | impl-manager-m7, TASK-155 r2 |
| 2 | `uploads.py`, `finish_interrupted`, before `os.replace(path, target)` | `OWN_CHANGES.wrote(f"uploaded/{target.name}", row.source_sha256)`. The `.tmp-` unlinks need no record, because their names are hidden and ignored. | impl-manager-m7, TASK-155 r2 |
| 3 | `delete.py`, `remove_after_commit`, before each `unlink` | `OWN_CHANGES.removed(f"uploaded/{name}")`. This covers the API delete, the pipeline's post-commit removals, and the reconcile's and watcher's deletions. | impl-manager-m7, TASK-152 r1 |
| 4 | `folders.py`, `Relocate.after_commit`, before `self.path.unlink()` | `OWN_CHANGES.removed(f"uploaded/{self.path.name}")` | done (TASK-156 r2) |
| 5 | `folders.py`, `_remove_leftover`, before the unlink | `OWN_CHANGES.removed(rel)` | done (TASK-156 r2) |

I sent impl-manager-m7 the API and these three sites on 2026-10-28. REQ-164 (4) can pass only once #1 (and #2 for the start-up finish) are in.

## Checks run here (scratch, outside the tree; the tests are the tester's)

- **Gates**, re-run after the move:
  - `ruff check manager/bitscan_manager` is clean. The whole-tree `ruff check manager` currently flags only F821 in the tester's in-progress `manager/tests/test_import_pipeline_pg.py:691`.
  - `ruff format --check manager` is clean (295 files).
  - `mypy --strict --config-file manager/pyproject.toml manager` is clean (295 files).
- **Smoke** (`C:\Users\kaiquan.koh\scratch\task159\smoke.py`, Windows, fakes for the database, lock, `folders` and `delete`):
  - **`OwnChanges`:**
    - a write with the same hash is dropped, and dropped only once;
    - a different hash is not dropped;
    - a removal is no longer dropped after 61 s;
    - no hash is computed when no record exists.
  - **`open()` on Windows:** logs one line and returns False.
  - **Event routing:**
    - `a.bit` and `uploaded/policy-3.bit` are imported;
    - `n.txt`, `.n.bit` and the subfolder `sub` are ignored;
    - `gone.bit` deletes policy 5 with "file removed";
    - `other.bit` (no policy) does nothing;
    - `b.bit` written then deleted in one batch counts as deleted, and, gone with no policy, does nothing.
  - **Rescans:** an overflow, and the creation of `uploaded`, each cause a rewatch and one reconcile.
  - **Own rename:** a recorded `IN_MOVED_TO uploaded/policy-4.bit` with a matching hash is dropped, and nothing is imported.

## For the tester (TP-M7-?, Linux with temporary folders and PostgreSQL)

- **Row checks:** REQ-164 (1), (3) and (4) within 5 s. Events for `n.txt`, `.n.bit` and `sub/n.bit` do nothing. On Windows, `open()` logs one line and `run()` returns.
- **REQ-164 (4) needs wiring #1** (and #2 for the start-up finish) before it can pass.
- **Plants:**
  - Use `IN_MODIFY` instead of `IN_CLOSE_WRITE`: REQ-164 (3) imports more than once.
  - Drop the `startswith(".")` test: `.n.bit` is imported.
  - Drop the `IN_ISDIR` branch: the subfolder rows break.
  - Make `drop_write` ignore the hash: an admin edit within 60 s of an upload is lost.
  - Never use up a match: a second identical event is dropped.
  - Check `OWN_CHANGES` before taking the lock: the own-rename race reappears.
  - Move a writer's record to after its call: a fast event can be handled before the record exists.
  - Remove the "back again" import: a delete-then-rewrite deletes and revives the policy.
  - Skip the rescan on `IN_Q_OVERFLOW`: overflow changes are missed.

## Revision 1 (2026-10-28): incoming paths first

Decisions row "W6 pre-read rulings" (2), from reviewer-m7's pre-read. `Watcher._handle` still coalesces each batch (the last event per path wins). It now handles the incoming paths (`IN_CLOSE_WRITE`, `IN_MOVED_TO`) before the outgoing ones (`IN_DELETE`, `IN_MOVED_FROM`), using a stable sort, so the order within each group is kept.

- **The case this fixes.** With `mv a.bit c.bit` in one batch, `c.bit` is imported first. decide sees that `a.bit`, its policy's file, is gone, and takes `move_server`: the same policy id and one move audit entry, with nothing deleted or disabled. The `a.bit` removal then finds no live policy with that `source_file` and does nothing.
- **Kept as before.** The "file is back, so import instead" rule for an outgoing path is unchanged.
- **Size.** `watcher.py` is 158 non-blank lines.
- **Checks.** Gates are clean: `ruff check manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml manager`, all on 296 files. Scratch smoke: the batch `[IN_MOVED_FROM a.bit, IN_MOVED_TO c.bit]` is handled as `c.bit` in, then `a.bit` out.
- **Plant:** restore the event order (iterate `changes.items()` unsorted). The smoke run then handles `a.bit` out before `c.bit` in. On PostgreSQL that soft-deletes the policy (delete alert, queued jobs cancelled, schedules disabled), and `c.bit` then revives it, with the version bumped. The expected result without the plant is one move entry, the same policy id, and no delete.
