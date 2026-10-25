# TASK-092 REVIEW: D-Bus policy and package metadata

Reviewer: reviewer. Date: 2026-10-24. REQ-106. Spec: TS §3.1 L157–L161 (binaries, the five units, `dh_installsystemd` flags, the D-Bus policy path), §3.7 L410–L433 (the policy, verbatim). Decisions (`work/decisions.md`, 2026-10-24): M4 breakdown approved; PD-26 option (a) (debhelper compat 13, `0.1.0~preN-1`, staging tree from `build-deb.sh`); arm64 dropped from v1 (an owner deviation from TS §3.1, so amd64 only); package licence and maintainer (proprietary, `Bitdeer-Security <kaiquan.koh@bitdeer.com>`); packaging notes (a lintian override for `dbus-policy-in-etc` in TASK-105; `bitscan-runner.service` is not enabled but is started on install, as the spec's flags give). Plan: `work/plans/TASK-100.md`. Inputs:
- `work/reports/TASK-092-impl.md`;
- `work/reports/TASK-092-test.md` (PASS: CHK-M4-070 to -075; 59/59 metadata checks; 10/10 verbatim files; 28/28 plants red; `deploy/tests/check_units_verbatim.py` extended, `deploy/tests/check_debian_meta.py` new).

Files reviewed (M4 worktree, branch `m4-agent`):
- `deploy/dbus/bitscan-runner.conf`;
- `deploy/debian/control`, `rules`, `changelog`, `copyright`;
- the two test scripts.

Verdict: APPROVED

Not on the TS §8.2 two-approval list. Standard rigor, one review round.

## What was checked

- **D-Bus policy (TS §3.7).** My own byte comparison of `deploy/dbus/bitscan-runner.conf` against TS L413–L430, the lines between the ```` ```xml ```` fence at L412 and the closing fence at L431, normalised to LF, is identical. The policy is `<deny send_type="method_call"/>` for `bitscan-runner`, then only the read-only allows the deploy rule lists, so no state-changing systemd method is allowed. There is no XML declaration, because the spec block has none.
- **`dh_installsystemd` flags (TS §3.1 L159, acceptance (2)).** Three calls, each naming its units, so each unit gets exactly one flag set:
  - `bitscan-agent.service` and `bitscan-runner.socket`: defaults (enable, start, restart on upgrade), which is TS §3.1 postinst step 4;
  - `bitscan-runner.service`: `--no-enable`;
  - `bitscan-capread.socket` and `bitscan-capread.service`: `--no-enable --no-start`, so the helper stays off until a host admin enables it. No manager route can change that (security invariants).

  As the user's packaging note accepts, `bitscan-runner.service` is started on install even though it is not enabled; that is what the spec's flags give.
- **Units unchanged.** `execute_after_dh_install` copies the five units from the staging tree with `install -m 0644`, unedited, so the units stay byte-identical to TS §3.7, which `check_units_verbatim.py` checks.
- **`control`.** `debhelper-compat (= 13)`, `Rules-Requires-Root: no`, `Architecture: amd64` (user decision), `Depends: adduser, ${misc:Depends}` (`adduser` for the TASK-100 users; `${shlibs:Depends}` omitted because the binaries are static), and the maintainer per the user. The description claims nothing that M4 does not deliver: the runner and helper are idle in 0.x.
- **`changelog`.** `bitscan-agent (0.1.0~pre1-1) unstable; urgency=medium`, with a fixed RFC 2822 trailer, which gives a reproducible `SOURCE_DATE_EPOCH` (TS §3.1 L177, reproducible builds). `0.1.0~pre1` sorts below `0.1.0`.
- **`copyright`.** DEP-5 1.0. `Files: *` is proprietary, "All rights reserved", per the user. `go.yaml.in/yaml/v3` is Apache-2.0, pointing to `/usr/share/common-licenses/Apache-2.0`. The eight libyaml-ported files are under Expat with the full text, taken from the module's LICENSE and NOTICE.
- **Security invariants.** There is no signing and no signed APT repository (an owner decision), and nothing in the metadata enables `bitscan-capread`.
- **Scope.** Five files, as the task row lists.
- **Tests.** The verbatim check now covers the policy with the fence lines named. The new metadata check has 59 assertions over `control`, `rules`, `changelog` and `copyright`. 28 plants are red, among them changed flags, a reordered policy line, arm64 added and a changed maintainer. I did not re-run them: they are Python scripts in the M4 worktree, and the tester's run is the evidence. My own byte check of the policy is above.

## Findings

None block approval.

1. **nit (for TASK-102)**, `deploy/debian/rules`. The file is stored without the executable bit, because the Windows checkout has `core.fileMode=false`. `build-deb.sh` must `chmod 0755 debian/rules` in the staging tree, or `git update-index --chmod=+x deploy/debian/rules` must be committed. CI on Linux would otherwise rely on `dpkg-buildpackage`'s fallback with a warning. Recommend the `update-index` fix so the repository itself is right.

## Carry-overs

- **TASK-096.** `source/format` must be `3.0 (quilt)` (the version has a Debian revision). `${misc:Depends}` picks up `debconf` once `templates` exist.
- **TASK-105.** List each lintian override with its reason (REQ-106 (4)): `dbus-policy-in-etc` (TS §3.1 L161 fixes the path), and possibly `statically-linked-binary`, `no-manual-page`, `systemd-service-file-missing-install-key` for capread (no `[Install]` by spec) and `new-package-should-close-itp-bug`.
- **`.claude/rules/deploy/packaging-and-units.md`** still says "for amd64 and arm64" and "postrm purge removes `/etc/bitscan`". Both are superseded by the user's 2026-10-24 decisions (amd64 only; #82 purge). The `.claude/` writer should update them; `.claude/CLAUDE.md` "Supported hosts" also still lists arm64, as the decision row notes.
