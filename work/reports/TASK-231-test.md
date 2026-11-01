# TASK-231 TEST: PASS (the VM runbook walk NOT RUN: VM hold)

Tester: tester-m10c, 2026-11-01. Low risk (docs), one approval. REQ-258, REQ-255 (version); PD-42; decisions "PD-42 against check_debian_meta.py" (old-to-new rule) and "User decisions before the M10 merge" (1), the VM rows as a named exception.

Under test (`work/reports/TASK-231-impl.md`): `deploy/runbooks/agent-install.md` (sections 9–11 and the cgroup v2 prerequisite), `README.md` (the compliance paragraph) and `deploy/debian/changelog` (the `0.2.0~pre1-1` entry).

Test-side changes:
- `deploy/tests/check_debian_meta.py`: the first-entry rule is rewritten per the decisions row, and a release-guard check is added. All other assertions are unchanged.
- `check231.sh` (outside the repo): the doc checks below.

## Old → new check ids (`check_debian_meta.py`)

| Old | New | Change |
| --- | --- | --- |
| CHK-M6-100 (`VERSION_RE` `^\d+\.\d+\.\d+-[1-9]\d*$`: a release, no `~`; #90) | **CHK-M10-318** | `VERSION_RE` `^\d+\.\d+\.\d+(?:~pre[1-9]\d*)?-[1-9]\d*$`: `X.Y.Z-R` or `X.Y.Z~preN-R` with N ≥ 1 and R ≥ 1 (PD-42). The RFC 2822 trailer date, the weekday and strictly-decreasing dates are all kept |
| (#90's protection, now held in `release.yml`) | **CHK-M10-319** (new) | `release.yml` must keep a `case "$deb" in` arm `*"~"*) … exit 1 ;;` on the `dpkg-parsechangelog -l deploy/debian/changelog -S Version` value, so a `~preN` build is never released. The release gate is unchanged and now has a check of its own |
| every other assertion | unchanged | rules, control, copyright, install, source/format, no arm64 |

## Runs

| Run | Command | Count |
| --- | --- | --- |
| meta check on the tree | `python -I deploy/tests/check_debian_meta.py --root .` | **OK 81/81** (78 before, plus CHK-M10-319's 2 checks and the rule's own line) |
| meta plants | `plantmeta.sh` (throwaway copies) | **8/8 red**, plus 2 green controls |
| doc checks (W) | `check231.sh` | **33/33 passed** |
| links | `python -I deploy/tests/check_md_links.py README.md deploy/runbooks/agent-install.md` | OK, 28 links, 0 findings |
| runbook text | `python -I deploy/tests/check_runbook_text.py deploy/runbooks/agent-install.md README.md` | 2 findings, both **pre-existing** on HEAD (M6 lines 76/120, the placeholder `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`). None in the M10 additions. This check is not a CI gate for this file |
| units verbatim (G17 part) | `python -I deploy/tests/check_units_verbatim.py` | OK, 10 files, 0 problems |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-315a version | CODE | W | `dpkg-parsechangelog -l deploy/debian/changelog -S Version` | PASS | `0.2.0~pre1-1` (PD-42). `dpkg --compare-versions`: 0.1.0-1 < 0.2.0~pre1-1 (the runbook's upgrade claim), 0.1.0~pre1-1 < 0.1.0-1, and 0.2.0~pre1-1 < 0.2.0-1 |
| CHK-M10-315b no secret or process note | CODE | W | greps over the 112 added lines of the three files | PASS | No token-shaped text (`bs[aeku]_…`); no `TASK-`, `REQ-`, `CHK-`, `PD-n`, tester, reviewer, `impl-`, "decisions" or `#NNN`; no `password=`/`token:` values |
| CHK-M10-315c quoted lines match the built code | CODE | W | `check231.sh`: each quoted string grepped in the source of the binary that prints it | PASS | 23/23 found, for example:<br>• `bitscan-runner started`;<br>• the `runner_unavailable` log line and `runner_unavailable: <reason>`;<br>• `start-up refused` and the four `runner: refusing to start: …` reasons;<br>• `bitscan-capread: not enabled`, `not_installed`;<br>• `agent.yaml: spool_max_mb: must be 1 to 50`;<br>• `spool full: …`;<br>• `spooled results dropped at start` and its `last_error`;<br>• `the result spool could not be opened; compliance jobs are refused`;<br>• `spool: not opened; compliance jobs refused`;<br>• `job refused; not run` / `no compliance handler` / `job refused: `;<br>• the manager's `agent last_error` log and the `runner_helper_changed` alert.<br>"The manager fails it 24 hours after it was handed out" matches M9's never-started sweep (`sweep.py`: "dispatched strictly more than 24 h ago"). Several lines were also seen live: `bitscan-runner started`, `start-up refused …`, the socket mode `srw-rw---- root bitscan-runner` and `not enabled` (TASK-226/228 WSL rows) |
| CHK-M10-315d commands | CODE | W | the new `sh` blocks | PASS | `findmnt --task 1 -n -o OPTIONS --mountpoint /tmp` and `du -sb` parse with the host's util-linux and coreutils. `systemctl is-active/enable --now/disable --now`, `journalctl -u`, `ls -l /run/bitscan/capread.sock` and `sudo -u bitscan-runner /usr/sbin/bitscan-capread nft_ruleset` match the unit and file names (the capread row ran the same client as bitscan-runner) |
| CHK-M10-315e README | CODE | L | read and `check_md_links.py` | PASS | It says hosts on this build run compliance jobs, that the results views come later ([Scans](#scans) resolves), and links the runbook sections 9–11 |
| CHK-M10-318 | CODE | L | meta check on the tree | PASS | `PASS changelog: version 0.2.0~pre1-1 is X.Y.Z-R or X.Y.Z~preN-R (N, R >= 1)` |
| CHK-M10-319 | CODE | L | meta check on the tree | PASS | `PASS release.yml: refuses a changelog version holding "~"` and `PASS release.yml: the guard reads the changelog version` |
| plant: `0.2.0~rc1-1` (decisions row) | CODE | L | first entry rewritten | PASS (red) | 80/81, the version check red |
| plant: `0.2.0~pre0-1` (decisions row) | CODE | L | first entry rewritten | PASS (red) | 80/81 |
| plants: `0.2.0~pre1`, `0.2.0~pre1-0`, `0.2.0~1-1`, `0.2.0~pre1a-1` | CODE | L | first entry rewritten | PASS (red ×4) | 80/81 each |
| plant: release.yml's `~` refusal removed (decisions row) | CODE | L | `*"~"*)` arm deleted | PASS (red) | `FAIL release.yml: refuses a changelog version holding "~"` |
| plant: release.yml's `~` arm made harmless (`true` in place of `exit 1`) | CODE | L | arm edited | PASS (red) | the same check red |
| controls | CODE | L | `0.2.0-1`, `0.2.0~pre12-3` | PASS (green) | 81/81 each |
| CHK-M10-315f VM runbook walk (REQ-258 (1)) | APP | VM | — | **NOT RUN** | VM hold: the user's named gate exception (decisions 2026-11-01 (1)); it must run before any M11 code or release. Cover: CHK-M10-315c and d, plus the TASK-226 and TASK-228 WSL rows that ran the same commands and saw the same lines |
