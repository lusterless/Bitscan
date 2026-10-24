# TASK-060 IMPL report: inventory decoder

REQ: REQ-074. Spec: TS §3.4 L240, §6.5 L1186, §6.1 L1072, §8.1 L1250, §8.3 Property/fuzz L1276; #33, #60, #72; rulings of 2026-10-23 (NUL and lone surrogates → 400; too-deep raw → 400, never 500). Plan: `work/plans/TASK-060.md` (pipeline steps 3 and 4). It depends on TASK-048, which is approved. A second look is recommended.

## Files (2)

- `manager/bitscan_manager/services/inventory/decode.py`: new, 150 lines.
- `manager/bitscan_manager/services/inventory/__init__.py`: new, re-exports.

## API (as the plan)

- `gunzip_capped(chunks: Iterable[bytes], cap: int) -> bytes`. TASK-073 also uses it for results.
- `list_sha256(packages) -> str`.
- `decode_inventory(body: bytes) -> DecodedInventory`. The result has `os_info`, `packages` (a tuple), `list_sha256` (recomputed) and `raw_json`.
- `InventoryRefused(status, type, reason)`. `reason` is a fixed word, never input.
- Constants: `DECOMPRESSED_CAP` (64 MiB), `RAW_CAP` (256 KiB), `MAX_PACKAGES` (50,000), `MAX_DEPTH` (32).

The decoder is pure: no database and no logging. It returns a complete result or raises one refusal, never partial data.

## Steps and statuses (#72)

1. **Gunzip**, through `zlib.decompressobj(wbits=31)`, which handles one gzip member and checks its header and CRC trailer.
   - Each `decompress()` call is given at most the remaining budget, `cap + 1 − produced`. A bomb therefore stops after at most cap + 1 output bytes: **413 `too_large`** `decompressed_too_large`. The full output is never built.
   - **400 `invalid_request`** for a `zlib.error` (`bad_gzip`), a stream that does not end (`truncated_gzip`, the empty body included), or data after the member (`trailing_data`; a second member also counts as trailing).
2. **Parse:** strict UTF-8 decode, then `json.loads` with `parse_constant` refusing `NaN`, `Infinity` and `-Infinity`, which RFC 8259 does not allow. Invalid UTF-8, invalid JSON, those constants, or a `RecursionError` from extreme nesting each give **400** `bad_json`.
3. **Storable and depth pre-scan:** one iterative walk of the whole document, with no recursion.
   - A string value or key holding U+0000 gives **400** `nul_character`, and a lone surrogate gives **400** `lone_surrogate`. This is the user ruling, applied to every string, `raw` included.
   - A container nested **deeper than `MAX_DEPTH` = 32** anywhere in the body gives **400** `too_deep`. `raw` sits at depth 2, so it may nest about 29 more levels.
   - **This is the chosen path for the depth ruling.** The decoder parses the body itself and validates it in Python mode, where pydantic-core's own guard is about 98 levels inside `raw`. A fixed bound well inside that makes a too-deep body a deterministic 400, never a model 422 or a 500. Agent `raw` is flat key/value data, so 32 is generous.
4. **Count:** more than 50,000 `packages` gives **422** (`about:blank`, #59) `too_many_packages`. It is checked before model validation, so 50,001 rows are never validated.
5. **Contract model:** `InventoryBody.model_validate` (TASK-048: types, lengths, formats, INET, finite floats). Any failure gives **422** `invalid_field`.
6. **raw size:** the compact UTF-8 JSON of `raw` (separators `,` and `:`, `ensure_ascii=False`) larger than 256 KiB gives **413** `raw_too_large`. That text is returned as `raw_json`.
7. **Duplicates:** two packages with the same `(name, version, architecture)` give **422** `duplicate_package` (#72 (f)).
8. **Hash (#33):** the lines `name\tversion\tarchitecture\tstatus\n` in UTF-8, sorted by bytes, concatenated, SHA-256, lowercase hex. A mismatch with the agent's `list_sha256` gives **422** `hash_mismatch`.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (154 files).
- `pytest -q`: 2003 passed, 704 skipped, 0 failed.

**Scratch probes outside the tree:**

- **Fixtures:** every inventory request fixture (87 of them), gzipped, gave its expected outcome.
  - Valid ones decoded.
  - The four `decoder`-marked ones gave their manifest status: hash mismatch 422, duplicate 422, `raw` of 256 KiB + 1 gave 413, 50,001 packages 422.
  - Every invalid one was refused.
- **Bounds:**
  - exactly 64 MiB decompressed is accepted; 64 MiB + 1 gives 413;
  - a gzip bomb (1.0 MiB compressed, 1 GiB of zeros) gives 413 in 0.25 s, with a peak Python heap of 129 MiB (REQ-074 (1): under 256 MiB).
- **Malformed input:** truncated, trailing byte, two members, plain JSON (not gzip), empty, invalid UTF-8, a `NaN` token, 100,000 nested arrays, and `raw` nested 40 deep all gave 400. A JSON array as the body gave 422.
- **Fuzz:** 12,007 attempts (bit-flipped JSON, bit-flipped and truncated gzip, random bytes, odd documents). No exception other than `InventoryRefused` escaped.

## For the tester

- Peak memory for a valid 64 MiB body is higher than in the bomb case (the decompressed bytes, the str and the parsed objects). The plan applies the 256 MiB bound to the bomb only.
- `1e400` parses as infinity and is refused by the model as 422 `invalid_field`, because it is valid JSON. The `NaN` and `Infinity` tokens are invalid JSON and get 400.
- A body nested 33 or more containers deep gets 400 `too_deep` before the model runs. The model's own deeper limit is therefore never reached through the decoder.

## Deviations

None from the plan's interface or statuses. The `MAX_DEPTH` value of 32 is my choice under the lead's depth ruling, stated above.

## Note on problem types (lead query of 2026-10-23; no code change)

`InventoryRefused` has a **`type`**, which is the problem `type` the route answers with. It also has a separate **`reason`**, a fixed internal word for the audit detail and tests (`too_deep`, `bad_json`, `hash_mismatch` and so on), which is never a problem `type`.

The type comes only from the status: 413 → `too_large`, 422 → `about:blank`, and 400 → `invalid_request`. A too-deep body is therefore already **400 `invalid_request`** (reason `too_deep`). A probe over a too-deep `raw`, 100,000 nested arrays, a non-gzip body, an empty document and a 64 MiB + 1 bomb gave types `invalid_request`, `invalid_request`, `invalid_request`, `about:blank` and `too_large`. All of them are inside `AGENT_PROBLEM_TYPES | AGENT_GENERIC_PROBLEM_TYPES`. TASK-074 must put `exc.type` into the problem body, never `exc.reason`.
