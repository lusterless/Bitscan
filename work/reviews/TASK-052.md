# TASK-052 REVIEW: enrolment repository

Reviewer: reviewer. Date: 2026-10-23. REQ-067, REQ-068, REQ-069. Spec: TS §5.2 L748–L777 (`enrollment_token`, `enrollment_request`) and L1007 (UPDATE grants, no DELETE), §3.2 L181–L192 (atomic `UPDATE … WHERE uses < max_uses RETURNING`, CIDR, held and decided enrolments, matches by hostname or machine-id); #26, #59 (one refusal for every `bse_` cause), #64, #68. Plan: `work/plans/TASK-067.md`. Inputs:
- `work/reports/TASK-052-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-060 to -065, `manager/tests/test_enrolment_repo_pg.py`, WSL; rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/repositories/enrolment.py` (new, 252 lines, 217 code);
- the tester's test file.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. Its consumers TASK-066, TASK-067 and TASK-070 are on it.

## What was checked

- **Spec conformance.**
  - `use_token` runs one UPDATE that checks the hash, `uses < max_uses`, `revoked_at IS NULL`, `expires_at > now` and `inet <<= ANY(allowed_cidrs)` (or NULL), and increments `uses` in the same statement. The row lock serialises concurrent uses, so 20 concurrent uses of a 5-use token give exactly 5 successes. Every refusal returns the same None with nothing changed, so no cause is revealed (#59).
  - The expiry bound is strict: accepted one second before `expires_at`, refused at it.
  - `decide` re-checks `decision IS NULL`, and with `get_request_for_update` (`FOR UPDATE`) two concurrent decisions give exactly one success (REQ-069 (5)).
  - `matches` lists every other agent with the same machine-id or hostname (TS §3.2 L192).
  - `rejected_new_for_agent` supplies the #26 and #59 `enrollment_rejected` case.
- **Security invariants.**
  - Only hashes reach this module.
  - `EnrolmentTokenRow` has no `token_hash` field, so list and read cannot show it (REQ-067 (3)). `RequestRow.new_token_hash` is kept out of `repr`.
  - No DELETE on either table (the tester probes both). Revoke keeps the row with the first `revoked_at`.
  - All SQL is parameterised or composed from constants with `psycopg.sql`; ruff S608 is clean on `repositories/`.
- **Scope.** One file, every function named in the task row. 217 code lines against a 180 estimate and the ~200 guide. Accepted: it is one cohesive repository, and splitting the token half from the request half would not make either easier to review.
- **Tests.**
  - The tests run as `bitscan_app`.
  - Races: 20 against 5 repeated five times, 10 against 1, and decisions both deterministic (A holds the lock) and 10-way.
  - Every refusal case leaves `uses` unchanged. A raw token presented in place of its hash does not match.
  - The CIDR table covers IPv4, IPv6, mixed and NULL. A host-bits CIDR is refused by the database.
  - These turn red for CHK-M3-332 to -335.
  - My run (Windows): ruff, format and `mypy --strict` are clean. The PostgreSQL cases skip locally and ran in WSL (tester).

## Findings

None.

## Carry-overs (for the consuming tasks)

- **TASK-067.** Convert an IPv4-mapped IPv6 peer (`::ffff:10.0.0.1`) to IPv4 before `use_token`. The repository deliberately does not match it against an IPv4 entry; the tester pins that, and the plan puts the conversion in the service.
- **TASK-066.** Validate `allowed_cidrs` as network addresses (no host bits) before `insert_token`, so the client gets 400 rather than a database `InvalidTextRepresentation` 500.
- **TASK-070.** Build the list and decision bodies from #68's fields only. `RequestRow` carries `new_token_hash`, which must never reach a response (REQ-063 (5)).
