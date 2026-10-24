# TASK-060 REVIEW: inventory decoder

Reviewer: reviewer. Date: 2026-10-23. REQ-074. Spec: TS §3.4 L240 (gzip ≤ 10 MB, streamed decompression with a 64 MB hard cap, ≤ 50,000 rows, field lengths, `raw` ≤ 256 KB, 413 or 422), §6.5 L1186 (body, `list_sha256`), §6.1 L1072 (the manager re-checks every cap), §8.1 L1250 (streaming decompression with hard caps), §8.3 L1276 (property and fuzz tests, gzip bombs, no partial import); #33 (recompute; sorted by bytes; mismatch 422), #60, #72 (b), (c), (f). Rulings (`work/decisions.md`, 2026-10-23): NUL and lone surrogates answer 400; a too-deep `raw` answers 400, never 500. Plan: `work/plans/TASK-060.md` (pipeline steps 3 and 4). Inputs:
- `work/reports/TASK-060-impl.md`, with the note on problem types;
- `work/reports/TASK-060-test.md` (PASS: CHK-M3-130 to -138, G32; 128 tests; 14 of 14 plants red).

Files reviewed:
- `manager/bitscan_manager/services/inventory/decode.py` (new, 150 lines);
- `manager/bitscan_manager/services/inventory/__init__.py` (re-exports);
- the tester's `test_inventory_decode.py` and `test_inventory_fuzz.py`.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. The M3 owner notes recommend a second look (TS §8.1 decompression bombs).

## What was checked

- **Bounds (REQ-074 (1)).** `gunzip_capped` uses `zlib.decompressobj(wbits=31)` and gives each `decompress()` call at most `cap + 1 − produced` bytes. As soon as the output passes the cap it refuses with 413 `too_large`. A bomb therefore never builds more than 64 MiB + 1 bytes: the tester measured 0.25 s and a 129 MiB peak for 1 MiB expanding to 1 GiB, under the 256 MiB bound. The output limit binds only at cap + 1, so a body under the cap is never cut short. Truncated streams, trailing data (a second member included), corrupt data and an empty body each get 400.
- **Statuses (#72, rulings).**
  - 400 `invalid_request`: invalid UTF-8; invalid JSON, including the `NaN` and `Infinity` tokens, refused through `parse_constant`; `RecursionError`; U+0000 or a lone surrogate in any key or string; nesting deeper than `MAX_DEPTH`.
  - 422 `about:blank`: more than 50,000 packages, checked before the model so 50,001 rows are never validated; any contract-model failure (`1e400` → inf included); duplicate `(name, version, architecture)`; a `list_sha256` mismatch.
  - 413 `too_large`: the decompressed cap, and a compact UTF-8 `raw` above 256 KiB.
  - The problem `type` follows only from the status, and every value is in the agent sets. `reason` is a fixed word, never input.
- **Hash (#33).** Lines `name\tversion\tarchitecture\tstatus\n`, UTF-8, sorted by bytes, concatenated, SHA-256, lowercase hex. The agent's value is compared, never trusted (CHK-M3-357 red). The tester computes it independently from the spec text.
- **Security invariants.** The decoder is pure: no database, no logging, no package name or `raw` content in any exception. It returns a complete `DecodedInventory` or raises one refusal, never partial data. No stdlib `re` is used.
- **Scope.** Two files, as the task row lists.
- **Tests (my run, Windows).** 128 passed in 14 s. ruff and format are clean, and `mypy --strict` is clean (161 files). The fuzz suite runs nine hypothesis properties under a bounded, derandomised budget: random bytes, bit-flipped and truncated gzip, random JSON, deep nesting, invalid UTF-8. Nothing but `InventoryRefused` escapes. Plants red include whole-body decompression (CHK-M3-355), the row limit (CHK-M3-356), each cap off by one, and the NUL and depth scans removed.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/inventory/decode.py:77`. `bytes(out)` copies up to 64 MiB, and `decode_inventory` then decodes that copy, so the peak for a valid 64 MiB body holds the bytes twice before the `str` and the parsed objects exist. Optional fix: return the `bytearray` (or a `memoryview`) and decode it directly, since `bytearray.decode("utf-8")` works. That saves 64 MiB of peak memory per large upload.

## Notes and carry-overs

- **M4 (Go agent).** `MAX_DEPTH` = 32 nesting levels over the whole body is a decoder limit, not part of the JSON Schema. A `raw` nested about 30 levels is contract-valid but refused with 400. The agent should keep `raw` flat key/value data. Record this in the M4 contract notes and in the README agent-API section (TASK-080).
- **TASK-074.**
  - Answer with `InventoryRefused.status` and `.type`; `.reason` may go into the audit detail only.
  - A 413 or 422 that names a `dispatched` job fails it, and a 400 leaves the job to the sweep (#72 (c)).
  - Ask the 10-minute window before calling the decoder.
- **TASK-064.** An empty `source` reaches ingest as `""` and must be stored as NULL (#60).
- **Memory (M6).** A valid 64 MiB body costs several hundred MiB while it is parsed (bytes, `str` and objects). The plan accepts this, and the bound applies to the bomb case only. With one manager instance, concurrent large uploads multiply it; worth a line in the M6 load test notes.
