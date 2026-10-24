# TASK-053 IMPL report: inventory repository

REQ: REQ-075, REQ-081. Spec: TS §5.2 L780–L825 (`os_info`, `package`, `agent_package`, `inventory_snapshot`) and L994–L1013 (grants), §3.4 L241–L243; database rules ("Never weaken these grants"); #68, #69. Plan: `work/plans/TASK-060.md` (ingest, step 5).

## Files (1)

- `manager/bitscan_manager/repositories/inventory.py`: new, 252 lines (222 code). Over the 190 estimate; a ruling was asked of the lead.

## Rows

- `OsInfoRow`: the ten `os_info` value columns plus `collected_at`. `ip_addresses` is read back in its stored order through `abbrev()`, so `10.0.0.1` reads as written, not as `10.0.0.1/32`.
- `PackageRow(name, version, architecture, source_name)`.
- `AgentPackageRow`: `package_id`, the four hash fields, `source_name`, `installed_size_kb`, `first_seen_at`, `last_seen_at`.
- `SnapshotRow`.
- `PackageIds(ids: {(name, version, architecture): package_id}, new: frozenset of keys inserted by this call)`.

## Functions (`InventoryRepo(conn)`, inside the caller's transaction)

**os_info:**
- `upsert_os_info(agent_id, row)`: `INSERT … ON CONFLICT (agent_id) DO UPDATE` sets every column. `raw` is written as JSONB and `ip_addresses` cast to `inet[]`.
- `get_os_info(agent_id)`: for the TASK-076 detail.

**package:**
- `insert_packages(rows) -> PackageIds`: in batches of `BATCH` = 1,000.
  - First `INSERT … SELECT FROM unnest(…) ON CONFLICT (name, version, architecture) DO NOTHING RETURNING name, version, architecture`; its returned rows are the "new" keys.
  - Then a `SELECT … JOIN unnest(…)` for every key's id.
  - Only INSERT and SELECT are used: the app has **no UPDATE on `package`**.
  - Keys are written in sorted order, so concurrent uploads of overlapping packages wait on each other in one order and cannot deadlock.
  - A concurrent insert of the same new key gives one row: the later statement waits for the first commit, does nothing, and its SELECT then sees the committed row.
  - `source_name` comes from the first writer only (plan, edge cases). The service maps an empty `source` to None.

**agent_package:**
- `agent_packages(agent_id)`: all of the agent's rows. Ingest uses them as the previous lines for the #69 added and removed diff.
- `upsert_agent_packages(agent_id, rows: [(package_id, status, installed_size_kb)], now)`: batched `INSERT … ON CONFLICT (agent_id, package_id) DO UPDATE` of `status`, `installed_size_kb` and `last_seen_at`. **`first_seen_at` is kept**.
- `delete_not_listed(agent_id, keep_ids) -> int`: `… AND package_id NOT IN (SELECT unnest(…))`. That is a hashed subplan rather than `<> ALL (array)`, which would be quadratic at 50,000 rows. It removes exactly the agent's rows that are not listed; `package` rows stay (retention prunes them, M11).

**inventory_snapshot:**
- `insert_snapshot(agent_id, list_sha256, package_count, added, removed, collected_at) -> snapshot_id`, with `added` and `removed` as JSONB arrays (#69 items).
- `latest_snapshot(agent_id)`: the newest by `snapshot_id`, which is insertion order and independent of any clock. The table has no `agent_id` index and none may be added, so the query walks the primary key backwards and filters. This is cheap while agents upload regularly; noted for the load test (M6).

**Package page (#68):**
- `package_page(agent_id, limit, after: (name, architecture, version) | None)`: ordered by `name, architecture, version`, keyset paging, with `limit=None` reading all rows.

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass. `mypy --strict`: pass for `bitscan_manager`.
- `pytest -q`: 1198 passed, 451 skipped (the 2 expected TASK-056 failures aside).
- PostgreSQL: **NOT RUN locally** (Docker unavailable); the SQL has been reviewed but never executed. TP-M3-07 in WSL is the first run, including the 50,000-row batch and the INSERT-only grant.

## Deviations

None.

## Revision 1 (reviewer CHANGES_REQUESTED, finding 1)

- **Finding:** `package_page` ordered and paged on `p.version` as text. That breaks database.md ("Never compare Debian versions as text") and TS §7.2 L1219.
- **Fix:** `inventory.py` `package_page` only.
  - It now orders by `p.name, p.architecture, p.version::debversion, p.version`.
  - The keyset uses the same four-part tuple: `(p.name, p.architecture, p.version::debversion, p.version) > (name, arch, CAST(version AS debversion), version)`. The previous row's version is passed twice.
  - The text tie-break keeps the key total, because two different version strings can be equal in Debian order (for example `1.0` and `1.00`). The `after` tuple is unchanged: `(name, architecture, version)`.
- **Gates (Windows):** ruff, ruff format and `mypy --strict` pass (143 files). The PostgreSQL run is the tester's.
- **For the tester:**
  - Page across versions whose text order differs from Debian order, for example `1.10` against `1.9`, and `1.0~rc1` against `1.0`.
  - Include two versions that are equal in Debian order (`1.0`, `1.00`): each row must come back once.
- **Note for TASK-060 (reviewer):** an odd version string must not make the `::debversion` cast fail. The decoder should refuse such versions, or the cast's behaviour on them should be checked.
