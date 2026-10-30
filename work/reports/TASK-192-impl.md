# TASK-192 IMPL: idempotency store (pure, in memory)

Implementer: impl-manager-m9. REQ-222. Risk high. Spec: TS §6.3 L1135, §6.4 L1149, §2.1 L103. Answer applied: #123.

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/idempotency.py` (new, 143 lines) | `check_key()`, `body_digest()`, `InvalidKey`, `KeyReused`, `IdempotencyStore` |

No file outside the task's list was changed. The plans fix no interface for this task; the one below is new.

## Interface

```python
KEY_MAX: Final = 255; TTL: Final = timedelta(hours=24); MAX_ENTRIES: Final = 100_000
class Clock(Protocol): def now(self) -> datetime     # structural; runtime.Clock fits
class InvalidKey(ValueError)        # "Invalid request: Idempotency-Key"          -> 400
class KeyReused(Exception)          # "Idempotency-Key was used with a different request." -> 409
def check_key(value: str) -> str    # 1–255 chars, each 0x20–0x7E
def body_digest(body: object) -> bytes   # SHA-256 of canonical JSON
class IdempotencyStore[T]:
    def __init__(self, clock: Clock, *, ttl: timedelta = TTL, max_entries: int = MAX_ENTRIES)
    def run(self, user_id: int, key: str, body: object, call: Callable[[], T]) -> T
```

## Behaviour

- `run`:
  - It checks the key first, so `InvalidKey` comes before anything else.
  - It then takes the per-(user, key) lock. A concurrent repeat waits here.
  - Under the lock, it looks up the entry. One older than `ttl` (`now - stored_at > 24 h`) is dropped and treated as absent. If the entry exists, the same digest returns the remembered answer, and a different digest raises `KeyReused`.
  - Otherwise it calls `call()`. If `call()` raises, nothing is remembered and the exception propagates (#123 (g)).
  - If `call()` returns, the answer is stored with `clock.now()` and returned.
- **Scope:** the key is `(user_id, key)`, so another user with the same key gets their own answer.
- **The body is compared after parsing:** `json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)` and then SHA-256. Key order and spacing don't matter. `1`, `1.0` and `true` stay distinct, unlike Python `==`.
- **Only the 32-byte digest is kept, never the body.** A 10,000-agent body is about 400 KB, so 100,000 stored bodies could reach tens of GB.
- **Bounds:** entries are kept in insertion order. Each insert first drops expired entries from the oldest end, then drops the oldest until there are at most 100,000.
- **Per-key locks are reference-counted** and removed when no caller holds them, so the lock map does not grow with the keys.

## For the route (TASK-205) and the tester

- `call()` must return only after its transaction has committed (the route runs `queue_scan` inside `db.transaction()` within `call`). The answer must not be mutated afterwards; a frozen value is best.
- The store is built once per process. TASK-205's file list has no `app.py`, so the route task decides where it lives (for example in `build_user_router()`), and will ask `main` if that needs `app.py`.
- A fake clock is any object with `now()`.
- REQ-222 (2): with two threads at a barrier, `call` runs once and both get the same answer object.
- Imports: stdlib only. Importing the module loads `api/user/__init__.py`, which imports `fastapi` (the package `__init__`); the module itself imports no API code.

## Plants

- CHK-M9-367: return `entry.answer` without comparing digests. The second plant replaces the per-key lock with a no-op `contextlib.nullcontext()`, so two threads run `call` twice.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
