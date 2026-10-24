# TASK-064 IMPL report: inventory ingestion

REQ: REQ-075. Spec: TS §3.4 L241–L243, §5.2 L780–L825, §8.1 L1257, §8.4 L1291; database rules (no UPDATE on `package`); #65 (e), #69. Plan: `work/plans/TASK-060.md`, step 5. Depends on TASK-053, 056 and 060, all approved. A second look is recommended. Carry-over applied: an empty `source` is stored as NULL (#60).

## Files (1)

- `manager/bitscan_manager/services/inventory/ingest.py`: new, 178 lines. The package `__init__` is unchanged, since it is not in the file list; import from `services.inventory.ingest`.

## API

```python
ingest(inventory, agents, audit, burst, *, agent_id, decoded: DecodedInventory, now) -> IngestResult
IngestResult(snapshot_written, added, removed, new_packages)
```

- Protocols: `InventoryStore` (TASK-053 `InventoryRepo`), `AgentStore` (`AgentRepo`), `Alerter` (`TxAudit`) and `BurstWindow` (`SlidingCount`). `mypy --strict` confirms that all four real types satisfy them.
- `AgentGone`: raised when the agent's token was revoked (or its row is missing) after the token check. Nothing is written, and TASK-074 answers 401 `token_revoked`.
- `NEW_PACKAGES_PER_DAY = 1000`.

## Behaviour (one caller transaction; commits or rolls back as a whole)

1. `agents.get(agent_id, lock=True)` locks the agent row first. This serialises two uploads from one agent and catches a revoke that happened meanwhile (plan, edge cases).
2. **Every upload:** `upsert_os_info` replaces `os_info`. Its fields come from the decoded `OsInfo`, `raw` is stored as JSONB, and `collected_at = now`, the receive time (#69). Then `set_last_inventory(now)`.
3. **The comparison:** `latest_snapshot(agent_id)`. If its `list_sha256` equals the decoded (recomputed) hash, the call stops here: no `agent_package` change and no snapshot (REQ-075 (2)).
4. **Changed list, or no snapshot yet:**
   - `insert_packages` with `source_name = source or None`, so `""` becomes NULL. This is TASK-053's `ON CONFLICT DO NOTHING` + SELECT in sorted batches, so it uses INSERT only on `package`, and two agents with one new package give one row.
   - The previous lines come from `agent_packages(agent_id)`. Then `upsert_agent_packages` (`first_seen_at` kept, `last_seen_at`, `status` and `installed_size_kb` set), and `delete_not_listed` on the new id set. `package` rows always stay.
   - **Snapshot (#69):** `added = new lines − previous lines` and `removed = previous − new`, on `(name, version, architecture, status)`, sorted, as JSON objects with those four keys. An upgrade or status change is the old line in `removed` and the new one in `added`, and the first snapshot lists every package in `added`. `package_count` is the number of uploaded packages, and `collected_at = now`.
5. **Burst alert (#65 (e)):** the number of `package` rows this upload created is added to the caller's `SlidingCount(24 h window, 24 h period, threshold 1000)` with that weight. When it fires, one `new_packages_burst` alert entry is written in the same transaction (action `alert.new_packages_burst`, actor and target `agent:<id>`, detail `{new_packages, over_per_day}`, never package names).
   - The caller (TASK-074) builds the window **once per process**, as the TASK-056 review asks.
   - The count is in memory and is added before commit, so a rolled-back upload still counts toward the window. This errs towards alerting.

Nothing here logs; no package name or `raw` value leaves the transaction except into the tables.

## Local gates (Windows)

- ruff and ruff format: pass. `mypy --strict --config-file manager/pyproject.toml manager`: `bitscan_manager` clean. The one error is in the tester's new `tests/test_agent_auth_pg.py:533` (an `arg-type` on an ASGI callable).
- `pytest -q`: 2131 passed, 722 skipped, 0 failed.
- **Scratch probe**: fake stores that behave like the tables, and real decoded inventories from `decode_inventory`.

  | Upload | Result |
  | --- | --- |
  | First upload (4 packages, multi-arch `libc6`) | one snapshot with all 4 in `added`; `os_info` and `last_inventory_at` at now; empty `source` stored as None |
  | The same list an hour later | no snapshot; `agent_package` untouched; `last_inventory_at` moved |
  | `a` upgraded 1 → 2 and `b` removed | `added = [a 2]`, `removed = [a 1, b 1]`; `first_seen_at` of the unchanged rows kept; `b`'s `agent_package` row gone and its `package` row kept |
  | 1,001 new packages | one `new_packages_burst` alert |
  | 1,001 more within 24 h | no second alert |
  | A revoked agent | `AgentGone`, nothing written |

- PostgreSQL (TP-M3-18, including the forced mid-transaction failure and the concurrent same-package case): **NOT RUN locally**; WSL.

## Design note for the lead (no change made)

The TASK-053 review notes that `latest_snapshot` has no `agent_id` index, so every upload walks the primary key backwards. One option is to compare against the hash recomputed from the agent's `agent_package` rows, which are already read when the list changes and are a primary-key prefix scan. That would differ from the spec wording ("compare with the last snapshot") in one case: after retention has deleted every snapshot of an unchanged host, no new snapshot would be written. I kept the plan's `latest_snapshot` comparison. The cost is for the M6 load test to measure.

## Deviations

None.

## Revision 1 (lead ruling 2026-10-23: the burst alert is marked only after commit)

- **Rule:** the burst window's "fired" mark is set only after the transaction commits. Counting stays immediate. A rolled-back alert therefore leaves the 24 h slot free, and the next qualifying upload alerts.
- **`services/audit/thresholds.py` (a TASK-056 file, which the ruling requires):** `SlidingCount` gains a two-phase API.
  - `count_and_check(key, weight=1, threshold=None) -> bool` counts and reports whether the alert is due, without marking.
  - `mark_fired(key)` records the alert.
  - `add()` is unchanged in behaviour: it is now `count_and_check` plus `mark_fired`, so the existing TASK-056 tests pass (`tests/test_thresholds.py`: 19 passed).
- **`services/inventory/ingest.py`:**
  - `ingest(..., burst, on_commit, *, agent_id, decoded, now)` gains a **positional `on_commit` parameter**, the transaction's after-commit registrar (`tx.on_commit`).
  - The `BurstWindow` protocol is now `count_and_check` plus `mark_fired`.
  - When the alert is due, the `new_packages_burst` entry is written in the transaction and `on_commit(lambda: burst.mark_fired(agent_id))` is registered.
- **Residual:** two uploads of one agent in flight at once could both see "due" before either commits. They are serialised by the agent row lock, though: the second waits for the first's commit, but `count_and_check` runs after the lock and the mark lands only after commit. So a second alert is possible only within that commit gap, and only for one agent's back-to-back uploads. This is accepted as erring towards alerting.
- **Probe** (fake stores; hooks run only for a commit):

  | Step | Result |
  | --- | --- |
  | upload with 1,001 new packages | alert entry written, one hook pending |
  | that hook not run (rollback) | the next qualifying upload alerted again |
  | that hook run (commit) | a third qualifying upload within 24 h wrote no alert and registered no hook |

  `add()` still fires once in 22 events.
- **Gates (Windows):** ruff, ruff format and `mypy --strict` pass for `bitscan_manager`. The protocol check against the real `SlidingCount` passes.
- **For tester-b:** the 18 cases in `tests/test_inventory_ingest.py` fail only with `TypeError: ingest() missing 1 required positional argument: 'on_commit'`. They need the new argument, for example a list's `append` as the registrar, plus a rollback case.
