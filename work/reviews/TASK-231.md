# TASK-231 REVIEW: runbook, README and changelog for the compliance runner

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-258, REQ-255 (the version); PD-42. Low risk (docs), one approval.

Scope reviewed, per `work/reports/TASK-231-impl.md`, +112 / −2 lines:
- `deploy/runbooks/agent-install.md`: §1 cgroup v2 prerequisite, §4 and §6 lines, new §9–§11;
- `README.md`: the compliance paragraph;
- `deploy/debian/changelog`: the `0.2.0~pre1-1` entry.

I also checked the tester's rewrite of `deploy/tests/check_debian_meta.py`, as the brief asks.

TEST: PASS (`work/reports/TASK-231-test.md`).
- Doc checks: 33/33.
- Meta check: 81/81.
- 8/8 meta plants red, plus 2 green controls.
- Links OK.
- Units verbatim OK.
- The VM runbook walk is NOT RUN (VM hold).

Spec read: TS §3 L152; §3.1; §3.3 L224–L226; §3.6; §3.7 L276–L285, L484, L501, L503; §4.4 L575, L578; decisions rows "PD-42 against `check_debian_meta.py`" and "User decisions before the M10 merge" (1).

## Checks
1. **No secret and no process note.**
   - The added lines hold no token-shaped text, password or internal id (`TASK-`, `REQ-`, `PD-`, `M10`, `#n`) and no team-role words.
   - The README says "in a later version", not a milestone name.
   - The only example values are `https://mgr.example:8443`-style placeholders that already existed.
   - The tester's grep agrees (CHK-M10-315b).
2. **Quoted lines match the code.** I checked each one against the source myself:

   | Quoted line | Source |
   | --- | --- |
   | `bitscan-runner started` | `cmd/bitscan-runner/main.go` |
   | `the runner is unavailable; plugins without a result are reported runner_unavailable` and `runner_unavailable: <reason>` | `compliance.go:63-64` |
   | The reason words `connect`, `timeout`, `broken`, `protocol`, `refused_<reason>` | `runnerclient/client.go` |
   | `start-up refused` and the four `runner: refusing to start: …` texts | `hygiene_linux.go:61-84` |
   | `bitscan-capread: not enabled` and `not_installed` | `client.go`, `serve_linux.go` |
   | `agent.yaml: spool_max_mb: must be 1 to 50` | `config.go:205` |
   | `spool full: …` | `overflow.go` |
   | `spooled results dropped at start` and the `last_error` texts | `cmd/bitscan-agent/main.go` |
   | `job refused; not run` and `job refused: no compliance handler` | `pull.go:155-156`, `jobs.go:34` |
   | The manager's `agent last_error` and `runner_helper_changed` | `services/agents/heartbeat.py:94, 115` |

   The claims also hold:
   - **"Stopping the socket also stops the helper"** is true. `bitscan-capread.service` has `Requires=bitscan-capread.socket`, so an explicit stop of the socket stops the service. `RemoveOnStop=yes` removes the file.
   - **"The manager fails it 24 hours after it was handed out"** matches TS §4.4 L575 (a dispatched job that never starts fails 24 h after dispatch).
   - **"Kept for 7 days … the manager refuses them after that"** matches L578 (`dispatched_at` + 7 days).
   - **The `findmnt --task 1` advice** matches TS §3.7 L501.
3. **Version** (PD-42). `dpkg-parsechangelog` gives `0.2.0~pre1-1`. It sorts above `0.1.0-1` and below `0.2.0-1`, which matches the runbook's upgrade line. The trailer date is a Friday and lies after the previous entry's date.
4. **The `check_debian_meta.py` rewrite does not lower the release gate.**
   - CHK-M6-100 is replaced by CHK-M10-318. `VERSION_RE` now allows only `X.Y.Z-R` or `X.Y.Z~preN-R` with N ≥ 1 and R ≥ 1. Any other `~` form stays red: `~rc1`, `~pre0`, a bare `~1`, `~pre1a`, no revision and `-0` are all planted red.
   - The protection #90 actually gave (a pre-release is never published) lives in `release.yml:77` (`*"~"*) … exit 1 ;;`). That file is unchanged.
   - The new CHK-M10-319 pins that guard and that it reads the `dpkg-parsechangelog` version. Plants that delete the arm or make it harmless (`true`) are red.
   - The tag rule at `release.yml:65` (`^v[0-9]+\.[0-9]+\.[0-9]+$`) is untouched too.
   - So the release gate is unchanged and has gained a check; that is not a lowering. Every other assertion in the file is kept.
   - It uses Python `re` on repository files, which are trusted input, so the RE2 rule does not apply.

## NOT RUN rows and cover
- **The runbook walk on a sandbox VM** (REQ-258 (1), CHK-M10-315f): NOT RUN under the VM hold, now the named gate exception, which must run before any M11 code or release (decisions 2026-11-01 (1)).
- **Cover:**
  - every quoted string grepped in the source;
  - the new commands parsed;
  - the TASK-226 and TASK-228 WSL rows, which ran the same commands and showed the same lines: `bitscan-runner started`, `start-up refused`, the socket mode, `not enabled`.
- **Unproven on a real host:**
  - the §1 cgroup v1 symptom and its fix (a reboot);
  - §10's `runner_helpers` change in the next heartbeat;
  - §11's unopenable-spool walk on an installed `.deb`.

## Findings
None blocking or should-fix.

1. nit, `agent-install.md` §11: "a refused job never starts, so the manager fails it 24 hours after it was handed out" leaves out that M9 then makes its single retry (TS §4.4 L575). The retry is refused too while the spool stays broken. A half sentence would make the 48 h worst case clear.
