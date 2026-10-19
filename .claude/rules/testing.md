---
paths:
  - "manager/tests/**"
  - "**/*_test.go"
  - "agent/test/**"
  - "deploy/tests/**"
  - "e2e/**"
  - "bits/tests/**"
  - "web/**/*.test.ts"
  - "web/**/*.test.tsx"
  - ".github/workflows/**"
---

# Tests and CI gates

The full matrix is in TS §8.3. Do not lower a gate, skip a test or mark one expected-to-fail to get a change through; ask first. Test locations: Python in `manager/tests/`, Go unit and agent tests as `*_test.go`, sandbox and security VM suites in `agent/test/sandbox/`, package tests in `deploy/tests/`, end-to-end and load in `e2e/`, web tests as `web/**/*.test.ts(x)`, and `.bit` fixtures (malformed, XXE, billion-laughs, oversize) in `bits/tests/`.

- **Unit:** cover the parser, normaliser (CRLF, trimming; `.gitattributes` has `* text=auto eol=lf`, so build CRLF inputs as in-code literals such as `"\r\n"`, or mark their fixture paths `-text` in `.gitattributes`), validators (one case per BIT code), Debian version comparison (against `dpkg --compare-versions`, at least 500 pairs, TS §7.2), `evaluate()` (every one of the 14 operators and every ERROR case) and the BIT102 lexer (the SR §1.1 example, a corpus of common CIS commands and the allowed read-only uses must pass), plus CSV formula escaping for every export (TS §6.3). Redaction fixtures:
  - must be redacted: a shadow line, a full and a cut-off private key, `key=value`, a `bsa_` token (TS §8.3), AKIA and ASIA key ids (TS §8.6 pattern 4);
  - must stay unchanged: normal check output such as `install ok installed`, `PasswordAuthentication no`, `passwd: files`.

  Gate: at least 85 % line coverage on `manager/services` (= `manager/bitscan_manager/services/` in this layout; the M0 coverage config must point there). The SR §1.1 canonical example must import successfully.
- **Property and fuzz:** the `.bit` parser with random and malformed XML, and the inventory decoder with oversized and malformed input, including gzip bombs. Gate: no crash and no partial import.
- **Contract:** the JSON Schemas for every agent route are shared by the Python manager and the Go agent, and both pass the same fixtures.
- **Integration:** API plus PostgreSQL 16 through Testcontainers. Cover every endpoint, a rebuild of a corrupted catalog, partition maintenance, and `/readyz` failing when the `inventory` `system_schedule` row is missing (TS §3.4). Grant probes, run on a freshly migrated database:
  - `bitscan_app` cannot UPDATE or DELETE results through the parent, the default partition or a newly created partition;
  - it cannot delete scans, jobs, agents or the audit log, or move a job to another host or scan;
  - `bitscan_retention` can delete only from the retention tables.
- **Agent:** runner timeouts, output caps, redaction, spool overflow and back-off. Runs on Ubuntu 22.04, Ubuntu 24.04 and Debian 12, on both amd64 and arm64.
- **Sandbox:** the units pass `systemd-analyze verify` as written. Tests show a plugin cannot:
  - write files, open IP sockets, or execute files outside system paths;
  - reach the blocked local sockets, `ptrace` the runner, inherit its socket or replace it;
  - call state-changing D-Bus methods;
  - outlive its job.

  The full CIS plugin set passes under the sandbox and BIT102, and `systemctl is-active`, `is-enabled`, `list-units` and `list-unit-files` work under the D-Bus policy. Run these on every PR touching units, the runner or plugins, on amd64 and arm64.
- **End-to-end (nightly, 3 VMs):** enrol → approve enrolment → heartbeat → inventory → import → scan → results.
- **Load:** 10,000 simulated agents heartbeating, with p95 under 200 ms.
- **Security:** must be rejected:
  - expired, foreign and replayed jobs (by both agent and runner);
  - tokens on the wrong route group;
  - API tokens used for sensitive actions, token creation or TOTP changes (and on `DELETE /policies/{id}`, a TOTP-session route);
  - non-admins uploading or deleting policies;
  - BIT015 and BIT102 violations;
  - a manager certificate that fails verification or its pin.

  Also: uploads with hostile file names are stored safely, and the first result wins under concurrent retries. Run the security suite on every PR touching the importer, auth, agent or runner.
- **Packaging and release (TS §3.1, §8.1):** `lintian` passes; install, reinstall, upgrade and purge prove the maintainer scripts idempotent; agent builds are reproducible (two builds, identical hashes) and each release ships an SBOM.
- **Static gates:** CI runs every command in CLAUDE.md "Commands" (ruff, `mypy --strict`, `pip --require-hashes`, gofmt, golangci-lint, `CGO_ENABLED=0`, `go mod verify`, web lint and typecheck), plus Prettier and an OpenAPI client regeneration with no diff. Migrations are forward-only, one per PR.
- Tests that need PostgreSQL run the TS §5.2 Bootstrap block, then `bitscan-manager db migrate` (as `bitscan_migrate`, `SET ROLE bitscan_owner`); never apply the raw spec DDL. A schema-diff test compares the migrated database with the TS §5.2 DDL. Tests never run as a superuser after the bootstrap.
- Backup restore is tested monthly as an operational check, not in CI (TS §5.3).
- **Open spec question:** the package-search target (< 1 s at 10,000 hosts × 2,000 packages, TS §7) and the agent idle target (< 0.1 % CPU, < 30 MB RSS, TS §3.3) have no TS §8.3 gate; ask before adding CI performance gates.
