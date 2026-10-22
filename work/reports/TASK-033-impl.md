# TASK-033 IMPL report: audit disk queue

REQ: REQ-054 (1) queue part, (6). Spec: TS §5.3 L1051 (entries queue on disk while the sink is unreachable), TS §8.7 L1344 (`/var/lib/bitscan/audit-queue/`, `bitscan-manager`, 0700), L1377 (`ReadWritePaths`); #51 (c) (outage start stored in the queue folder). Plan: `work/plans/TASK-034.md`, section TASK-033. Second look recommended (lead), not on the two-approval list.

## Files (1)

- `manager/bitscan_manager/services/audit/disk_queue.py`: new. 185 non-blank lines including the module docstring, about 150 of code (estimate was 140).

## Interface (as in the plan, one deviation)

```python
class QueueError(Exception)            # folder or queue file unsafe or damaged
@dataclass(frozen=True)
class QueueState:  cursor: int; outage_since: datetime | None; alerted: bool
class DiskQueue:
    def __init__(self, folder: Path)
    def append(self, records: Sequence[Mapping[str, Any]]) -> None
    def peek(self, max_records: int) -> list[dict[str, Any]]
    def ack(self, upto_audit_id: int) -> None
    def depth(self) -> int
    def last_queued_id(self) -> int | None
    def load_state(self) -> QueueState
    def save_state(self, state: QueueState) -> None
SEGMENT_RECORDS = 10_000
```

**Deviation:** records are plain JSON objects (`Mapping[str, Any]`) that must carry an integer `audit_id`; they are not the plan's `SinkRecord` type. The reason is ordering: `SinkRecord` belongs to TASK-032 (wave 2), and TASK-033 is wave 1 with no dependencies. TASK-034's shipper converts with `dataclasses.asdict(record)` and `SinkRecord(**d)`. The queue keeps every key it is given and returns it unchanged.

## Behaviour

- **Folder.** Created with mode 0700 (parents with the default mode) if it is missing. It must be a folder. On POSIX, a folder that is group- or other-writable (`mode & 0o022`) is refused with `QueueError`, as the plan says ("refuses a folder others can write"). A 0750 folder is accepted. The install method creates it 0700 (TS §8.7).
- **Files.** Every file is created with `os.open(..., 0o600)` (plus `O_BINARY` on Windows, so `\n` is not translated):
  - `segment-<first audit_id, 20 digits>.jsonl`;
  - `acked.json` (the highest acknowledged `audit_id`);
  - `state.json` (`QueueState`).

  `acked.json` and `state.json` are written atomically: a temporary file `.<name>.tmp`, fsync, `os.replace`, then a folder fsync on POSIX.
- **Line format.** `{"crc": <zlib.crc32 of the canonical record JSON>, "record": {...}}\n`. The canonical form is `sort_keys`, compact separators and ASCII escapes, so no raw newline or U+2028 appears inside a line.
- **append.** Records go in the order given. Any record with `audit_id` at or below `max(acked, last queued id)` is skipped. This makes a re-read after a crash (between append and `save_state`) harmless, and keeps the queue strictly ordered. A record without an integer `audit_id` (bools refused) raises `ValueError`. Each record is written with one `os.write`, then the file is fsynced; the folder is fsynced when a segment file is new. Before writing, the segment is truncated to its last valid line, which removes a cut-off tail. A new segment starts after 10,000 records.
- **Read (`__init__`, `peek`).** Each segment is read up to the first line that is not newline-terminated, is not valid JSON, has the wrong shape, fails its CRC or has no integer `audit_id`. That cut-off record and everything after it in that segment is never returned. A warning names only the segment file name, never record content. `peek(n)` returns the oldest `n` records whose id is above the acked id.
- **ack(upto).** Writes `acked.json` first, then deletes leading segments whose records are all at or below it. Records stay unreturned after the queue object is recreated. A crash between those two steps is cleaned up at the next start.
- **State.** `load_state()` returns `QueueState(0, None, False)` when there is no file, and raises `QueueError` for a damaged file. It never silently resets the outage clock. `outage_since` is stored as ISO 8601 with its offset.
- **Threads and logging.** It is used by one thread (the shipper), so there are no locks. It logs nothing but the cut-off warning.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 51 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 370 passed, 181 skipped; **coverage gate FAILS at 39.70 %** because `disk_queue.py` (159 statements) has no tests yet. It turns green when TP-M2-11 (`tests/test_disk_queue.py`) lands. On Windows only the POSIX-only lines cannot be covered: the writable-folder refusal and the folder fsync body, about 6 statements |
| Scratch script in a temp folder (deleted, not a test file) | all of these behaved as expected: order kept across a recreate; overlapping appends skipped; acks persist across a recreate; a cut-off last line was dropped, earlier records returned, and the next append replaced the tail; a CRC-tampered line was dropped; with `SEGMENT_RECORDS = 3`, segments rolled over and fully acked segments were deleted; ack of everything left no segment, and an append afterwards skipped acked ids; the state round-trip worked and a damaged `state.json` raised `QueueError`; `audit_id=True` was refused; the record content (`\n`, U+2028, `é`) round-tripped |
| Linux permissions (0700 folder, 0600 files) | NOT RUN locally (Windows). TP-M2-11 runs it on Linux |

## Revision 1 (reviewer pre-review, 2026-10-21)

These changes supersede the matching lines under "Behaviour" above.

1. **Short writes (should-fix 1).** Every write now goes through `_write_all`, in both `append` and `_write_json`. It loops until all bytes are written and raises `OSError` if `os.write` returns 0. On a failed write the in-memory `segment.end` is not advanced, so the next append truncates any partial bytes. A full disk therefore raises out of `append`; the plan treats that as an outage, which is TASK-034's job.
2. **Damage is not skipped (should-fix 2).** Two rules now apply when the queue opens:
   - Only an incomplete final line (no `\n`) in the **newest** segment counts as a crash cut. It is logged with the file name only and truncated right away. Truncating at open rather than at the next append means a later segment roll-over cannot leave the cut line behind in what becomes an older segment.
   - Anything else raises `QueueError("audit queue file <name> is damaged")` and touches no file: a newline-terminated line that fails JSON, shape, CRC or the `audit_id` check, in any segment, or an incomplete tail in an older segment. The reviewer's repro (5 records, record 2 altered) now raises, and the file is byte-identical afterwards.
3. Nits, all fixed:
   - On POSIX the folder must be exactly 0700: any group or other bit (`& 0o077`) is refused.
   - `save_state` refuses a naive `outage_since` with `ValueError`.
   - `load_state` checks types exactly. The keys must be exactly `cursor`, `outage_since` and `alerted`; `cursor` must be an int (not a bool) and `alerted` a bool; `outage_since` must be `null` or an ISO string with an offset. Anything else raises `QueueError`.
   - A new segment is added to the in-memory list only after `os.open` succeeds, and `_drop_acked` uses `unlink(missing_ok=True)`.

Re-checked: ruff, ruff format and mypy `--strict` pass. A scratch script (deleted afterwards) confirmed each point:
- the reviewer's repro raises and leaves the file unchanged;
- a cut newest tail is tolerated and truncated;
- an incomplete tail in an older segment raises;
- a simulated short `os.write` still writes the whole record, and a 0-byte write raises with nothing queued;
- each malformed `state.json` variant raises, and a naive `outage_since` is refused.

The coverage gate is still red until TP-M2-11 lands. The file is now 293 statements in `services/` in total.

## Revision 2 (tester round 1, 2026-10-21)

- `peek(max_records)` now returns `[]` when `max_records <= 0`. Before this fix it added one record before checking the limit, so `peek(0)` returned one record (`test_peek_zero_returns_nothing`).
- Re-checked:
  - ruff, ruff format and mypy `--strict` pass;
  - `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` gives 535 passed, 222 skipped (pg), with coverage at 97.63 %, so the gate is green again.

## For the tester (TP-M2-11)

- Simulate a cut-off record by truncating the last segment file mid-line, or by appending a partial line without `\n`, then recreate the `DiskQueue`.
- Monkeypatch `bitscan_manager.services.audit.disk_queue.SEGMENT_RECORDS` to exercise segment rollover and deletion cheaply.
- On Linux, check the folder is 0700 and the `segment-*.jsonl`, `acked.json` and `state.json` files are 0600 under a permissive umask (for example `os.umask(0)`); the modes come from `os.open` and `mkdir`, not from the umask.
