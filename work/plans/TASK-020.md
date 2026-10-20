# TASK-020 plan: audit chain core (append, TASK-020; verifier, TASK-021)

REQs: REQ-030 (TASK-020), REQ-031 (TASK-021). Owner: impl-manager. Depends on: TASK-018 (table and grants).

Files:
- TASK-020: `services/audit/__init__.py`, `services/audit/chain.py`, `repositories/__init__.py`, `repositories/audit_log.py`.
- TASK-021: `services/audit/verify.py`, `repositories/audit_log.py`.

Tests: TP-M1-14, TP-M1-15. **Blocked on #38** (hash input and genesis) and, for the checkpoint part of TASK-021, **#39**. Nothing below decides those questions. Where a value is needed, it is marked "suggested (#38)" and must not be implemented until the owner answers.

## Spec quotes

- TS §5.2 L981–L990: `audit_log (audit_id BIGSERIAL PRIMARY KEY, actor VARCHAR(128) NOT NULL, action VARCHAR(64) NOT NULL, target VARCHAR(255), detail JSONB, at TIMESTAMPTZ NOT NULL DEFAULT now(), prev_hash CHAR(64) NOT NULL -- row_hash of the previous entry, row_hash CHAR(64) NOT NULL -- SHA-256 of prev_hash and this entry)`.
- TS §5.3 L1051: "before deleting expired entries, the retention task writes an `audit.checkpoint` entry recording the id and `row_hash` of the last deleted entry, so the chain can still be verified from that point. Each entry stores the previous entry's hash, and every insert takes `pg_advisory_xact_lock(hashtext('audit_log'))` so concurrent writers cannot fork the chain. Entries are also streamed to an external log store …" (the sink is M2).
- TS §5.2 L1003–L1004: `bitscan_retention` may INSERT into `audit_log` and use `audit_log_audit_id_seq`.

**What the spec does not say (#38):** which fields "this entry" means (is `audit_id` in it? `at`?), how they are serialised and separated, the JSON canonical form of `detail`, the timestamp text form, the hex case, and what `prev_hash` the first entry gets. **#39:** the `detail` keys of `audit.checkpoint`, and the exact rule for verifying from it.

## Layering (keeps the coverage gate green on Windows)

`services/` is under the 85 % coverage gate, and the PostgreSQL tests do not run on the Windows dev box. So:
- `services/audit/chain.py` holds the **pure** hash function and an `append_entry()` that talks to the database only through a small repository protocol. Unit tests drive it with a fake repository.
- `repositories/audit_log.py` holds the SQL: the lock, reading the head, allocating the id, the insert and the ordered read. It sits outside the coverage source and is tested on PostgreSQL.
- `services/audit/verify.py` is pure over a sequence of stored rows; only its thin `verify_chain(conn)` reads through the repository.

## Interface

```python
# services/audit/chain.py
GENESIS_PREV_HASH: str            # suggested (#38): "0" * 64

@dataclass(frozen=True)
class HashInput:
    audit_id: int                 # in the hash only if #38 says so
    actor: str
    action: str
    target: str | None
    detail_text: str | None       # PostgreSQL's text form of the stored jsonb value (see below)
    at_text: str                  # UTC text form of the stored timestamptz (see below)

def compute_row_hash(prev_hash: str, entry: HashInput) -> str: ...   # pure, lowercase hex (#38)

class AuditRepo(Protocol):
    def lock_chain(self) -> None: ...
    def head_row_hash(self) -> str | None: ...
    def allocate(self, detail_json: str | None) -> tuple[int, str, str | None]: ...   # (audit_id, at_text, detail_text)
    def insert(self, audit_id: int, actor: str, action: str, target: str | None,
               detail_text: str | None, at_text: str, prev_hash: str, row_hash: str) -> None: ...

@dataclass(frozen=True)
class AppendedEntry:
    audit_id: int
    prev_hash: str
    row_hash: str
    at_text: str

def append_entry(repo: AuditRepo, *, actor: str, action: str,
                 target: str | None = None, detail: Mapping[str, object] | None = None) -> AppendedEntry: ...

# repositories/audit_log.py
class PgAuditRepo:                # implements AuditRepo over one psycopg connection
    def __init__(self, conn: psycopg.Connection[Any]) -> None: ...
def iter_entries(conn: psycopg.Connection[Any]) -> Iterator[StoredEntry]: ...   # TASK-021

# services/audit/verify.py (TASK-021)
@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_bad_id: int | None
    reason: str | None

def verify_rows(rows: Iterable[StoredEntry]) -> VerifyResult: ...   # pure
def verify_chain(conn: psycopg.Connection[Any]) -> VerifyResult: ...
```

`AppendedEntry` is returned so M2's sink can stream the entry after commit without reading it back.

## Append flow (all inside the caller's transaction)

1. **Preconditions:** the connection is not in autocommit, and its isolation level is READ COMMITTED. Otherwise raise before any statement (REQ-030 (5)). Why:
   - in autocommit, the transaction-scoped advisory lock is released at the end of each statement;
   - in REPEATABLE READ or SERIALIZABLE, the snapshot is taken at the first statement, which is the lock call, so a writer that waited for the lock would not see the entry it waited for, and would fork the chain.
2. `SELECT pg_advisory_xact_lock(hashtext('audit_log'))`.
3. `SELECT row_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1`. None means use `GENESIS_PREV_HASH` (#38).
4. `allocate`: `SELECT nextval('audit_log_audit_id_seq'), <UTC text of now()>, CAST(%s AS jsonb)::text`. One statement, with `detail` passed as a bound JSON string. This gives the id (allocated under the lock, so `audit_id` order is chain order), the exact stored timestamp text, and **PostgreSQL's canonical text of the jsonb value**. jsonb reorders keys, removes duplicate keys and normalises numbers (`1e2` is stored as `100`). Hashing the database's own text form means the verifier can recompute the hash from `detail::text` byte for byte, and no Python JSON canonicalisation has to match PostgreSQL's.
5. `row_hash = compute_row_hash(prev_hash, HashInput(...))`.
6. `INSERT INTO audit_log (audit_id, actor, action, target, detail, at, prev_hash, row_hash) VALUES (%s, %s, %s, %s, CAST(%s AS jsonb), CAST(%s AS timestamptz), %s, %s)`, all bound. Casting the canonical text back to jsonb gives the same value, and so the same text.
7. Nothing is logged. There is no network.

A suggested timestamp form (#38): `to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`. It is used in `allocate` and in the verifier's read, so both sides use the same server-side formatting.

A suggested hash input (#38, **not decided**): SHA-256 over the UTF-8 bytes of the JSON array `[prev_hash, audit_id, actor, action, target, detail_text, at_text]`. It is serialised with `json.dumps(…, ensure_ascii=False, separators=(",", ":"))`, where `detail_text` is a JSON string or null (never re-parsed), and the digest is lowercase hex. A JSON array removes separator ambiguity, and including `audit_id` binds each entry to its position. One alternative the owner may prefer: compute the hash in SQL with `pgcrypto`'s `digest()`. TS §5.2 installs `pgcrypto` although `gen_random_uuid()` has been core since PostgreSQL 13, which hints at this use. The spec does not say so.

## Verifier (TASK-021)

- Read in one `REPEATABLE READ READ ONLY` transaction, ordered by `audit_id`, with `detail::text` and the same UTC `at` text as in `allocate`.
- For each row: recompute `row_hash`; check `prev_hash` equals the previous row's `row_hash`; report the first failure with its `audit_id` and a reason (`row_hash mismatch` or `broken link`).
- First row: `prev_hash` must be `GENESIS_PREV_HASH`. Or, suggested (#39), a later `audit.checkpoint` row must record `last_deleted_id < first.audit_id` and `last_deleted_row_hash == first.prev_hash`. The suggested `detail` keys are `last_deleted_id` and `last_deleted_row_hash`; the spec says only "the id and `row_hash` of the last deleted entry".
- Gaps in `audit_id` are allowed (rolled-back appends use up sequence values); only the hash links count.
- An empty log is `ok`, with `checked = 0`.

## Edge cases

- `target` NULL and `detail` NULL must hash differently from the empty string or `{}`. A JSON `null` in the array does that.
- `actor`, `action` and `target` longer than the column limits: the INSERT fails with 22001, and the caller's transaction is aborted. REQ-030 (6) only needs "nothing inserted".
- Non-ASCII text in `actor` or `detail`: UTF-8 everywhere, with `ensure_ascii=False`, so the hash covers the real characters.
- The lock is held until the caller commits, so every audited transaction is serialised on that key. That is intended (TS §5.3). Keep audited transactions short.
- `bitscan_retention` uses the same `append_entry` for checkpoints. It has SELECT, INSERT and sequence USAGE (L999, L1003, L1004), and needs nothing else.
- No function here takes UPDATE or DELETE paths. Tamper tests (REQ-031 (2), (3)) run as `bitscan_owner` through `bitscan_migrate`, never as a superuser (testing.md).

## Not in this task

The sink, disk queue, outage alert and 15-minute refusal (M2); `detail.alert = true` alerts and `bitscan_alerts_total` (M2); writing checkpoints during retention (M11); any CLI or API route that exposes the verifier (none is in the spec).
