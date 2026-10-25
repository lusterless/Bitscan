# TASK-102 TEST: reproducible build, SBOM and SHA-256 (build-deb.sh)
**Verdict: PASS** (Ubuntu 24.04 build image m4b-build-u24: dpkg 1.22.6, debhelper 13.14.1). REQ-106, REQ-109; TS §3.1. Tester: tester-m4b. Standard rigor with one plant per criterion.

Commands: `test_build_deb.sh repro` (two builds at different absolute paths with separate caches), `contents static sbom sha256 flags` both with `--deb` (the CI path, 89/89 as non-root) and without it (single build, 89/89); plants R1–R8 on throwaway copies.

Criteria:
- Two builds give identical binaries, .deb and .sha256: PASS (CHK-M4-200; plants R1 `-trimpath` removed and R2 a timestamp in -X are red).
- The .deb holds exactly the REQ-106 files, modes and owners: PASS (CHK-M4-201; R4, R4b, R7 red).
- Static amd64 ELF only: PASS (CHK-M4-202; R3 red).
- The SBOM lists every `go version -m` module: PASS (CHK-M4-203; R5 red).
- `sha256sum -c`: PASS (CHK-M4-204; R6 red).
- Reproducible flags: PASS (CHK-M4-206).
- Latest build-deb.sh change (staged files 0644): PASS (R8 red).

Note (not a REQ-109 item): the SBOM bytes differ only in metadata.tools[].hashes, the hash of the cyclonedx-gomod binary built per run. Suggestion for impl-deploy: add `-trimpath` to that `go install`, so the SBOM bytes are stable as well.

Lintian (CHK-M4-205) belongs to TASK-105.

Revision 1: PASS. -trimpath on the SBOM tool install makes the SBOMs byte-reproducible; repro 14/14 with the new byte check (CHK-M4-200-r1). The earlier note about SBOM bytes is resolved.
