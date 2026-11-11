# TASK-253 IMPL: manager-operations runbook and changelog `0.2.0~pre2-1`

Implementer: impl-deploy, 2026-11-08. REQ-289, REQ-290. Spec: TS §5.3 L1049, L1051, L1053 (retention, roles, checkpoints), §8.7 L1348–L1350 (upgrade order, N and N−1), §8.2 L1269 (agent supports manager N and N−1), §3.1 (release files, sums). Open items: PD-50 (a), #150, #151 (user answer (2): known v1 limit), #153; the user's "N / N−1 both ways" (decisions 2026-11-08). Written against `work/reports/TASK-245-impl.md` and the code of `services/retention/task.py`, `rules.py`, `scheduler/runner.py`, `cli/serve.py`.

## Files

- `deploy/debian/changelog` (+16): new top entry `bitscan-agent (0.2.0~pre2-1) unstable; urgency=medium`, "Pre-release: results and end to end. Not a supported release.", dated `Sun, 08 Nov 2026 00:00:00 +0000` (after `Fri, 30 Oct 2026`; weekday checked). It names the two package changes made after the `0.2.0~pre1-1` entry was written (both already in main; `git log eec76a3..HEAD -- agent/ deploy/systemd`): the runner unit's `ReadOnlyPaths=/dev/shm` and `NoExecPaths=/ /tmp /var/tmp` (86f33a6), and the runner's busy and failed-cleanup fix (9f64887); and the in-place upgrade from `0.1.0-1` and `0.2.0~pre1-1`. The manager stays `0.1.0` (`pyproject.toml` and `__init__.py` untouched).
- `deploy/runbooks/manager-operations.md` (+83 / −5):
  - Title adds "retention, releases".
  - §1 **Order** line: hosts one agent version behind keep working during the rollout.
  - §1 **Compatibility** rewritten: both directions (TS §8.7, §8.2); the 0.1.0-1 agent's compliance checks are ERROR `runner_unavailable` and its score `n/a` (#153 (b), #74, #28); agents more than one version behind are unsupported, with a `psql` block (database host) listing agent versions; pre-release builds unsupported. The new block is the **fourth** sh block in §1, after the three existing ones, so the harnesses that index or anchor §1 blocks (`e2e/m6/ops_walk.sh` `blk 0..2`, `e2e/m6/ops_upgrade.py` `b1[0..2]`, `e2e/m11/compat.py` anchors) see the same blocks; checked with the `ops_walk.sh` regex (blocks 0–2 unchanged) and the new block holds none of compat.py's three anchors.
  - New §6 **Retention**: the table of what goes when (#150 (a)–(f)); what is never deleted; partitions by the maintain timer; when it runs (10 min after start, then the `retention` row's interval read at start-up, no overlap, stop at the next batch); the `bitscan_retention` role and `retention.dsn`; batches and the 5-minute statement limit; the known slow-delete limit (#151 answer (2)); audit checkpoints with a `psql` block to list them; the journal command and one example `retention step done` line in the real `JsonFormatter` shape; what each `skipped` value (`null`, `clock_doubt`, `future_rows`, `failed`) and the runner's `scheduler run failed` / `"job": "retention"` line mean and what to do.
  - New §7 **Release checklist** (PD-50 (a)): open carry-overs (the deferred BIT102 review and the CIS control numbers, as decisions 2026-11-08 "listed for the release checklist"); the release PR bumps the changelog to `0.2.0-1` and the manager to `0.2.0` in `pyproject.toml` and `__init__.py`; run `e2e.yml` by hand on that branch (nightly chain plus N / N−1 rows, all PASS); `release.yml` dispatch with `0.2.0` (versions agree, reproducible agent build, sums, no release); merge; the release owner tags and pushes `v0.2.0`; check and publish the draft.
  - §2 to §5 unchanged, so the M6 harnesses that read §4 and §5 by position are unaffected (new blocks come after §5's).

## How to check

- `python -I deploy/tests/check_runbook_text.py deploy/runbooks/manager-operations.md` → `OK 1 files, 24 sh blocks, 0 findings` (run here, Windows, venv Python, Git Bash `bash -n`).
- `python -I deploy/tests/check_debian_meta.py --root .` → `OK 82/82 checks passed` (was 81: one more trailer weekday row). CHK-M10-318 and -319 rows green: version matches `X.Y.Z~preN-R`, dates strictly decrease, `release.yml` still refuses `~`.
- `dpkg-parsechangelog -l deploy/debian/changelog -S Version` → expect `0.2.0~pre2-1` (not run here: no dpkg on Windows; WSL is the tester's). Also worth: `dpkg --compare-versions 0.2.0~pre1-1 lt 0.2.0~pre2-1` and `0.2.0~pre2-1 lt 0.2.0-1`.
- `check_md_links.py` reports "0 relative links … nothing was checked" (the runbook names files in backticks, as before this task; unchanged behaviour).

## For the runbook walk (TP-M11-16)

- §6 log command: `journalctl -u bitscan-manager --since yesterday -o cat | grep -E '"message": "retention |"job": "retention"'`. A first run happens 10 minutes after `serve` starts, so the walk needs a manager up for over 10 minutes (or a clock-controlled run). Expect seven `retention step done` lines per run, in step order.
- §6 checkpoint query: rows only after an audit delete; on a young database it returns none (expected).
- §1 agent-version query: the `agent.agent_version` column (TS §5.2 L718) holds the package version the agent reports.
- §7 is a checklist for the release owner; its commands (`gh workflow run`, `git tag`, `git push`) must not be run by the walk (no tag, no release in M11). The walk can check that it names `0.2.0-1`, `0.2.0`, the nightly and N / N−1 re-run, and the tag as the owner's step, and no secret.
- No secret, token, DSN or process note in either file (the checker above; `deleted`/`chunks` example values are invented counts).

## Not changed, for the lead

- `deploy/runbooks/agent-install.md` L7 and L178 still name `0.2.0~pre1-1` as the current pre-release, and `README.md` L16 already says `0.2.0~pre2-1`. Outside this task's two files; a one-line follow-up in agent-install.md (impl-deploy) if the lead wants them to agree.

## Builder checklist

| Item | How it is met |
| --- | --- |
| 11, 12 | no token, DSN or row content in the runbook; the example log line carries counts only |
| 15 | no `pip` command added |
| 16 | no new status check after a `systemctl start` (the §1 loop is unchanged) |
| 17 | no CLI sign-in with a secret added |
| 1–10, 13, 14, 18–22 | don't apply (docs and changelog only) |
