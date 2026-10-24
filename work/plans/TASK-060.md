# TASK-060 plan: inventory pipeline (decode, ingest, upload route)

Covers TASK-060 (decoder), TASK-064 (ingestion) and TASK-074 (route). REQs: REQ-074, REQ-075, REQ-076, REQ-066. Owner: impl-manager. **Two approvals for TASK-074** (agent route); second look recommended for TASK-060 and TASK-064. Tests: TP-M3-14 (G32), TP-M3-18, TP-M3-28; mutation rows CHK-M3-355 to 358, 360, 361.

**Blocked on #33** (recompute and sort order), **#60** (field limits), **#69** (snapshot shape, `collected_at`), **#72** (413 or 422, `job_id` cases, the 10-minute count), **#65 (e)** (new-package alert).

## Spec quotes

- TS §3.4 L239: "it accepts at most one upload without `job_id` per agent per 10 minutes and answers 429 otherwise."
- L240: "Upload limits: gzip body ≤ 10 MB, decompressed as a stream with a hard cap of 64 MB, ≤ 50,000 package rows, every field length-checked against its column, `os_info.raw` ≤ 256 KB. Anything over a limit is rejected (413 or 422) and audit-logged."
- L241: "On every upload the manager replaces `os_info` and sets `agent.last_inventory_at`. If `list_sha256` differs from the last snapshot it also upserts `agent_package` rows, deletes rows for packages no longer listed, and writes an `inventory_snapshot` with what was added and removed."
- L244: "An inventory job that is dispatched but not uploaded within 30 minutes, or whose upload is rejected (413 or 422), becomes `failed`. A later upload carrying that `job_id` is still stored, as an unscheduled snapshot."
- TS §6.5 L1186: `list_sha256` = "hex SHA-256 of the UTF-8 lines name\tversion\tarchitecture\tstatus\n, sorted".
- TS §8.3 L1276: "inventory decoder with oversized and malformed input … No crash, no partial import."

## Pipeline

```
route (TASK-074)                         service upload.py (TASK-074)          decode.py (TASK-060)        ingest.py (TASK-064)
current_agent ──▶ read_capped(10 MiB) ──▶ job_id rules, 10-min window ──▶ gunzip_capped(64 MiB) ─▶ parse ─▶ validate ─▶ one transaction
```

1. **Route:** `current_agent` (TASK-063), then `job_id` query parameter (UUID or 400), then `Content-Encoding` must be `gzip` (#72 (a), else 400), then `read_capped` (TASK-049 after-auth mode; over 10 MiB → refusal path).
2. **Service, before decoding:** classify `job_id` (#72 (d)): `dispatched` inventory job of this agent → "completes"; `failed` or `completed` → "unscheduled"; anything else → 409 `job_not_acceptable` plus audit entry, stop. For "unscheduled" (no `job_id` too): ask `limits.allow_unscheduled_inventory(agent_id)`; refused → 429 with `Retry-After`, nothing decoded (#72 (e): every unscheduled attempt that reaches decoding counts).
3. **Decode (pure, no database):** `gunzip_capped(chunks, 64 MiB)` uses `zlib.decompressobj(wbits=31)` and feeds at most the remaining budget per call (`max_length`), so a bomb stops at cap + 1 bytes without building the output; trailing garbage after the gzip member and a truncated stream are refusals. Then `json.loads` on the bytes (UTF-8 strict; invalid UTF-8 or JSON → 400 per #72 (c)), then the `InventoryBody` model (TASK-048) for types and lengths (→ 422), then: `len(packages) <= 50,000` (→ 422), compact `raw` serialisation ≤ 256 KiB (→ 413), no duplicate `(name, version, architecture)` (→ 422), and the recomputed hash equals `list_sha256` (→ 422, #33).
4. **Hash (#33):** lines `f"{name}\t{version}\t{architecture}\t{status}\n"` encoded UTF-8, sorted by bytes, concatenated, SHA-256, lowercase hex. The test computes it independently from the spec text.
5. **Ingest (one transaction):** upsert `os_info` (`collected_at` = receive time, #69), set `agent.last_inventory_at`; read the latest snapshot's `list_sha256`; if different or none: `package` insert in batches of 1,000 with `INSERT … ON CONFLICT (name, version, architecture) DO NOTHING RETURNING package_id`, then `SELECT` the ids of the batch (the app has no UPDATE on `package`, database rules); `agent_package` upsert (`first_seen_at` kept, `last_seen_at`, `status`, `installed_size_kb` set); delete the agent's rows whose `package_id` is not in the new set; compute `added` and `removed` on the four hash fields against the previous `agent_package` rows (#69); insert the snapshot. The count of `package` rows this upload created feeds the #65 (e) window.
6. **Job:** "completes" → the job becomes `completed`, `finished_at = now`, in the same transaction as the ingest. A refusal (413 or 422) with a "completes" job → the job becomes `failed`, `finished_at = now`, plus one `agent.inventory_refused` audit entry (#71), in its own transaction; a 400 is audit-logged and leaves the job to the 30-minute sweep (#72 (c)).
7. **Answer:** 204 with no body.

## Interface

```python
# bm/services/inventory/decode.py
class InventoryRefused(Exception): status: int; type: str; reason: str   # reason is a fixed word, never input
def gunzip_capped(chunks: Iterable[bytes], cap: int) -> bytes: ...
def list_sha256(packages: Sequence[PackageItem]) -> str: ...
@dataclass(frozen=True)
class DecodedInventory: os_info: OsInfo; packages: tuple[PackageItem, ...]; list_sha256: str; raw_json: str
def decode_inventory(body: bytes) -> DecodedInventory: ...               # gunzip + parse + validate

# bm/services/inventory/ingest.py
@dataclass(frozen=True)
class IngestResult: snapshot_written: bool; added: int; removed: int; new_packages: int
def ingest(repo: InventoryRepoP, agents: AgentRepoP, agent_id: UUID, inv: DecodedInventory, now: datetime) -> IngestResult: ...

# bm/services/inventory/upload.py
def handle_upload(runtime: Runtime, caller: AgentCaller, job_id: UUID | None, body: bytes, now: datetime) -> None: ...
```

## Memory and time bounds (for TP-M3-14)

The raw body is held once (≤ 10 MiB) and the decompressed bytes once (≤ 64 MiB); JSON parsing of 64 MiB in CPython can take several hundred MiB, so the decoder refuses a decompressed body above 64 MiB before parsing and the test's peak-memory bound (REQ-074 (1), 256 MiB) applies to the bomb case, which never reaches the parser. A 50,000-row valid upload should ingest within a few seconds on the CI runner; the tester records the time, no gate is set (testing.md performance-gate question).

## Edge cases

- `source` empty → NULL (#60). `source_name` is not part of the `package` key, so the first writer's value is kept (no UPDATE grant); recorded as a known effect for #72's reviewer.
- Multi-arch packages (`libc6:amd64` and `libc6:i386`) are distinct rows (different `architecture`).
- An agent that is decommissioned between the token check and the ingest: the transaction locks the agent row first and refuses with 401 `token_revoked` if it was revoked meanwhile.
- `raw` is stored as JSONB; PostgreSQL may reorder keys. The 256 KiB limit is measured on the compact UTF-8 JSON the decoder produced, before storage.
- No package name, version or `raw` content is ever logged (REQ-087); refusal reasons are fixed words such as `too_many_packages`, `field_too_long`, `hash_mismatch`.
