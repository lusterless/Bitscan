# TASK-136 TEST: manager SBOMs in the release workflow (TP-M6-06, G49)

Verdict: **PASS**. Tester: tester-m6b. REQ-141 (4). Tested on release.yml r1, which holds both TASK-136's steps and TASK-135 r1. It is the same local run as TASK-135 (`e2e/m6/release_local.sh`, every step verbatim, Ubuntu 24.04 container). npm's outputs come from Node v24.22.0 / npm 11.19.1 on Windows, through a shim that refuses any other arguments.

Written by `main` from the tester's text (the harness blocks the tester on report files).

Commands and totals:
- `release_local.sh` r1: the "Python SBOM", "Web SBOM" and "Both SBOMs are complete" steps rc 0 (part of 22/22). Both SBOMs are in the release folder and in SHA256SUMS.
- `python3 -I deploy/tests/check_manager_sboms.py relout 0.1.0 tree`, an independent reader of the lock and package-lock: **OK, 0 findings**.
  - Python: 34 lock entries, 676 hashes, 34 components, each with its version, a pkg:pypi purl and exactly the lock's SHA-256 set; CycloneDX 1.5; metadata bitscan-manager 0.1.0.
  - Web: the runtime closure from package.json/package-lock is exactly openapi-fetch 0.17.0, openapi-typescript-helpers 0.1.0, qrcode-generator 2.0.4, react 19.3.1, react-dom 19.3.1 and scheduler 0.28.0, all `required` with those versions.
  - Both files are in SHA256SUMS with the right hash.
  - Plant (httpx dropped from the SBOM): red (`python sbom lacks httpx==0.28.1`, plus a hash mismatch).
- Determinism: the Python SBOM is byte-identical across two runs (2f234c34…544e). The web SBOM came from one npm run, served by the shim to both local runs, so its determinism is not tested (npm writes a random serialNumber and timestamp; reviewer nit). (Corrected by the tester after the review.)
- `release_checks.sh` SBOM cases: **5/5** (CHK-M6-117).
- Plant CHK-M6-332 (the generator drops the first lock package): the completeness step is red (`python sbom lacks alembic==1.20.0`). This is a re-run row: two test bugs (a missing `web/` work folder, and a `$?` read after the wrong command) were fixed first.

Acceptance criteria:
- Every requirements.txt package with its version and hash: PASS.
- Every bundled UI runtime package with its version: PASS.
- Both files in SHA256SUMS: PASS.
- A package dropped from either SBOM turns the completeness check red: PASS (CHK-M6-117, -332).
Note: the web SBOM also lists the 230 build and test tools as `optional`. That's the lead's accepted ruling (2026-10-26), not a finding.
