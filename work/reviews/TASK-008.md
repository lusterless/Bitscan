# TASK-008 REVIEW: manager systemd units, verbatim from TS §8.7

Reviewer: reviewer. Date: 2026-10-20. REQ-016, REQ-008. Inputs: `work/reports/TASK-008-impl.md`, `work/reports/TASK-008-test.md`, `tests/m0/report.md` CHK-M0-121 to -125.

Verdict: APPROVED

TS §8.2 L1268 asks for one approval here: manager units are not importer, auth, agent or runner code. This approval completes the review.

## What was checked

1. **Spec conformance.** Re-ran `python -I deploy/tests/check_units_verbatim.py manager` and `all`: exit 0, 4 and 9 units identical. Independent check: an awk extraction of every ```` ```ini ```` block in the TS (exactly 9 exist) plus `cmp`. Each manager file matches exactly one block: L1352-1401, 1405-1435, 1439-1467 and 1469-1480. All four files are ASCII, end in a single LF, and have no CR and no trailing whitespace. REQ-016 (1) and (2) are met. (4) and (5) are NOT RUN locally (no systemd) and carried to TASK-010 CI. That CI run also needs `/usr/bin/bitscan-manager` from TASK-002 (REQ-008). `ExecStart=/usr/bin/bitscan-manager ...` is copied as written, so it does not decide Open spec question #6.
2. **Security invariants (packaging-and-units.md, TS §8.7).** All four files are byte-identical to the spec, so no directive is added, weakened or reworded.
   - `bitscan-manager.service`: `User=`/`Group=bitscan-manager`, `NoNewPrivileges=yes`, empty `CapabilityBoundingSet=`, `ProtectSystem=strict`, `ReadWritePaths=` limited to `uploaded` and `audit-queue`, and `ExecReload=/bin/kill -HUP $MAINPID`. It loads `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key` and `vault_token`, and never `migrate_dsn`.
   - `migrate_dsn` is loaded only by the migrate and maintain units, both `DynamicUser=yes`.
   - The migrate unit has `Before=bitscan-manager.service`.
   - The timer has `OnCalendar=daily` and `Persistent=true`.
   - No file has an end-of-line comment, and secrets come only through `LoadCredential=`.
3. **Scope.** The task adds exactly the 4 listed files under `deploy/systemd/` (114 lines, all spec text), with no other changes.
4. **Tests.** In my own temp copy, a missing timer in `manager` mode made the script exit 1 (`MISSING`), and the unmodified control exits 0. The tester's plants (`OnCalendar=hourly`, an extra final newline, a missing final newline) each fail as reported. See the TASK-007 review for the shared script's other plants.

## Findings

1. nit (shared with TASK-007 finding 2, carry to TASK-010). CI should run `python deploy/tests/check_units_verbatim.py all` next to `systemd-analyze verify`, so that later edits that drift from the spec are caught.
