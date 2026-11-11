# Review: release 0.2.0 batch (TASK-262, TASK-263), one round

Reviewer: reviewer-rel, 2026-11-11. Tree: `Bitscan-m11`, branch `release-0.2.0`, working tree against `d26c472`.

Verdict: APPROVED

Both tasks: no blocking or should-fix finding; four nits below. TEST: tester-rel2's round 2 re-runs of CHK-R020-034, -036 and -040 PASS (relayed by `main`; the lead records `tests/release/report.md` and `work/reports/TASK-26{2,3}-test.md` from tester-rel2's reply, because a rule refused the tester's write). CHK-R020-046 (SBOMs) is NOT RUN; the `release` run on the PR covers it (L5). The -034/-036 fix is the text reviewed here: changelog L14–L24, README L355 and L395.

## Scope reviewed

- TASK-262: `manager/pyproject.toml`, `manager/bitscan_manager/__init__.py`, `manager/openapi.json`.
- TASK-263: `deploy/debian/changelog`, `deploy/debian/control`, `README.md`, `deploy/runbooks/agent-install.md`, `manager-operations.md`, `manager-install.md` (the sixth file, added by the lead's ruling).
- Tester changes (PD-51, old → new): `manager/tests/test_openapi.py` L75 and `test_project_config.py` L42 (`0.1.0` → `0.2.0`); `deploy/tests/test_manager_wheel.sh` L32 (`VERSION=0.2.0`); `deploy/tests/check_runbook_bootstrap.py` L6 and L22 (1018–1033 → 1023–1038, after the TS §5.2 index commit `68d3881`); `e2e/m6/manager_walk.py` (`rel_version`, `rel_files`, the §6 step); the new `e2e/m6/check_walk_rel_version.py`.
- BIT102 text was checked only against decisions 2026-11-11 (last row) and 2026-10-27 "BIT102, a non-literal command word". No BIT102 or lexer file was read (scope limit).

## Checks run by the reviewer

| Check | Result |
| --- | --- |
| `git diff d26c472 -- manager/openapi.json` | one line, `info.version` `0.1.0` → `0.2.0` |
| `pytest tests/test_openapi.py tests/test_project_config.py` (WSL venv, tree on `/mnt/c`, no cache) | 16 passed, including both byte-stability exports (G6) |
| `ruff check manager` (WSL) | all checks passed |
| `check_debian_meta.py` | OK 83/83 |
| `dpkg-parsechangelog` (WSL) | `0.2.0-1`, `Wed, 11 Nov 2026 00:00:00 +0000`; the entry below is `Sun, 08 Nov 2026`; urgency medium; no line over 80 characters |
| `check_md_links.py README.md deploy/runbooks/*.md` | OK, 42 links |
| `check_runbook_text.py` (4 files) | only the 2 known `agent-install.md:79` and `:123` placeholder findings, also present on the base |
| `check_runbook_bootstrap.py` | OK vs TS L1023–L1038 (L1023 is the sql fence after the **Bootstrap** paragraph at L1021) |
| `e2e/m6/check_walk_rel_version.py` | 17/17 passed |
| Grep of added user-facing lines for task, REQ, CHK or PD ids, `#NNN`, role names and token-like strings | none; only `TS §8.5`, the README's existing citation style (REQ-145 (3)) |

## Conformance notes

- **Versions:** pyproject, `__version__` and `info.version` are `0.2.0`, and the changelog upstream version is `0.2.0`. The `release.yml` versions step (L57–L85) therefore accepts `0.2.0` and refuses `~` and any mismatch.
- **Compatibility** (README L55, agent-install L170, manager-operations L43–L45) matches the `e2e/m11/compat.py` header rows. Row (a), manager N with agent 0.1.0-1: every plugin ERROR `runner_unavailable`. Row (b), manager 0.1.0 with agent N: enrol to inventory, and no compliance job. Nothing beyond those rows is claimed. Agent N with manager N−1 is the user's 2026-11-08 (1) "both ways" answer.
- **`~pre` builds stay unsupported:** README L5 and L55; agent-install L7 and L170; manager-operations L52.
- **#111:** changelog L22–L24 and README L355 both say the samples are not in the package or the manager release, and that the CIS control numbers are unconfirmed (TS §8.5). The samples' own `PolicyDescription` keeps "not yet confirmed". Neither `bitscan-agent.install` nor the hatch `packages`/`artifacts` holds a `bits/` path.
- **BIT102 known limit** (changelog L14–L21, README L395):
  - It names the `-c` strings of su/runuser/flock, `trap`, brace expansion in `bash -c`, the extra wrappers, abbreviated long options (getopt), the `time -o`/`--output` and `flock` output targets, and the non-literal command word (2026-10-27).
  - It names the runner sandbox as the real control.
  - It claims no r2 rule.
- **Built features:**
  - The release files listed in README L39–L42 are the set `release.yml` publishes for `${VERSION}`.
  - `bits rebuild` (manager-operations L218) exists in `cli/bits.py` (TS §8.7).
  - Scans by host, tag or fleet, schedules, results and score, results CSV, re-evaluation (`api/user/reevaluate.py`) and retention are all in the built tree.
  - `control`'s "the helper stays off until an administrator enables it" matches `--no-enable --no-start` for both capread units.
- **No out-of-scope claim:** nothing about signing, an APT repository, arm64, Debian, CVE matching, OIDC or remediation.
- **e2e:**
  - In the CI walks, only `manager_walk.py` runs a block that names a version (the §6 block). It now takes the version from the `--rel` wheel. compat-b (the v0.1.0 files with this tree's runbook) installs the `0.1.0` names; nightly and compat-a are unchanged (the substitution is the identity).
  - `compat.py`'s upgrade phase already substitutes `0.1.1` with the `--rel` wheel's version.
  - `ops_upgrade.py`, `ops_walk.sh` and `readme_walk.sh` hold 0.1.0 pins, but `e2e.yml`, `nightly.py` and `compat.py` call none of them.
  - The README walk tests read no changed prose (CHK-R020-040 PASS).

## Findings

1. **nit**, `deploy/runbooks/agent-install.md:178`. The in-place upgrade sentence lists `0.1.0-1`, `0.2.0~pre1-1` and `0.2.0~pre2-1`. But L7 and README L5 send `0.1.0~preN-1` hosts to section 6 too, and those hosts are not named here. The general "upgrade every such host to `0.2.0-1`" (L170) covers them. Fix if touched again: add `0.1.0~preN-1` to the list (it also sorts below `0.2.0-1`).
2. **nit**, `deploy/runbooks/manager-operations.md:12`, L17–L18. The upgrade example is still "for example 0.1.1" in a 0.2.0 release. Keep it: `ops_upgrade.py` L123 and `compat.py` L284 substitute `0.1.1`. No change requested.
3. **nit**, `README.md:395` and `deploy/debian/changelog:20`. "the output files that `time -o` or `--output` and `flock` open" is hard to parse. Suggested wording: "the file `time -o` (`--output`) writes, or the lock file `flock` opens".
4. **nit**, `deploy/debian/changelog:12`. "deletes old scans, inventory and other data" could be read as covering current inventory, which retention never deletes. Suggested wording: "old scans, inventory jobs and snapshots, and other data".

Not checked by scope: whether r1 actually lets each listed form through (for example `time` and the `sudo --us` example). The list comes from the ruling. Where it overstates a gap, it errs toward caution.

## Follow-up (not a finding)

The lead has already recorded it (status 2026-11-11): five `deploy/tests` checkers run in no CI workflow, and `check_runbook_bootstrap.py` was red on `main` until this branch re-pinned it.
