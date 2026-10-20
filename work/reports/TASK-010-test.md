# TASK-010 TEST report: CI workflows for agent gates and systemd units verify

Tester: tester. REQ-017, REQ-010, REQ-011, REQ-016. Date 2026-10-20. Impl report: `work/reports/TASK-010-impl.md` (round 2: stubs-run step). Plan: `work/plans/TASK-010.md`.

## Verdict: PASS (round 3; local static checks and step substitutes)

NOT RUN locally:
- the live PR runs of both workflows (CHK-M0-144): this needs GitHub Actions and a pushed branch, and pushing is not authorised;
- the real `systemd-analyze verify` and the `/usr/sbin` and `/usr/bin` installs (G17; CHK-M0-124, CHK-M0-125): no systemd;
- running the ELF stubs on Linux (CHK-M0-146).

They must be confirmed on the first PR run.

## Method

- Both files were parsed with js-yaml for triggers, permissions, steps and forbidden constructs.
- Each `run:` block was extracted with its `working-directory` and run as Actions does (`bash --noprofile --norc -eo pipefail`), in `mktemp -d` copies deleted afterwards:
  - the golangci-lint install step was replaced by the local 2.14.0;
  - the stubs-run step was checked with Windows PE builds of the real stub source and with mutants;
  - the verify step was checked against a stub `systemd-analyze`.

## Counts

- agent.yml: clean, all steps green.
- 13 plants, each turning the expected step red, with no unexpected red on another step. G10 (a) correctly reddens build, listing, lint and test together.
- Stubs step: 1 green proxy and 6 red mutants.
- units.yml: 3 verbatim runs, 1 build, 1 install and 3 verify-logic runs, all as expected.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-017 (1): every gate is its own step, with no `continue-on-error`, `\|\| true` or skip | CHK-M0-140, CHK-M0-141, CHK-M0-142, CHK-M0-143 | PASS |
| REQ-017 (2): both workflows pass on a PR with the clean tree | CHK-M0-144 | NOT RUN (local substitute green: CHK-M0-145, CHK-M0-142-sub) |
| REQ-017 (3): each job fails on one planted violation (G7 to G10, G17) | CHK-M0-145, CHK-M0-147, CHK-M0-142-sub | PASS for the G7 to G10 substitutes; G17 NOT RUN (the verify logic was shown with a stub) |
| REQ-017 (4): linux/amd64 and arm64 builds | CHK-M0-141, CHK-M0-145 | PASS |
| REQ-017 (5): the gofmt step fails when `gofmt -l` prints anything | CHK-M0-145 | PASS |
| REQ-017 (6): the units job installs the binaries before verify and fails on any error or output | CHK-M0-142, CHK-M0-142-sub | PASS (static and logic); real run NOT RUN |
| REQ-017 (7): no secret, token or credential | CHK-M0-143 | PASS |
| REQ-010 (2), (4): `file` statically linked; stubs exit non-zero within 1 s, no stdout, one stderr line | CHK-M0-141, CHK-M0-146 | PASS (proxy); ELF run NOT RUN locally |
| REQ-010 (3): the go list step fails on `import "C"` next to main.go, and (round 3) on assembly and `.syso` files | CHK-M0-147 | PASS |
| Review finding 4 (TASK-004): nolint and go:linkname grep | CHK-M0-145 | PASS |

## Notes

- arm64 binaries are built and checked with `go version -m` and `file`, but never executed (no arm64 runner yet); this needs a decision before M6.
- The units job installs the dev lock rather than the runtime lock, because hatchling is only in the dev lock. That is the deviation in the impl report, and it is acceptable for CI scaffolding.
- `deploy/tests/check_units_verbatim.py` (tester-owned) is now a CI step, so changing it changes a gate.
