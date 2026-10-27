# M6 commit split and PR draft (lead)

Draft only. Nothing is committed or pushed until the user says so. Finalise after the M6 gate (TP-M6-14) and the closing review (`work/reviews/M6-gate.md`); fill in the gate numbers marked TBD.

## Commits on `m6-release` (from main `8ad50eb`)

1. `feat(manager,deploy): 0.1.0 release packaging, runbooks and release workflow`
   - `manager/pyproject.toml` (wheel with the built UI and every migration, no tests)
   - `manager/bitscan_manager/api/user/agents.py`, `services/agents/fleet.py`, `repositories/agents.py`, `repositories/inventory.py` (id-only paging cursors)
   - `agent/.golangci.yml` (forbid `net.FileConn`, `net.FilePacketConn`, `fcgi.Serve`)
   - `deploy/debian/changelog`, `deploy/debian/bitscan-agent.lintian-overrides`, `deploy/debian/rules` (comments only)
   - `deploy/systemd/bitscan-capread.socket` (TASK-138: `RemoveOnStop=yes`, the one recorded deviation from the TS §3.7 unit)
   - `deploy/runbooks/agent-install.md`, `deploy/runbooks/manager-install.md`, `deploy/runbooks/manager-operations.md`
   - `.github/workflows/release.yml`
   - `README.md`
2. `test(manager,deploy,e2e): M6 suites, release checks and end-to-end harness`
   - `manager/tests/test_agent_cursors_pg.py`, `test_agent_repo_pg.py`, `test_inventory_repo_pg.py`
   - `deploy/tests/check_debian_meta.py`, `check_units_verbatim.py` (the TASK-138 exception), `test_maintainer_scripts.sh`, `test_manager_wheel.sh`, `check_manager_host.sh`, `check_manager_sboms.py`, `check_md_links.py`, `check_release_workflow.py`, `check_runbook_bootstrap.py`, `check_runbook_text.py`
   - `e2e/m6/` (all files)
3. `docs: M6 plans, test and review records`
   - `work/` (requirements, tasks, plans, reports, reviews, decisions, open questions, status), `tests/m6/`, `tests/test-plan.md`

4. `chore(claude): supported hosts, team speed rules, capread socket exception` (user to authorise; `.claude/` changes are the user's)
   - From the main `Bitscan` checkout, uncommitted there: `.claude/CLAUDE.md` (Supported hosts: Ubuntu 22.04 and 24.04, amd64), `.claude/skills/bitscan-team/SKILL.md` (testing by risk), `.claude/rules/deploy/packaging-and-units.md` (the TASK-138 `RemoveOnStop=yes` exception, the user's edit), `.gitignore`.
   - The main checkout's `work/decisions.md`, `work/status.md` and `work/reviews/builder-checklist.md` edits are older copies. The `Bitscan-m6` copies supersede them, so diff them before discarding the main checkout's.

Each commit message ends with:

```text
Co-Authored-By: Claude Code <noreply@anthropic.com>
```

Before committing: check that no stray scratch file is in the tree (`git status --short --untracked-files=all`), and that `work/audit/archive/` is untouched.

## PR description

Title: `M6: first release 0.1.0 (manager wheel, agent 0.1.0-1, runbooks, release workflow)`

```markdown
## Summary

First-release gate (M6). Bitscan 0.1.0 can be installed, upgraded, backed up and removed from runbooks, and inventory works end to end on real Ubuntu hosts. Compliance scanning is not in this release: agents answer compliance jobs with `runner_unavailable`.

Implements TS §2.2, §3.1, §3.3, §3.7, §5.2 (Bootstrap), §5.3, §6.3, §8.2, §8.4, §8.7 for REQ-137 to REQ-149 (TASK-129 to TASK-138).

## Changes

- **Manager wheel** (TASK-129): ships the built web UI and every migration, no tests; version 0.1.0.
- **Agent 0.1.0-1** (TASK-130): changelog entry and the agent runbook for the first release; one unused lintian override removed.
- **Paging cursors** (TASK-131): `/agents` and `/agents/{id}/packages` cursors carry only ids; a cursor whose anchor is gone or foreign is 400 (was 404 for a missing agent).
- **Agent lint** (TASK-132): forbidigo also forbids `net.FileConn`, `net.FilePacketConn` and `fcgi.Serve` in non-test agent code.
- **Manager install runbook** (TASK-133): PostgreSQL 16 with TLS-only roles, the TS §5.2 Bootstrap byte for byte, the verbatim units, secrets via `LoadCredential=`, first admin. A database on another host uses `sslrootcert=/etc/bitscan/postgres-ca.pem` (#97).
- **Operations runbook** (TASK-134): upgrade (stop, install, migrate, start), certificate and OpenBao token replacement, nightly dump, monthly restore test, WAL archiving with weekly base backups and pruning, point-in-time recovery (including moving the audit id sequence past the shipper cursor), and removal with an audit drain check.
- **Release workflow** (TASK-135, TASK-136): version agreement, double `.deb` build and compare, wheel with a UI check, `SHA256SUMS`, CycloneDX SBOMs for the Python lock and the bundled UI, draft release on a tag only; actions pinned by commit, least privilege.
- **README** (TASK-137): 0.1.0 status and an "Installing a release" section.
- **Capread socket** (TASK-138): `RemoveOnStop=yes`, so disabling the helper removes `/run/bitscan/capread.sock` and the next heartbeat reports `[]`, which raises the "helper off" `runner_helper_changed` entry. Release candidate `bitscan-agent_0.1.0-1_amd64.deb` sha256 `d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf`.

## Deviations and owner notes

- **Spec deviation (user decision 2026-10-26):** `bitscan-capread.socket` adds `RemoveOnStop=yes` to the verbatim TS §3.7 unit. It adds no privilege or listener, and the helper stays disabled by default. The verbatim check allows exactly this line.
- Ubuntu 22.04 and 24.04 on amd64 only (arm64 and Debian 12 dropped earlier, decisions 2026-10-24).
- The end-to-end run used one VM at a time with 1 GB each (test-environment limit; plan L99–L102).
- `systemctl reload` does not refresh the `LoadCredential=` copies, so certificate replacement needs a restart (#96); TS §8.7 L1343's SIGHUP wording is for the owner.
- `/run/lock` is writable under the verbatim manager unit (systemd behaviour); accepted (O1).
- The web SBOM is not byte-reproducible (`npm sbom` writes a serial number and timestamp).
- For the owner, no change in this PR: the #65 (b) alert re-arm state is in memory only, so a manager restart re-alerts; a later product guard for the audit shipper cursor after a restore.
- Test waits were skipped by time-skewing in the throwaway test database or VM clock (user rule); production timings are unchanged, and the gate re-checks them against the spec.

## Tests

- Every task tested and reviewed; TASK-132 and TASK-138 have the second approval (TS §8.2).
- Full manager suite with coverage on the final tree: 4,824 passed, 0 failed, 99.41 % (gate 85 %).
- Manager install walk 59/59 and host checks 19/19 on a fresh host; operations walk including PITR and removal.
- Release workflow run locally on the final tree: two `.deb` builds byte-identical, equal to the VM-tested RC `d98ef8c3…`; `SHA256SUMS` OK; SBOM check 0 findings. G41 on the RC 23/23.
- End to end on Ubuntu 22.04 and 24.04 VMs (Hyper-V): install with and without a pin, enrol, inventory, package search, every alert kind, CA and pin refusals, route-group and API-token refusals, revoke, re-enrol, purge and stale; no tokens in the manager journal or the sink. Each W4 failure was a harness defect, fixed and re-checked on a fresh 24.04 host (46/48, the two FAILs harness expectations, accepted with evaluation rows): token file modes with a 0644 control, a journal canary over every field with positive controls, agent and manager write sweeps, a manager secret canary (0/0 with a control), re-enrolment, and revoke with a 10-minute path-based no-call count (28/28).
- M6 gate TP-M6-14: **PASS with one named exception**; closing review APPROVED (`work/reviews/M6-gate.md`). Mutation table red on its plants, including the wheel plants (320x, 321, 322), the coverage boundary (85.02 % green, 84.99 % red) and two unit-level plants for the clock-skew threshold and the alert flag.
- **Not run (owner sign-off):** the VM plants CHK-M6-340..345 (a planted agent or manager on a VM must turn the end-to-end rows red). The session's safety check blocked them; they run before any M7 code. Each fault is covered at a lower level (`tests/m6/report.md`, Gate TP-M6-14). Also not run: the load and soak tests (deferred since 2026-10-24, so no evidence yet for large fleets); the release workflow on GitHub (it runs on the v0.1.0 tag).
- Not run: the release workflow on GitHub (needs this PR and a tag).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
