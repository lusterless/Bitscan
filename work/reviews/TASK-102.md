# TASK-102 REVIEW: `.deb` build script

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (packaging, speed rule 6). Not on the two-approval list.

Scope reviewed: `deploy/debian/build-deb.sh` (`work/reports/TASK-102-impl.md`): the first version, the changes before the TEST verdict, and Revision 1 (`-trimpath` on the SBOM tool install). Sources: TS §3.1 L177, §8.1, REQ-106, REQ-109, PD-26, and decisions 2026-10-24 (amd64 only; Ubuntu 22.04 and 24.04; no signing and no APT repository).

TEST: PASS (`work/reports/TASK-102-test.md`, CHK-M4-200..206).
- Two builds from clones at different paths give identical binaries, `.deb` and `.sha256`.
- The `.deb` contents, modes, static amd64 ELF, SBOM module list, `sha256sum -c` and the build flags all hold.
- Plants R1–R8 are red. R3, R4 and R7 were silent at first because of a bug in the tester's own test, which is now fixed.

## Checks
1. Spec:
   - The build is linux/amd64 only.
   - `-trimpath -buildvcs=false -ldflags "-s -w -buildid= -X main.version=…"`, with `CGO_ENABLED=0` and `GOAMD64=v1`.
   - `SOURCE_DATE_EPOCH` comes from the changelog, with `umask 022`, `LC_ALL=C` and `TZ=UTC`.
   - There is one CycloneDX SBOM per binary, built from the binary's own build info, plus a `sha256sum`-format file (REQ-109 (1), (3), (4)).
   - `-us -uc`: unsigned, as the owner decided (no signing).
2. Supply chain:
   - `go mod verify` runs before the build, and `GOFLAGS=-mod=readonly` is set.
   - The SBOM tool is pinned by version and by module checksum, and the checksum is compared before `go install`. `go install` also checks the checksum database.
3. Staging:
   - An explicit file list, so nothing stray is packaged. The manager units are never staged.
   - Fixed staged modes (0644, then 0755 on the four scripts), which closes the TASK-092 executable-bit carry-over.
   - The temporary directory is removed on exit.
4. Scope: 1 file, about 55 code lines.

## Findings
1. nit. r1 (`go install -trimpath` for the SBOM tool) was made after the TEST PASS. Its only effect is that the SBOM bytes become stable; the `.deb` and the binaries are unchanged. G39 does not require byte-identical SBOMs, so I do not hold approval for it. tester-m4b should confirm byte-identical SBOMs once, in the next `repro` run (the TASK-105 or M4 gate run). **Closed, 2026-10-25:** the r1 TEST passed (tester-m4b, `repro` 14/14) with a new hard check, and the three SBOMs, the `.deb` and the binaries are byte-identical between the two builds.
2. nit, `build-deb.sh:8`. The "Needs:" comment is one 140-character line. Wrap it.
