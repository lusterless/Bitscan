# TASK-135 TEST: release workflow (TP-M6-06, G49)

Verdict: **PASS** (r1). Round 0: FAIL. Tester: tester-m6b. REQ-141 (1)–(3), (5). The local runs execute every `run:` script of release.yml **verbatim**, extracted by `check_release_workflow.py --extract`, with `bash --noprofile --norc -eo pipefail`, the step's `env:` values, RUNNER_TEMP and GITHUB_OUTPUT. They run in an Ubuntu 24.04 build container (m4b-build-u24 + python3.12-venv; Go 1.27.2 from agent/go.mod). The two agent builds use separate clones (src, rebuild/copy/src) and separate Go caches. Environment notes:
- `npm ci && npm run build` and the two npm outputs (`npm sbom …`, `npm ls …`) were run with Node v24.22.0 / npm 11.19.1 on Windows, the same major versions the workflow pins. An `npm` shim serves those outputs to the steps and refuses any other arguments.
- `gh` is a shim that records its arguments.

Written by `main` from the tester's text (the harness blocks the tester on report files).

Commands and totals:
- `actionlint v1.7.7 -shellcheck=shellcheck` (shellcheck 0.9.0) on r1: clean, rc 0. Control plant (`timeout-minute`) red (CHK-M6-110).
- `check_release_workflow.py` r1: 17/17. On r0 it is 16/17: the new pip-target check is red (CHK-M6-111).
- `release_local.sh` r0: FAIL (CHK-M6-112). The `manager` job's wheel step `pip wheel … -w "$RUNNER_TEMP/dist" manager` printed `Collecting manager` / `Using cached Manager-2.0.5.tar.gz` and failed with `No module named 'setuptools'`, rc 2: pip resolved the bare name on PyPI. `./manager` or an absolute path builds our wheel.
- `release_local.sh` r1 (L216 `--no-index … ./manager`): **22/22 PASS**, 0 failed (CHK-M6-112-r1).
- `release_checks.sh` r1: **34/34 PASS** (8 version cases, 5 wheel cases, 7 SHA256SUMS cases, 5 SBOM cases, 9 plants). Two test bugs in the CHK-M6-332 case were fixed first; that case is re-run as its own row.
- CHK-M6-118: the GitHub run and publication are NOT RUN (no push authorised).

Acceptance criteria:
- (1) actionlint clean, every `uses:` pinned by commit, only publish has `contents: write`, `--draft`: PASS (CHK-M6-110, -111; plants -328, -329 red).
- (2) the build commands produce exactly the plan's files; `sha256sum -c` passes and lists every file; the two `.deb` builds are identical: PASS at r1 (CHK-M6-112-r1).
- (3) plants red: PASS. A v0.1.1 tag / pyproject / changelog mismatch is refused (-113), and the version checks removed go red (-327). A wheel without the UI is refused (-114), and the UI check neutered goes red (-331). A changed file after SHA256SUMS, a missing file and an extra file are each refused (-115, -330). A tag-pinned action goes red (-328). The bare-`manager` form goes red (-112p).
- (5): NOT RUN (push).

Failure in round 0 (fixed in r1): expected the job to build the checked-out `manager/` with no unhashed download. Actual: pip fetched PyPI `Manager-2.0.5`. A supply-chain risk too: with `--no-build-isolation`, a hostile `manager` sdist's build hooks would run in the release job. r1 adds `--no-index` and `./manager`, and the new static check guards every pip call.
