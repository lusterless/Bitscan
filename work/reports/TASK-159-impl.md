# TASK-159 IMPL: folder watcher (inotify through ctypes)

Implementer: impl-manager-159. Spec: TS §4.1 L528, §4.2, §4.6, §8.7. REQ-164 (1), (3), (4), (5). Also #102 (a), (c), #98 (j), PD-33 (b), and the user's "Folder guard" ruling plus "Folder guard details" (decisions 2026-10-27).

**Revision 1 (2026-10-28, lead rulings in work/decisions.md).**
- (1) The catalog-based self-event check is adopted. It amends #102 (c).
- (2) Batches now call the TASK-156 r5 one-file entry point `folders.reconcile_paths(session, clock, bits_dir, changed)`, with only the paths whose disk hash differs from the catalog. A queue overflow, a lost watch or a re-arm still runs the full `folders.reconcile`.
- (3) The size, about 230 code lines, is accepted.

r1 changed `watcher.py` only: `_handle`, `_changed` (which now returns the changed paths) and the module docstring.

## Files (both new; no other file changed)

- `manager/bitscan_manager/services/importer/inotify.py`: 111 physical lines, 92 non-blank.
- `manager/bitscan_manager/services/importer/watcher.py`: 224 physical lines at r1, about 65 of them docstrings.

Together they come to about 230 code lines against the ~190 estimate. That is over budget, and the lead needs to accept it or split the task. A natural split would be `inotify.py` on its own, but it cannot be tested on its own in any useful way.

## The ctypes binding (`inotify.py`)

- `_libc()` (:46) returns `InotifyUnavailable` in three cases: not Linux, `ctypes.CDLL` failing (OSError), or a missing `inotify_*` symbol (AttributeError). It loads `find_library("c")` (falling back to `libc.so.6`) with `use_errno=True`, and sets `argtypes` and `restype` for `inotify_init1`, `inotify_add_watch` and `inotify_rm_watch`.
- `Inotify.__init__` (:68) calls `inotify_init1(O_NONBLOCK | O_CLOEXEC)`. On −1 it raises `InotifyUnavailable(strerror(errno))`.
- `add_watch(path, mask)` raises `OSError(errno)` on −1. For example, IN_ONLYDIR gives ENOTDIR and IN_DONTFOLLOW gives ELOOP. `rm_watch` ignores errors, because the kernel may already have dropped the watch (IN_IGNORED).
- `read()` (:91) calls `os.read` with 64 KiB and returns `[]` on `BlockingIOError`. It parses `struct inotify_event` (`"iIII"` plus `len` name bytes, NUL-padded) and decodes names with `os.fsdecode`.
- The mask constants come from `<sys/inotify.h>` and are the same on amd64 and arm64.

## Watcher design (`watcher.py`, class `FolderWatcher(db, clock, bits_dir)`)

- `start() -> bool`: on `InotifyUnavailable` it logs one line, `folder watcher not started: inotify is not available` (:63), and returns False with no thread. Otherwise it creates a non-blocking wake pipe, arms the watches and starts the daemon thread `folder-watcher`. `stop(timeout_s=5.0)` sets the stop flag, writes to the wake pipe and joins. It closes the descriptors only if the thread has ended (a thread stuck in a reconcile keeps its descriptors). Both methods are for TASK-160.
- Watches: the bits folder and `uploaded/` with `IN_CLOSE_WRITE | IN_MOVED_TO | IN_DELETE | IN_MOVED_FROM | IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR | IN_DONTFOLLOW` (:42). `uploaded/` is armed only while the bits folder is armed. inotify is not recursive, so subfolders are never watched. Events flagged IN_ISDIR are ignored. A name counts only if it ends in `.bit` and does not start with `.`. Everything else, including `.tmp-*` temp files, is dropped.
- Coalescing: paths go into a set. The batch is handled once there has been no relevant event for `QUIET_S = 1.0` s (:36). Unrelated events (`n.txt`) do not extend the window.
- Bounded queue: the kernel queue is bounded and an overflow (IN_Q_OVERFLOW) triggers a full reconcile. In-process, more than `MAX_PENDING = 1024` distinct paths also turn into a single full reconcile.
- No busy loop: `poll()` on the inotify fd and the wake pipe blocks with no timeout when nothing is pending and both watches are armed. Otherwise it waits until the quiet deadline or the next re-arm attempt.
- `_handle` (:186) runs under `db.session()` plus `catalog_lock(session)`:
  - For a file batch it runs the pre-check (`_changed`, :212, below). If nothing changed, it stops there. Otherwise it calls `folders.reconcile_paths(..., changed)`.
  - A full batch (overflow, lost watch, re-arm) calls `folders.reconcile` in auto mode.
  - Either way it writes one log line with counts only.
  - The watcher does no classification, folder guard or delete check of its own.
- #98 (j): any exception (for example a database outage) is logged as `folder reconcile failed: <ExceptionType>` and the batch is dropped. The next event or the next start-up reconciles again.
- Logs hold only fixed words, the folder labels `./` and `uploaded/`, exception type names and counts. They never contain file names or content.

## Self-caused events (#102 (c), as amended by the lead on 2026-10-28)

The literal #102 (c) has the manager record the path and SHA-256 of its own renames and deletions for 60 s. That needs `uploads.py` and `delete.remove_after_commit` (approved) to record, and they do not. Instead, `_changed` (:203) runs under the catalog lock and compares disk with the committed catalog:

- It reads the live `{source_file: source_sha256}` once with `catalog_integrity.integrity_rows`.
- For each pending path it takes the disk hash: None if the file is not `folders.present`, otherwise `folders.read_input(...).sha256`. This uses the no-follow folder fd and never logs for a file that is gone.
- A path counts as changed when its disk hash differs from its catalog hash (None = None counts as equal). Only the changed paths go to `reconcile_paths`. If there are none, no reconcile runs.

How the manager's own actions come out:

- Upload rename `.tmp-…` → `uploaded/policy-<id>.bit`: the policy is live with that source_file and hash, so the event is dropped. REQ-164 (4) holds: the probe shows exactly one `manual` row.
- Policy delete, leftover removal, server-wins removal of the uploaded copy: no live policy has that path and the file is gone, so the event is dropped.
- A `touch`, or a rewrite with the same bytes, is dropped too. This means no flood of `skipped` rows.

With `reconcile_paths` (r1), a real change writes rows only for the changed paths. Unchanged files get no `skipped` rows. Only a full reconcile (overflow, lost watch, re-arm) writes `skipped` rows for the unchanged files, as start-up does.

## Folder swap (Folder guard)

- When a watch is lost (IN_DELETE_SELF, IN_MOVE_SELF or IN_IGNORED, :146), `_drop` removes it and logs `folder watch lost, reconciling: <label>` once. A lost bits folder also drops `uploaded/`, which is reached through it. It then queues a full reconcile, which reports the folder unreadable and deletes nothing.
- Re-arming is tried at most every `REARM_S = 10` s. `add_watch` with IN_ONLYDIR | IN_DONTFOLLOW fails on a symlink, a file or a missing folder, and that failure is not logged again. Once it succeeds, the watcher logs `folder watched again: <label>` and runs a full reconcile to catch up on changes made while the folder was unwatched.
- A watch only triggers reconciles. If a folder is swapped between a check and `add_watch`, the cost is at most an extra reconcile, which applies the guard itself.

## REQ-164 mapping

- (1) Create, edit, remove and move each imported or deleted within about 1.05 s (probe).
- (3) Ten appends over 2 s give one `success` row and no partial `rejected` row, thanks to the 1 s quiet window.
- (4) Upload: one `manual` row and no extra `auto` row.
- (5) No inotify: one log line and `start()` returns False (shown with `sys.platform='win32'`).

## Gates (repo root, Linux container)

- `ruff check manager && ruff format --check manager`: pass.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 296 files.
- Regression: `pytest tests/test_folders_pg.py tests/test_uploads_pg.py tests/test_uploads.py` (Docker PG): 316 passed at r0 and 316 passed at r1.
- r1 probes, which counted rows for each step with one unchanged `u.bit` present:
  - one edit of `n.bit`: exactly 1 row (`n.bit auto success`), no `skipped`;
  - a `touch` or an open-and-close of `u.bit`: 0 rows;
  - moving `n.bit` to `m.bit`: 1 success row, the policy moved, no delete;
  - ten appends to `c.bit`: 1 success row;
  - an upload: 1 manual row;
  - removing `m.bit`: 0 rows, the policy deleted;
  - every step was reflected within about 1.1 s;
  - folder swaps behaved as before (re-armed full reconciles write the expected `skipped` rows).
- Throwaway probes on PG, kept in the scratchpad and not in the repo:
  - `n.bit` created: imported in 1.04 s. Edited: v2 in 1.03 s. Moved to `m.bit`: policy moved in 1.05 s. Removed: deleted in 1.04 s.
  - `n.txt`, `.n.bit` and `sub/n.bit` gave 0 rows.
  - The chunked write gave 1 success.
  - The upload gave 1 manual row only.
  - `uploaded/` swapped for a symlink: watch lost, the reconcile reports `uploaded/` unreadable, the uploaded policy is still live. After restore: re-armed.
  - Bits folder swapped for a symlink, then for a regular file: both watches lost, both folders unreadable, `a.bit` still live. After restore: re-armed, and a later removal of `a.bit` deletes it.
  - `stop()` took 5 to 16 ms.

## Cases for the tester (TP-M7-19, `manager/tests/test_watcher_linux.py`)

1. REQ-164 (1), (3) and (4) as in the probes, each within 5 s. Count `bit_import` rows exactly: one edited file gives exactly one new row, and other unchanged files get no `skipped` row. Spy on `folders.reconcile_paths`: it gets only the changed paths. `folders.reconcile` runs only after an overflow, a lost watch or a re-arm.
2. `n.txt`, `.n.bit`, `sub/n.bit`, `.tmp-1-<sha>` in `uploaded/`, and a subfolder created or moved in: no reconcile. Spy on `folders.reconcile` or count rows.
3. Self-events: an upload, `delete_policy` on an uploaded policy, a leftover removal and a server-wins move each cause no extra row or reconcile after the action. A `touch` of an unchanged file causes no reconcile.
4. Folder guard: `uploaded/` and the bits folder each replaced by a symlink, by a file, and removed. Expect one "watch lost" line per folder, nothing deleted, and a re-arm with a reconcile within about 11 s after restore. Re-arm must not follow a symlink (IN_DONTFOLLOW): with a symlinked `uploaded/`, no "watched again" line appears.
5. A database outage during a reconcile: one `folder reconcile failed: …` line, the thread keeps running, and the next event reconciles.
6. Overflow: set a tiny `fs.inotify.max_queued_events`, or patch `MAX_PENDING`, and expect one full reconcile.
7. `start()` with `sys.platform` patched (or `_libc` raising): False, exactly one log line, no thread. `stop()` after a failed start is a no-op.
8. Canary: plant a file named with a secret and secret content. No watcher log line contains either.
9. `stop()` returns within its timeout while the watcher is idle and while a reconcile waits on the catalog lock (the thread is a daemon; the descriptors stay open until it ends).
