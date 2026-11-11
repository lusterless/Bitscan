# Release 0.2.0 test plan (TASK-262, TASK-263)

Owner: tester-rel2. Drafted 2026-11-11 from `work/tasks.md` "Release 0.2.0" (the TASK-262 and TASK-263 rows, "Release test plan (tester-rel)", the lead and user steps L4, L5), `deploy/runbooks/manager-operations.md` §1 and §7, the decisions of 2026-11-11 ("Release 0.2.0 started" (2) to (4), and the last row: 0.2.0 ships BIT102 revision 1 as a named release exception) and the lead's two additions of 2026-11-11 (CHK-R020-016, -017, -036), before the IMPL diffs were read.

Spec: TS §8.2 L1272 (semantic versioning), TS §8.7 L1353 (manager N supports agents N and N−1), decisions 2026-11-08 (1) (agent N supports managers N and N−1), TS §3.1 (`.deb` with a published SHA-256), TS §8.5 and #111 (control numbers unconfirmed), REQ-137, REQ-139, REQ-141, REQ-142, REQ-145, REQ-290.

Where: **L** = Windows worktree (Git Bash, `manager/.venv`); **W** = WSL Ubuntu-24.04, from a copy in the tester's own work folder (`/root/rel2/tree`), Zscaler CA mounted read-only (`/etc/ssl/certs/ca-certificates.crt`, `SSL_CERT_FILE` set), pytest with xdist and one PostgreSQL container per worker; **W-c** = a disposable `ubuntu:24.04` container in WSL; **GH** = a GitHub Actions run on the release PR (lead steps L4, L5).

Acceptance-criterion change recorded here: the TASK-263 row says "the changelog and README say the BIT102 r2 rules are in". The user's ruling of 2026-11-11 (last decisions row) supersedes it: 0.2.0 ships BIT102 revision 1, so the text must **not** claim the revision 2 rules and must name the unchecked forms as an accepted limit, with the runner sandbox as the real control (CHK-R020-036, lead 2026-11-11).

## Re-pins (PD-51 pattern: old → new)

| File | Old pin | New pin | Old CHK | New CHK |
| --- | --- | --- | --- | --- |
| `manager/tests/test_openapi.py` L75 | `info.version == __version__ == "0.1.0"` | `== "0.2.0"` | CHK-M0-040 (version part) | CHK-R020-006 |
| `manager/tests/test_project_config.py` L42 | `project.version == "0.1.0"` | `== "0.2.0"` | CHK-M0-011 (version part) | CHK-R020-007 |
| `deploy/tests/test_manager_wheel.sh` L32 | `VERSION=0.1.0` (wheel name and metadata, REQ-137) | `VERSION=0.2.0` | CHK-M6-020, CHK-M6-022 (version part) | CHK-R020-009 |

Left as they are (test inputs, not tree-version pins; CHK-R020-012): the `0.1.0` values in `e2e/m6/release_checks.sh` (inputs to the versions step in a scratch workspace), the agent versions `0.1.0` / `0.1.0-1` in `manager/tests` fixtures, `e2e/m11/compat.py` (the published v0.1.0 release), the `~pre` versions in `e2e/agent_binary*.sh`, `e2e/runner_unit_m10.sh`, `deploy/tests/test_debconf.sh`, `test_maintainer_scripts.sh` and the agent Go tests (build inputs and upgrade-from versions).

## TASK-262: manager version 0.2.0 (CHK-R020-001 to -019)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-R020-001 | CODE | `manager/pyproject.toml` `[project].version` is `0.2.0` (read with `tomllib`) | L |
| CHK-R020-002 | CODE | `bitscan_manager.__version__` is `0.2.0` (imported from the tree) | L |
| CHK-R020-003 | CODE | `manager/openapi.json` `info.version` is `0.2.0` | L |
| CHK-R020-004 | CODE | `git diff <branch base> -- manager/openapi.json` changes exactly one line, `"version": "0.1.0"` → `"version": "0.2.0"` under `info` (base = `git merge-base HEAD main`) | L |
| CHK-R020-005 | CODE | G6: `python -m bitscan_manager.app <tmp>/a.json` and `<tmp>/b.json`: both `cmp`-equal to the committed `manager/openapi.json` | L + W |
| CHK-R020-006 | CODE | `manager/tests/test_openapi.py` passes after the re-pin (passed/total) | W |
| CHK-R020-007 | CODE | `manager/tests/test_project_config.py` passes after the re-pin (passed/total) | W |
| CHK-R020-008 | CODE | Before the re-pin the same two files fail exactly on the two version assertions (the pins can fail) | W |
| CHK-R020-009 | APP | Wheel from the tree: `pip wheel --no-deps --no-build-isolation manager/` gives exactly `bitscan_manager-0.2.0-py3-none-any.whl`; its `METADATA` has `Version: 0.2.0` (REQ-137 name follows the version) | W-c |
| CHK-R020-010 | APP | The `release` workflow's step "Tag, pyproject and changelog versions agree", run locally as written (script taken from `.github/workflows/release.yml`, scratch workspace = the tree's `manager/pyproject.toml`, `manager/bitscan_manager/__init__.py` and `deploy/debian/changelog`): manual run with version `0.2.0` passes, outputs `version=0.2.0`, `deb_version=0.2.0-1`; push of tag `v0.2.0` passes | W |
| CHK-R020-011 | CODE | `__version__`, pyproject version and the changelog upstream version agree (`0.2.0` = `0.2.0` = upstream of `0.2.0-1`) | L |
| CHK-R020-012 | CODE | No other tree-version pin of `0.1.0` in `manager/`, `deploy/tests/`, `e2e/` (grep; every hit classified as a test input) | L |
| CHK-R020-013 | CODE | `deploy/tests/check_release_workflow.py` passes on the tree (shared with TASK-263) | L |
| CHK-R020-016 | CODE | Release tree (lead, user ruling 2026-11-11): `sha256sum manager/bitscan_manager/services/importer/bit102.py` = `279291cff382653ffcc59a2382e32f57c0586bbe84011acdcf466de5d8a991fd` (hash only; contents not read) | L |
| CHK-R020-017 | CODE | Release tree: neither `bit102_wrappers.py` nor `bit102_braces.py` exists in `manager/bitscan_manager/services/importer/`, tracked or untracked (file list only) | L |

## TASK-263: release notes and packaging text (CHK-R020-020 to -059)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-R020-020 | CODE | `python deploy/tests/check_debian_meta.py` passes | L |
| CHK-R020-021 | CODE | `python deploy/tests/check_runbook_text.py`: no finding other than the 2 known `agent-install.md` findings of the TASK-259 record | L |
| CHK-R020-022 | CODE | `python deploy/tests/check_md_links.py` passes | L |
| CHK-R020-023 | CODE | `python deploy/tests/check_release_workflow.py` passes (= -013) | L |
| CHK-R020-024 | CODE | `dpkg-parsechangelog -l deploy/debian/changelog -S Version` = `0.2.0-1`; `-S Source` = `bitscan-agent`; no warning on stderr | W |
| CHK-R020-025 | CODE | The top entry's date (`-S Date`) is after the second entry's date (`--offset 1 --count 1 -S Date`, expected the `0.2.0~pre2-1` entry, Sun, 08 Nov 2026) and not in the future of the run | W |
| CHK-R020-026 | APP | `bash deploy/debian/build-deb.sh` (mode 100644) in a W-c container from a clean copy of the tree gives `bitscan-agent_0.2.0-1_amd64.deb`; `dpkg-deb -f … Version` = `0.2.0-1` | W-c |
| CHK-R020-027 | APP | G37: `lintian` on that `.deb` prints nothing at the default level and exits 0 | W-c |
| CHK-R020-028 | CODE | `deploy/debian/control` holds neither `(pre-release)` nor the "0.x pre-releases … idle" sentence | L |
| CHK-R020-029 | CODE | No `~pre` text in `README.md`, `deploy/` (non-test), `docs/` outside `docs/spec`, except: (a) the changelog entries below the top one; (b) the "pre-release agent builds are not supported" rule; (c) checkers or workflow lines that refuse `~` (each hit listed) | L |
| CHK-R020-030 | CODE | README and both runbooks hold no pre-release note for 0.2.0 (grep `pre-release`, `prerelease`, `not yet released`, `0.2.0~`; each hit classified) | L |
| CHK-R020-031 | CODE | `manager-operations.md` §1 **Compatibility** states: manager 0.2.0 supports agents 0.2.0-1 and 0.1.0-1; agent 0.2.0-1 supports managers 0.2.0 and 0.1.0 | L |
| CHK-R020-032 | CODE | The agent runbook's **Compatibility** states the same pairs as -031 | L |
| CHK-R020-033 | CODE | The Compatibility text (-031, -032) matches the compat rows named in the `e2e/m11/compat.py` header (manager N with agent 0.1.0-1; manager 0.1.0 with agent N; what each row shows, for example no compliance job from manager 0.1.0, `runner_unavailable` for the 0.1.0-1 agent) and claims nothing those rows do not test | L |
| CHK-R020-034 | CODE | #111: the changelog and README say the sample policies' CIS control numbers are not yet confirmed, and that the samples are not in the `.deb` or the manager release | L |
| CHK-R020-035 | APP | The samples are really absent: no `bits/samples/` file (by name or by hash) in the built `.deb` (`dpkg-deb -c`) or in the wheel built from the tree (`unzip -l`) | W-c |
| CHK-R020-036 | CODE | BIT102 text (user ruling 2026-11-11, lead): the changelog and README do not claim the BIT102 revision 2 rules (no claim of new refusals for `su`/`runuser`/`flock -c` strings, `trap`, brace expansion in `bash -c`, extra wrappers, getopt abbreviations, `time -o`/`flock` output targets); they name the unchecked forms as an accepted limit, and name the runner sandbox as the real control. The list must hold every r2 gap the ruling names: the `-c` strings of `su`/`runuser`/`flock`, `trap`, brace expansion in `bash -c`, the extra wrappers, getopt (abbreviated long option) forms, the `time -o`/`flock` output targets, and (lead ruling Q1, 2026-11-11) the accepted residual of a command word taken from a variable or other non-literal form (decisions 2026-10-27) | L |
| CHK-R020-037 | CODE | Nothing describes unbuilt behaviour: every claim in the changed lines of the 6 TASK-263 files maps to a built and tested feature (one evidence item per claim); no out-of-scope claim (arm64, Debian, Ubuntu 20.04, signed APT repository, signing, CVE, OIDC, client certificates, remediation, policy editor) | L |
| CHK-R020-038 | CODE | User terms: the changed text has no task id, REQ, CHK, PD, decision date, team role or process note (REQ-139 (4), REQ-142 (5), REQ-145 (3)) | L |
| CHK-R020-039 | CODE | No token-like string (`bs[uaek]_` + 20 or more base64url characters) in the changed text | L |
| CHK-R020-040 | APP | README walk tests affected by the README change pass: `test_readme_walk_linux.py`, `test_readme_m5_walk_linux.py`, `test_readme_m7_walk_linux.py`, `test_readme_m9_walk_linux.py` (passed/total) | W |
| CHK-R020-041 | CODE | The changelog top entry is well formed: `bitscan-agent (0.2.0-1) <dist>; urgency=…`, a trailer ` -- Name <email>  <RFC 5322 date>`, and its distribution and urgency match the entry style below (`dpkg-parsechangelog -S Distribution`, `-S Urgency`) | W |
| CHK-R020-042 | CODE | Runbook §7 and the upgrade example still agree with the new state (no step that names a pre-release still to be replaced) | L |
| CHK-R020-043 | CODE | `deploy/runbooks/manager-install.md` (added to TASK-263 by the lead, 2026-11-11): the release file names at about L165–166 and L411–412 read `bitscan_manager-0.2.0-py3-none-any.whl` and `bitscan-manager-0.2.0-requirements.txt`; no `0.1.0` release file name remains anywhere in the file; the names equal the ones `release.yml` writes for version `0.2.0` (and CHK-R020-009's wheel name). This file is also in the scope of -029, -030, -037, -038 and -039 (six TASK-263 files) | L |

## Release-PR runs (CHK-R020-060 to -079; lead steps L4 and L5, GH)

Recorded from the uploaded reports after the lead runs them; NOT RUN until then.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-R020-060 | APP | L4 `e2e.yml` on `release-0.2.0`: run green; every nightly-chain row PASS in the uploaded report | GH |
| CHK-R020-061 | APP | L4: compat row manager 0.2.0 with agent 0.1.0-1: every row PASS | GH |
| CHK-R020-062 | APP | L4: compat row agent 0.2.0-1 with manager 0.1.0: every row PASS | GH |
| CHK-R020-063 | APP | L5 `release.yml` by hand with `0.2.0`: the versions step passes | GH |
| CHK-R020-064 | APP | L5: the two agent `.deb` builds are byte-identical | GH |
| CHK-R020-065 | APP | L5: `SHA256SUMS` lists every file once and `sha256sum -c` passes | GH |
| CHK-R020-066 | APP | L5: no `bits/samples/` file in the `.deb` or the wheel artifacts | GH |
| CHK-R020-067 | APP | L5: artifact names `bitscan-agent_0.2.0-1_amd64.deb`, `bitscan_manager-0.2.0-py3-none-any.whl`; no release is created by the manual run | GH |

## Plants (CHK-R020-080 onwards; each on a scratch copy, never on the tree)

| Check | Plant | Expected red |
| --- | --- | --- |
| CHK-R020-080 | Versions step, manual run with version `0.2.1` | refused (version / pyproject disagree) |
| CHK-R020-081 | Changelog top entry `0.2.0~pre3-1` (with pyproject 0.2.0) | refused (`~`) |
| CHK-R020-082 | pyproject `0.2.1`, changelog `0.2.0-1`, given `0.2.1` | refused (changelog disagrees) |
| CHK-R020-083 | Tag `v0.2.1` pushed on the tree | refused |
| CHK-R020-084 | `__version__ = "0.1.0"` with pyproject 0.2.0 | `test_openapi.py` (CHK-R020-006) red; record whether the versions step also refuses it |
| CHK-R020-085 | `openapi.json` `info.version` back to `0.1.0` | `test_committed_file_matches_a_fresh_export` and CHK-R020-003 red |
| CHK-R020-086 | pyproject back to `0.1.0` | `test_project_config.py` (CHK-R020-007) red |
| CHK-R020-087 | Changelog top date set before the entry below | CHK-R020-025 script red; record whether `check_debian_meta.py` also goes red |
| CHK-R020-088 | `(pre-release)` put back into `control` | CHK-R020-028 script red; record whether `check_debian_meta.py` also goes red |
| CHK-R020-089 | Runbook Compatibility `0.1.0-1` changed to `0.0.9-1` | CHK-R020-031 script red |
| CHK-R020-090 | `manager-install.md` wheel name back to `0.1.0` at one of the four lines | CHK-R020-043 script red |
