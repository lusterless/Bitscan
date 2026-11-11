# TASK-253 REVIEW: manager-operations runbook and changelog `0.2.0~pre2-1`

Reviewer: reviewer-m11, 2026-11-09. Round 1. Low risk (docs), one approval.

Verdict: APPROVED

**Scope reviewed:** `deploy/runbooks/manager-operations.md` (+83 / −5) and `deploy/debian/changelog` (+16).

**Checked against:**
- TS §5.3 L1049, L1051, L1053; §8.7 L1348–L1350; §8.2 L1269; §3.1.
- REQ-289, REQ-290.
- PD-50 (a), #150, #151 (answer (2)), #153.
- Decisions 2026-11-08: N / N−1 both ways, and the carry-overs listed for the release checklist.

**Reports:** `work/reports/TASK-253-impl.md` and `work/reports/TASK-253-test.md`, which points to `TASK-252-test.md`. The test passed: `dpkg-parsechangelog` gives `0.2.0~pre2-1`, `check_debian_meta.py` is 82/82, §1 and §6 were walked against a real `serve`, and `check_runbook_text.py` is clean.

## Checks

- **Changelog (PD-50 (a), REQ-290 (1)):**
  - The new top entry is `0.2.0~pre2-1 unstable`, marked as a pre-release and not supported.
  - Its date is after the entry below it, with the maintainer line as in every earlier entry.
  - The two package changes it lists match decisions 2026-11-03 (1) and (2) and the runner fix.
  - The manager stays at `0.1.0`.
  - `release.yml` still refuses `~` (CHK-M10-319 green).
- **§1 Compatibility:**
  - It states both directions, as the user decided on 2026-11-08 (TS §8.7 L1350, §8.2 L1269).
  - The 0.1.0-1 agent shows ERROR `runner_unavailable` and `n/a` (#153 (b)).
  - An agent more than one version behind is unsupported. It is listed with a read-only `psql` query on the database host, with no secret.
  - The new shell block comes after §1's three existing blocks, so the harness indexes are unchanged.
- **§6 Retention:**
  - The table matches #150 and `services/retention/rules.py`.
  - The never-deleted list protects inventory (G2).
  - Partitions are dropped by `db maintain`, which uses the same 400 days (`db/maintain.py`).
  - Timing: first run at start + 10 minutes, then the `retention` row interval, with no overlap.
  - It covers the `bitscan_retention` role and `retention.dsn`, batches and the 5-minute statement limit.
  - The #151 slow-delete limit is stated as a known limit, which also covers my TASK-245 nit for operators.
  - It covers the checkpoints. The log example has the real `JsonFormatter` keys and only invented counts.
  - Each `skipped` value has an operator action. The text says there is no setting or command to turn retention off, which is correct.
- **§7 Release checklist (PD-50 (a)):**
  - Carry-overs first: BIT102 and the CIS control numbers.
  - Then the version bump to `0.2.0-1` and manager `0.2.0` in a release PR, the e2e run with the N / N−1 rows on that branch, a `release.yml` dispatch, the merge, and the tag as the release owner's step.
  - It names no secret, and its commands are marked as the owner's steps.
- **No secret or process note:** `check_runbook_text.py` reports `OK 24 sh blocks, 0 findings`. No DSN, token or password appears.

## Findings

None.
