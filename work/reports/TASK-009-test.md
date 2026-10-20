# TASK-009 TEST report: CI workflows for manager gates, web gates and the OpenAPI regeneration diff

Tester: tester. REQ-017, REQ-002, REQ-005, REQ-007, REQ-015. Date 2026-10-20. Impl report: `work/reports/TASK-009-impl.md`. Python 3.12.10, Node 24.22.0, npm 11.19.1.

## Verdict: PASS (round 2; local static checks and step substitutes)

NOT RUN locally:
- the live PR runs (CHK-M0-136, and CHK-M0-137 live): this needs GitHub Actions and a pushed branch, and pushing is not authorised;
- the PostgreSQL tests with Docker (CHK-M0-050 to -052, -057; TASK-003);
- the Ryuk digest pull by the daemon.

The first PR run must confirm them. With `CI=true` and Docker on the runner, the pg tests cannot be skipped silently: no Docker fails the run (shown locally).

## Method

- Both files were parsed with js-yaml for triggers, permissions, steps and forbidden constructs.
- Every `run:` block was extracted with its step `env` and run as Actions does, in `mktemp -d` copies:
  - each copy has a scratch git index (`git init`, `git add -A`, never committed), so `git diff --exit-code` compares against the "committed" state;
  - each plant is staged, as a PR would commit it.
- Windows adaptations: venv `bin` becomes `Scripts`, `$GITHUB_PATH` is emulated, and `CI=false` is used for the pytest step only when proving G5 (no local Docker).

## Counts

- manager.yml: clean run (as written, and with the CI override), and 14 plants, each turning its gate step red.
- web.yml: clean run (all green), and 14 plants, each turning only its gate step red (G11 cascades to the npm-dependent steps, as expected).

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-017 (1): every gate G1 to G6 and G11 to G16 is its own step, with no skip, `continue-on-error` or `\|\| true` | CHK-M0-130 to CHK-M0-133 | PASS |
| REQ-017 (2): both pass on a PR with the clean tree | CHK-M0-136 | NOT RUN (local substitute green, CHK-M0-137) |
| REQ-017 (3): each job fails on one planted violation per gate | CHK-M0-137 | PASS (substitute); live NOT RUN |
| REQ-017 (4): CPython 3.12; PostgreSQL tests with Docker, failing if Docker is missing | CHK-M0-134, CHK-M0-137 | PASS (`CI=true` set; the no-Docker failure was shown) |
| REQ-017 (7): no secret, token or credential | CHK-M0-135 | PASS |
| REQ-002: hashed installs of both locks as committed (`--only-binary` applies) | CHK-M0-131, CHK-M0-137 | PASS |
| REQ-005: coverage gate on services | CHK-M0-137 | PASS |
| REQ-007 (4), REQ-015 (2), (3): the export and client diff checks regenerate first | CHK-M0-132, CHK-M0-137 | PASS |
| Review carry-overs: `npm ci --ignore-scripts`, gen:api before the diff, Ryuk pinned by digest | CHK-M0-132, CHK-M0-134 | PASS (the Ryuk pull is NOT RUN) |
| Review should-fix (round 2): a committed deletion of a generated file is caught | CHK-M0-137-r2 | PASS |

## Notes

- If Ryuk fails to start on the first run with `name:tag@digest`, the impl report's fallback is `testcontainers/ryuk@sha256:...`. Ryuk must not be disabled.
- The web job exports with the runtime lock and `PYTHONPATH=manager`, not the installed package. The result is equivalent for the export.
