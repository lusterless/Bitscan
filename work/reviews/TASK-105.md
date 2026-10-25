# TASK-105 REVIEW: package CI (`package.yml`) and lintian overrides

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (CI and packaging metadata, speed rule 6). Not on the two-approval list.

Scope reviewed (`work/reports/TASK-105-impl.md`, including fix rounds 1 and 2):
- `.github/workflows/package.yml` (new);
- `deploy/debian/bitscan-agent.lintian-overrides` (new, approved by the lead);
- the one-entry `DEBIAN_FILES` addition in `build-deb.sh`.

Sources:
- TS §3.1 ("must pass `lintian`", reproducible builds, SBOM, SHA-256), §3.7 and §8.3;
- REQ-106, REQ-109, REQ-111;
- PD-27;
- decisions 2026-10-24 (lead ruling (A); amd64 and Ubuntu only) and 2026-10-25 (the D-Bus lintian findings are overridden with a reason; the policy stays verbatim).

TEST: PASS on local evidence (`work/reports/TASK-105-test.md`).
- actionlint is clean.
- `systemd-analyze verify` on the packaged units passes on systemd 249 and 255.
- lintian 2.117 on 24.04 reports no error or warning, and every override is used and has a reason.
- Plants L1–L3 are red.
- The GitHub run is NOT RUN until the branch is pushed. Debian 12 is NOT RUN (dropped by the user).

## Checks
1. Spec and decisions:
   - Seven jobs: the verbatim units and D-Bus policy, metadata, a double build at two paths, reproducibility, lintian, package checks, packaged units on 22.04 and 24.04, and install tests on 22.04 and 24.04.
   - The reproducibility job checks equal SHA-256 for every artifact, `sha256sum -c`, and that every tar member is clamped to the changelog date.
   - No arm64 job, no Debian job, no signing step and no APT repository.
2. Overrides:
   - Every override has a reason.
   - The six D-Bus lines follow the 2026-10-25 ruling, and the policy text itself is untouched (still byte-identical in `sources`).
   - `uses-dpkg-database-directly` is justified: the agent only watches the directory, and the list comes from `dpkg-query`.
   - CI fails on an unused or mismatched override, so the list cannot go stale silently.
   - lintian runs only on 24.04. 2.114 on 22.04 cannot parse the same override file, and the reason is recorded.
3. Supply chain and permissions:
   - `contents: read`, and `persist-credentials: false` on every checkout.
   - Every action is pinned by commit.
   - `setup-go` has `cache: false`.
   - Packages come only from the runner's signed Ubuntu archive.
   - Every job has a timeout.
   - `sudo` is used only for apt, the unit install and the disposable install test.
4. Scope: 240 lines in one workflow file. The lead accepted that as one task (decisions 2026-10-24).

## Findings
1. nit, `package.yml`, `build` job. The two builds run on the same runner image label. The two VMs give fresh environments, but they do not differ in image or toolchain, which is acceptable for G39. Optional, at the M4 gate: record each build job's `$ImageVersion` in the reproducibility job's output (the build job already prints it), so a differing image is visible when the hashes differ.
