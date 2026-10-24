# TASK-060 TEST report: inventory decoder

**Verdict: PASS** (2026-10-23, tester). REQ-074 (1) to (5), G32. Plan checks: CHK-M3-130 to -138. Code tested: `bm/services/inventory/{__init__,decode}.py` (`work/reports/TASK-060-impl.md`), as handed over; no revision.

## Tests added
- `manager/tests/test_inventory_decode.py`: 119 tests. The statuses come from the shared fixtures' manifest and the rulings.
- `manager/tests/test_inventory_fuzz.py`: 9 hypothesis properties, derandomized with a bounded budget (G32, TS §8.3 Property/fuzz).

## Commands (L)
- 128 passed in about 12 s (the bomb case takes 0.25 s). ruff, format and mypy clean.
- Plants (throwaway copies; control green), all 14 red:
  - CHK-M3-355 (whole-body decompress);
  - the G32 plant "rows checked after the packages are returned";
  - CHK-M3-356 (row limit), CHK-M3-357 (hash trusted);
  - raw cap with `ensure_ascii`;
  - raw cap off by one; decompressed cap off by one;
  - duplicates not checked;
  - NUL scan removed;
  - depth scan off;
  - trailing data accepted; truncation accepted;
  - `RecursionError` not caught;
  - NaN tokens accepted.

## Acceptance criteria
- "the TP-M3-01 inventory fixtures decode exactly": CHK-M3-130 PASS.
- "64 MiB + 1 decompressed, a gzip bomb, 50,001 rows, each over-length field, a 256 KiB + 1 `raw`, duplicates and a hash mismatch each give their #72 refusal within the read and memory bounds": CHK-M3-132 to -134 PASS.
- "random or truncated input never raises anything else": CHK-M3-135, -136 PASS.

## Notes
- **M4:** `MAX_DEPTH` (32 nesting levels in the whole body) is a decoder limit, not part of the JSON Schema. A `raw` nested 31 levels is contract-valid but refused with 400. The Go agent should keep `raw` flat (it is key/value data).
- **TASK-064:** an empty `source` reaches ingest as `""`; ingest must store NULL (#60).
- **TASK-074 (carry-over):** the route answers with `InventoryRefused.type`, never `.reason`.
