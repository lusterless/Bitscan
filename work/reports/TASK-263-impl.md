# TASK-263 IMPL: release notes and packaging text for 0.2.0

Implementer: impl-deploy-rel. Branch `release-0.2.0`, worktree `Bitscan-m11`. Not committed.

Spec: TS §3.1, §8.2 L1272, §8.7 L1353 (manager supports its own version and the one before), TS §8.5 (CIS control numbers). Decisions 2026-11-11 (2) (#111: ship with the note, samples not in the `.deb` or the manager release) and the last 2026-11-11 row (user: 0.2.0 ships BIT102 revision 1; the r2 gaps are accepted risks listed in the release notes).

**Departure from the task row's acceptance text (work/tasks.md L2819):** the row says "the changelog and README say the BIT102 r2 rules are in". The user's later ruling (decisions 2026-11-11, last row; relayed by `main`) supersedes it: r2 is **not** in 0.2.0. The changelog and README instead say BIT102 is the safety net, the runner sandbox is the real control, and name the forms the importer does not check in this release. The tester should test against the ruling, not the row.

## Files changed (the five owned files plus `manager-install.md`, the lead's sixth file)

| File | Change |
| --- | --- |
| `deploy/debian/changelog` | New top entry `bitscan-agent (0.2.0-1) unstable; urgency=medium`, trailer `Bitdeer-Security <kaiquan.koh@bitdeer.com>  Wed, 11 Nov 2026 00:00:00 +0000` (after the `0.2.0~pre2-1` entry of Sun, 08 Nov 2026). Bullets: release 0.2.0 with manager 0.2.0 (scans, results, retention); runner sandbox, redaction on the host, spool, inventory as before; manager scans (host, tag, fleet; by hand or schedule), results and score, CSV, re-evaluation, retention; **known limit** (BIT102 is a safety net, the runner sandbox is the real control; not checked in this release: `-c` strings of su/runuser/flock, `trap`, brace expansion in `bash -c` scripts, and the wrappers time, nsenter, unshare, flock, setpriv, taskset, chrt, runuser and su); supported with managers 0.2.0 and 0.1.0 (0.1.0 has no scans, so sends no compliance job); upgrades 0.1.0-1, 0.2.0~pre1-1 and 0.2.0~pre2-1 in place keeping config, token and agent id. Older entries unchanged (the diff removes no line). |
| `deploy/debian/control` | Synopsis: "(pre-release)" removed. Extended part: "In the 0.x pre-releases the runner and the helper are idle." replaced by "The runner returns the output of each check redacted on the host, and the helper stays off until an administrator enables it on the host." No other field changed. |
| `README.md` | **Status** paragraph: release 0.2.0 (manager `0.2.0`, agent `0.2.0-1`, tag `v0.2.0`), what it adds to 0.1.0, 0.1.0 summary; `0.1.0~preN-1` and `0.2.0~preN-1` not supported, upgrade to `0.2.0-1`. "Compliance scans and results" heading: "(release 0.2.0)", "Hosts on agent `0.2.0-1`". **Release files**: 0.2.0 file names (the same set `release.yml` publishes). **Versions and compatibility**: example `0.2.0-1`; manager 0.2.0 supports agents 0.2.0-1 and 0.1.0-1, agent 0.2.0-1 supports managers 0.2.0 and 0.1.0; 0.1.0-1 hosts report `runner_unavailable`; `X.Y.Z~preN-1` not supported by any manager. **Policies**: one new paragraph on `bits/samples/` (not in the agent package or the manager release; CIS control numbers not yet confirmed against the benchmark, TS §8.5). **What an import does**: one new bullet "Known limit of this release" naming the same unchecked BIT102 forms, with the runner sandbox as the control. README has no "Known limits" section, so the bullet sits with the existing BIT102 bullets. |
| `deploy/runbooks/agent-install.md` | Intro: the `0.2.0~pre2-1` pre-release note replaced by **Release 0.2.0** (package `0.2.0-1`, tag `v0.2.0`), then **Release 0.1.0** in the past tense; pre-release builds `0.1.0~preN-1` and `0.2.0~preN-1` not supported. §2: example package `bitscan-agent_0.2.0-1_amd64.deb`. §6 **Compatibility**: the 0.2.0 matrix, 0.1.0-1 hosts' `runner_unavailable`, manager 0.1.0 sends no compliance job, `X.Y.Z~preN-1` not supported by any manager, upgrade to `0.2.0-1`. §6 upgrade text: a `0.1.0-1`, `0.2.0~pre1-1` or `0.2.0~pre2-1` host upgrades to `0.2.0-1` in place. |
| `deploy/runbooks/manager-operations.md` | §1 **Compatibility**: names release 0.2.0 (manager `0.2.0`, agent `0.2.0-1`, tag `v0.2.0`) and the matrix; new bullet "Manager 0.1.0 has no scans, so it sends a `0.2.0-1` agent no compliance job"; the pre-release bullet keeps "not supported by any manager" and now points to `0.2.0-1` (agent-install section 6). §4: removed "0.1.0 holds no policies, so this doesn't apply to it yet." (wrong for 0.2.0) and named the rebuild command. §7 and §8 unchanged. |

| `deploy/runbooks/manager-install.md` (**sixth file, added by the lead's ruling**, docs only) | §2 L163 "(for 0.1.0)" → "(for 0.2.0)"; L165–L166 file names → `bitscan_manager-0.2.0-py3-none-any.whl`, `bitscan-manager-0.2.0-requirements.txt`; §6 block L411–L412 → the 0.2.0 requirements file and wheel; L420 offline `pip download` → `bitscan-manager-0.2.0-requirements.txt`. No other `0.1.0` remains in the file (none was upgrade-from text). |

Not changed on purpose:
- manager-operations §1 step 2 keeps the example wheel version `0.1.1`: `e2e/m6/ops_upgrade.py` L123 walks that block and substitutes `0.1.1` → `0.1.0`.
- No code block in any of the three Markdown files was edited (the e2e walks read them by anchor).

## Checks run

| Check | Result |
| --- | --- |
| `python -I deploy/tests/check_debian_meta.py` (Windows) | **OK 83/83**, including "first line format (0.2.0-1)", "weekday Wed matches 2026-11-11", "5 trailer dates strictly decrease", "Description synopsis 1..80" |
| `python -I deploy/tests/check_runbook_text.py deploy/runbooks/agent-install.md deploy/runbooks/manager-operations.md README.md` | FAIL, 2 findings: `agent-install.md:79` and `:123`, the `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN` placeholders. **Pre-existing:** the same 2 findings on the HEAD copies of the three files (checked from `git show HEAD:`). This is the known M6 placeholder follow-up (tasks.md L2610); not caused by this task. |
| `python -I deploy/tests/check_md_links.py README.md deploy/runbooks/*.md` | **OK**, 42 relative links, 0 findings (includes the new `bits/samples/` link) |
| `python3 -I deploy/tests/check_release_workflow.py` (WSL Ubuntu-24.04; the Windows venv has no `yaml`) | **17/17 passed** |
| WSL Ubuntu-24.04 `dpkg-parsechangelog -l deploy/debian/changelog` | `Version: 0.2.0-1`, `Date: Wed, 11 Nov 2026 00:00:00 +0000`, the new entry as Changes; `-S Version` prints `0.2.0-1` |
| `check_runbook_text.py deploy/runbooks/manager-install.md` | **OK**, 31 sh blocks, 0 findings |
| `check_md_links.py` after the manager-install change | **OK**, 42 links, 0 findings |
| `check_runbook_bootstrap.py` | FAIL `TS line 1016 is not the **Bootstrap** paragraph`. **Pre-existing, not from this task:** the owner-approved TS §5.2 index commit `68d3881` moved the paragraph to TS L1021 (5 lines down); the checker pins `SPEC_START`. The Bootstrap block in the runbook is untouched. Tester re-pin. |
| lintian on the built `bitscan-agent_0.2.0-1_amd64.deb` (G37) | NOT RUN: no `.deb` built locally and lintian is not installed in WSL. CI `package.yml` runs it. |

## For the tester

- No checker in `deploy/tests/` pins the old pre-release text (grep of `deploy/tests/` for `pre2`, `not a supported release`, `(pre-release)`, `idle`: none). `check_debian_meta.py`'s VERSION_RE still allows `~preN` (it guards the shape, the release workflow refuses `~`); nothing to re-pin there.
- Pins to look at outside `deploy/tests/` (none edited): `e2e/m6/ops_upgrade.py` (manager-operations §1 step 2 block, unchanged); `e2e/m11/compat.py` L216 (reads manager-operations §1 blocks by anchor, code blocks unchanged); `e2e/runbook_walk.py` (agent-install section 1, unchanged); `manager/tests/test_readme_*walk_linux.py` (README code blocks, unchanged). If any of them asserts the old prose, it is yours to re-pin.
- Check rows: no task id, REQ id or `#111` in the five files (grep clean). The BIT102 list matches the user ruling and the r1 code in `main` (`bit102.py` WRAPPERS: env, command, builtin, nice, nohup, ionice, setsid, stdbuf, timeout, chroot, sudo, doas, busybox; CODE_WORDS without `trap`).
- The samples are not in the `.deb` (`deploy/debian/bitscan-agent.install` lists only the three binaries and the D-Bus policy) or in the release files list of `release.yml`.

## e2e impact of the manager-install.md change (tester-owned, likely blocks the release-PR e2e run)

`e2e/m6/manager_walk.py` runs the §6 block `B["venv"]` (anchor `python3.12 -m venv /opt/bitscan-manager`) **verbatim** (L593, `sub()` replaces only `mgr.example`). `e2e/m11/nightly.py` L244 calls that walk with `--tree` = this tree and `--rel` = the release folder:
- **nightly and compat-a** install the wheel built from this commit, which TASK-262 makes `bitscan_manager-0.2.0-…`, so they need the 0.2.0 names (before this change the 0.1.0 block would have failed there).
- **compat-b** (manager 0.1.0) uses `rel010` (the v0.1.0 files) with **this tree's** runbook, so its §6 step now runs `pip install -r bitscan-manager-0.2.0-requirements.txt` against 0.1.0 files and will fail (CHK-M6-048, then CHK-M11-295).
- The §2 `sha256sum -c` step does not depend on names (it counts six `OK` lines).

So the walk needs to take the version from the `--rel` wheel name (or substitute it in `B["venv"]`) for the N−1 runs. That is the tester's file; I changed nothing in `e2e/`.

## For main

- Resolved: the tree is back to BIT102 r1 (lead, 2026-11-11), which matches the release text.

## Round 2 (tester-rel2 FAILs CHK-R020-034 and CHK-R020-036; lead fix list)

- **CHK-R020-034 (#111, changelog half):** new bullet in the changelog's top entry: "The sample policies in bits/samples/ are not part of this package or the manager release. Their CIS control numbers are not yet confirmed against the CIS benchmark." I left out a "TS §8.5" cite because the changelog doesn't cite the spec anywhere. The README sentence (Policies) keeps its "(TS §8.5)".
- **CHK-R020-036 (BIT102 known limit):** the changelog bullet and the README "Known limit of this release" bullet now also name:
  - long options given as abbreviations to the wrappers BIT102 does check (example `sudo --us`);
  - the output files that `time -o`/`--output` and `flock` open;
  - a non-literal command word, such as one taken from a variable (README example `c=rm; "$c" x`). This is the 2026-10-27 accepted residual.

  Both bullets keep "the runner sandbox is the real control". Each item was checked against the r1 code now in the tree (`bit102.py` SHA-256 `279291cf…`):
  - `_resolve` matches wrapper options by exact name only;
  - `time` and `flock` are not in `WRAPPERS`;
  - a non-literal command word is allowed (module docstring L9, L297).
- **Not changed:** the `~pre` upgrade-path mentions (changelog "Upgrades 0.1.0-1 and the 0.2.0~pre1-1 and 0.2.0~pre2-1 pre-releases…", agent-install L178). They stay on hold until main rules on them.
- **Re-run after round 2:**
  - `check_debian_meta.py`: 83/83 OK;
  - `check_md_links.py`: OK, 42 links;
  - `check_runbook_text.py README.md`: 0 findings;
  - WSL `dpkg-parsechangelog -S Version`: `0.2.0-1`;
  - no changelog line in the top entry is over 80 characters.

## Lead rulings after round 2 (2026-11-11)

- Leaving "(TS §8.5)" out of the changelog is accepted; the README keeps it.
- The `~pre` upgrade-path mentions stay as they are: the changelog top entry ("Upgrades 0.1.0-1 and the 0.2.0~pre1-1 and 0.2.0~pre2-1 pre-releases…") and `agent-install.md` L178. They are the remedy the unsupported-pre-release rule points to. No change.
