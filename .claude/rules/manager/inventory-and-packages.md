---
paths:
  - "manager/**/services/inventory/**"
  - "manager/**/services/packages/**"
---

# Inventory ingestion and package search

Spec: TS §3.4 (mandatory inventory), §6.5 (inventory body), §7 (search), §6.3 (CSV). Tables: `os_info`, `package`, `agent_package`, `inventory_snapshot` (TS §5.2). Inventory can never be disabled (G2).

## Upload (`PUT /agent/{id}/inventory[?job_id=…]`)

- Limits, checked by the manager whatever the agent claims: gzip body ≤ 10 MB, decompressed as a stream with a hard cap of 64 MB, ≤ 50,000 package rows, every field length-checked against its column, `os_info.raw` ≤ 256 KB. Anything over a limit is rejected (413 or 422) and audit-logged; if it carried a `job_id`, that inventory job becomes `failed`.
- Accept at most one upload without `job_id` per agent per 10 minutes; answer 429 otherwise.
- With a valid `job_id` the upload completes that job (204). A later upload carrying a `job_id` whose job already failed is still stored, as an unscheduled snapshot.
- **Open spec question:** TS §3.4 does not say whether such a late `job_id` upload counts against the one-unscheduled-upload-per-10-minutes limit.
- Every upload replaces `os_info` and sets `agent.last_inventory_at`. Recompute `list_sha256` (hex SHA-256 of the sorted UTF-8 lines `name\tversion\tarchitecture\tstatus\n`, same as the agent). If it differs from the last snapshot: upsert `agent_package`, delete rows for packages no longer listed, and write an `inventory_snapshot` with what was added and removed.
- `package` rows are shared: insert with `INSERT … ON CONFLICT DO NOTHING` then SELECT (the app has no UPDATE on `package`). Unreferenced rows are pruned by the retention task.
- Alert when one agent adds more than 1,000 previously unseen packages in a day.

## Package search (`GET /packages/search`, `/packages/search.csv`, viewer)

- Target: under 1 s for 10,000 hosts × 2,000 packages (20 M `agent_package` rows), using `ix_package_name_trgm` and normalised `package` rows.
- Parameters (TS §7.1): `q` substring/fuzzy match via `pg_trgm`, at least 3 characters; `name`, `version`, `arch`, `os` (for example `ubuntu:24.04`), `tag`, `host` (hostname substring), `agent_id`.
- `version_op` (`lt`, `le`, `eq`, `ge`, `gt`) compares with `version` in Debian order: cast `version::debversion` and use `ix_package_name_debver`. Never compare Debian versions as text.
- `status`: `installed` (default) keeps only `install ok installed`; `any` also shows removed packages whose config files remain.
- Filters combine with AND. `q` with `name`, or `version_op` without `version`, returns 400.
- `group_by=package` (hosts per version) or `group_by=host` (packages per host), at most 500 groups per page. Row shapes are TS §7.1; every response is `{items, next_cursor}`.
- CSV export of the current result set escapes formula cells as in TS §6.3 (prefix `'`).
- The < 1 s search target (TS §7) has no TS §8.3 gate: see the open question in `.claude/rules/testing.md` before adding a CI performance gate.

Tests (TS §8.3): Property/fuzz (inventory decoder with oversized and malformed input, including gzip bombs: no crash, no partial import), Unit (version compare against `dpkg --compare-versions`, ≥ 500 pairs; CSV escaping), Integration (every limit, 429, snapshot diff).
