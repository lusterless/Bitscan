# TASK-130 IMPL: agent 0.1.0-1 changelog entry and agent runbook

Implementer: impl-deploy. REQ-142 (also feeds REQ-146, REQ-148, REQ-149). Answers used: #90 (0.1.0 is the first supported release; package `0.1.0-1`), #28 and #74 (compliance answered `runner_unavailable`), #91 (`SHA256SUMS` in the release notes on the release page), the N / N−1 marker recommendation (no earlier supported version yet), decisions 2026-10-20 (pre-release builds are not N−1). File names come from `work/plans/TASK-135.md` §3.

## Files changed

| File | In the task's list | Change |
| --- | --- | --- |
| `deploy/debian/changelog` | yes | New top entry `bitscan-agent (0.1.0-1) unstable; urgency=medium`, dated `Mon, 26 Oct 2026 00:00:00 +0000` (later than the `0.1.0~pre1-1` entry, so `SOURCE_DATE_EPOCH` moves forward and lintian's new-date rule holds). The `0.1.0~pre1-1` entry stays below it unchanged. Lines are 80 characters or fewer, ASCII, LF. |
| `deploy/runbooks/agent-install.md` | yes | (1) The "0.x is a pre-release" note becomes the 0.1.0 status: enrolment, heartbeat, job pull and mandatory inventory are supported; compliance is not in 0.1.0, the runner and helper are idle, no check command runs, every check of a compliance job is reported as `runner_unavailable`; pre-release builds are not supported. (2) Section 2: the per-file `.deb.sha256` is replaced by `SHA256SUMS`, copied as text from the release page's notes (not the `SHA256SUMS` asset on the download host), checked with `sha256sum -c --ignore-missing SHA256SUMS`. (3) Section 6: upgrade order (manager first: migrate, restart, pointing to `manager-operations.md`, then agents), the compatibility rule (manager N serves agents N and N−1, TS §8.7 L1348; agent N supports manager N and N−1, TS §8.2 L1267; no earlier supported version exists yet; pre-release hosts must upgrade), the in-place upgrade from `0.1.0~pre1-1`, and a result check (`dpkg-query -W` version, `bitscan-agent started` line with the version). |
| `deploy/debian/bitscan-agent.lintian-overrides` | **no (outside the task's list, same area)** | Removed the `initial-upload-closes-no-bugs` override and its comment. Lintian emits that tag only when the changelog has exactly one entry with Debian revision 1. With two entries it no longer fires, so the override would be reported as `unused-override`. Both `deploy/tests/test_build_deb.sh lintian` and `package.yml` `lintian` fail on an unused override. |

No code, unit, maintainer script or `build-deb.sh` change. `build-deb.sh` already takes the version and the timestamp from the changelog (`dpkg-parsechangelog -S Version` / `-S Timestamp`) and injects the version with `-X main.version=$VERSION`, so the `.deb` is `bitscan-agent_0.1.0-1_amd64.deb`, and the agent's `bitscan-agent started` line logs `version` `0.1.0-1`.

## Checks run here (Windows, Git Bash)

- No shell or YAML changed, so `sh -n` / YAML parse don't apply. `dpkg-parsechangelog` and lintian aren't available on Windows, and WSL isn't mine to use.
- Day names: `date -d 2026-10-26` = Mon, `2026-10-24` = Sat. Changelog: no line over 80 characters, no CR, ASCII.
- Read-only run of `python -I deploy/tests/check_debian_meta.py --root .`: 74/75. The only failure is the expected `changelog: version 0.1.0-1 matches 0.x.y~preN-R` (see below).
- Builder checklist: items 1–14 concern manager routes, SQL, logs and Go code, and none applies to these files. Item 11/12 spirit: the runbook holds no real secret, task id or process note (the placeholder `bse_REPLACE_…` lines are unchanged).

## What the tester must know

1. **`deploy/tests/check_debian_meta.py` needs a tester change (tester-owned, I didn't edit it).** `VERSION_RE = r"^0\.\d+\.\d+~pre\d+-\d+$"` (line 56) and the docstring (lines 5, 19) still expect a pre-release. With 0.1.0-1 the check goes red by design. Per #90, plan TASK-135 §6 and REQ-142 (3), the expected first entry is now `0.1.0-1`: a release with no `~`, sorting above `0.1.0~pre1-1`.
2. **Lintian override removal needs lintian to confirm.** Run `deploy/tests/test_build_deb.sh lintian`, and expect no `initial-upload-closes-no-bugs` and no unused or mismatched override. If your lintian still emits the tag, the fix is to restore the removed three lines, and I'll do that. Also watch for any new changelog tag at the pedantic level (I expect none: new version, later date, correct day name, same maintainer).
3. **G38 upgrade:** `0.1.0~pre1-1` → `0.1.0-1` needs a pre1 `.deb`. Build it from the changelog at `HEAD` (`git show HEAD:deploy/debian/changelog`), or with the existing `repack` helper's approach. `dpkg --compare-versions 0.1.0~pre1-1 lt 0.1.0-1` must be true.
4. **G39:** the changelog date moved, so `SOURCE_DATE_EPOCH` is now 1792972800 (2026-10-26 00:00:00 UTC). Both builds use it, so reproducibility is unaffected.
5. **Runbook walk (TP-M6-10):** section 2 relies on GNU `sha256sum --ignore-missing` failing with "no file was verified" when the `.deb` isn't among the listed names (coreutils 8.32 on 22.04, 9.4 on 24.04). Section 6's pointer to `manager-operations.md` names the TASK-134 file, which doesn't exist until TASK-134 lands. The `bitscan-agent started` line appears only once the host is enrolled (it's logged after enrolment completes).
6. `deploy/tests/test_debconf.sh` lines 259 and 264 use `0.1.0~pre1-1` as the prior version passed to the scripts. That's still a valid older version and needs no change.
