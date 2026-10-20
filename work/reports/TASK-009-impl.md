# TASK-009 IMPL report: CI workflows for manager gates, web gates and the OpenAPI regeneration diff

Implementer: impl-deploy. REQs: REQ-017, REQ-002, REQ-005, REQ-007, REQ-015. Spec: TS §8.2 (ruff, mypy --strict, `pip --require-hashes`, TypeScript strict, ESLint, Prettier, OpenAPI client regenerated with no diff), TS §8.3 (85 % coverage on services; Integration through Testcontainers), TS §8.1 (hashed dependencies). M0 gate rows G1 to G6 and G11 to G16. There is no plan file for this task.

## Files (2 new, LF, 137 lines including blank lines after round 2)

- `.github/workflows/manager.yml` (63 lines): one job, `gates`, on `ubuntu-24.04`, with setup-python 3.12. The steps:
  1. **G4, runtime lock:** a fresh venv in `$RUNNER_TEMP/runtime`, then `pip install --require-hashes -r manager/requirements.txt`.
  2. **G4, dev lock:** a fresh venv in `$RUNNER_TEMP/dev`, then `pip install --require-hashes -r manager/requirements-dev.txt`, then `pip install --no-deps --no-build-isolation -e manager`. The venv's `bin` goes onto `$GITHUB_PATH`.
     - Both locks are used exactly as committed, so the `--only-binary :all:` line inside each lock applies. No flag is added or removed.
  3. **G1:** `ruff check manager`
  4. **G2:** `ruff format --check manager`
  5. **G3:** `mypy --strict --config-file manager/pyproject.toml manager`
  6. **G5:** from `manager/`, `pytest --cov=bitscan_manager/services --cov-fail-under=85`. The step sets `CI: "true"` explicitly, although GitHub already sets it, so a missing Docker fails the run. It also sets `RYUK_CONTAINER_IMAGE` to the pinned digest (see below). The pg tests use the Docker on the Ubuntu runner.
  7. **G6:** `python -m bitscan_manager.app manager/openapi.json`, then `git diff --exit-code -- manager/openapi.json`.
- `.github/workflows/web.yml` (74 lines): one job, `gates`, on `ubuntu-24.04`, with setup-node `24` (Active LTS; `engines` is `>=24 <25`; `package-manager-cache: false`) and setup-python 3.12. The steps, all from `web/` unless noted:
  1. **G11:** `npm ci --ignore-scripts`
  2. **G12:** `npm run lint`
  3. **G13:** `npm run typecheck`
  4. **G14:** `npm run format:check`
  5. **G15:** `npm test`
  6. **G16:** in this order, as the TASK-006 review asked:
     - from the root, the runtime lock with `--require-hashes` in a fresh venv;
     - the export, with `PYTHONPATH=manager` (`"$RUNNER_TEMP/runtime/bin/python" -m bitscan_manager.app manager/openapi.json`);
     - `npm run gen:api`;
     - from the root, `git diff --exit-code -- manager/openapi.json web/src/api/`.
- Both workflows:
  - run on `pull_request` and on `push` to `main`, with no path filters;
  - set `permissions: contents: read` only, `defaults.run.shell: bash` and checkout `persist-credentials: false`;
  - use the same action pins as TASK-010, plus `actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0` (the newest tag; lightweight, verified with `git ls-remote`; its `action.yml` has `node-version` and `package-manager-cache` and runs on `node24`);
  - contain no secrets, no `|| true`, no `continue-on-error`, no `set +e` and no `if:`.

### Choice for the reviewer

The web job's export installs only the **runtime** lock and runs with `PYTHONPATH=manager`. It does not install the dev lock and build the package. The export needs only the runtime dependencies, and this avoids building the package in the web job. The manager job does the full dev-lock and `-e manager` install, as `main` specified.

## Ryuk pinned by digest (verified read-only)

testcontainers 4.15.0 reads `RYUK_CONTAINER_IMAGE` (`testcontainers/core/config.py:105`, default `testcontainers/ryuk:0.8.1`).

How I verified the digest:
- I took an anonymous pull token from `auth.docker.io`; this is not a login.
- `HEAD https://registry-1.docker.io/v2/testcontainers/ryuk/manifests/0.8.1` returned `200`, `Content-Type: application/vnd.docker.distribution.manifest.list.v2+json` and `docker-content-digest: sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e`.
- A `GET` of the same manifest list hashes with `sha256sum` to the same value.
- The list includes `linux/amd64` and `linux/arm64`.

The workflow sets `RYUK_CONTAINER_IMAGE: testcontainers/ryuk:0.8.1@sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e`, the form the TASK-003 review asked for.
- NOT RUN locally (no Docker): whether docker-py and the daemon pull `name:tag@digest` correctly.
- If the first PR run fails at Ryuk start-up, the fallback is the tag-less form `testcontainers/ryuk@sha256:<same digest>`. Do not disable Ryuk.

## Local validation (Windows 11, Git Bash; Python 3.12.10, Node 24.22.0, npm 11.19.1)

- **actionlint** v1.7.12, built into a throwaway `GOPATH`: 0 errors across all four workflows. shellcheck is not available.
- **Step harness:** scratch scripts in a temp dir, not committed. They extract every `run:` block with its `working-directory` and step `env` and run it under `bash --noprofile --norc -eo pipefail -c`, as Actions does. They use a throwaway copy of `manager/`, `web/` and `.gitattributes`, with `git init` and `git add -A` (index only; no commit), so `git diff --exit-code` compares against the "committed" state.
  - Windows adaptations: venv `bin/` becomes `Scripts/`, and `$GITHUB_PATH` is emulated.
  - A planted change that a PR would commit (G16) is `git add`ed in the copy before the run.
- **Clean copy, manager.yml:**
  - All 7 steps were GREEN, with the pytest step's `CI` overridden to `false`, because there is no local Docker.
  - With `CI=true` as written, the pytest step is RED, with `not run: Docker unavailable and CI=true: PostgreSQL tests must run`. That is the intended behaviour; on the runner Docker exists.
- **Clean copy, web.yml:** all 9 steps GREEN.

### manager.yml plants (each in the copy, restored afterwards)

| Gate | Plant | Red step |
| --- | --- | --- |
| G1 | `import os` unused in `bitscan_manager/plant.py` | ruff check |
| G1 | `import xml.etree.ElementTree` in `bitscan_manager/` | ruff check |
| G1 | `cur.execute(f"SELECT ... '{name}'")` | ruff check |
| G2 | `VALUE = { "a":1 }` | ruff format --check |
| G3 | unannotated `def helper(x)` in `bitscan_manager/` | mypy (`no-untyped-def`) |
| G3 | the same in `manager/tests/test_plant.py` | mypy |
| G4 | first hash of `annotated-doc` altered in `requirements.txt` (fresh venv) | runtime-lock step (`THESE PACKAGES DO NOT MATCH THE HASHES`) |
| G4 | unpinned `six` appended to `requirements.txt` | runtime-lock step (`all requirements must have their versions pinned with ==`) |
| G4 | first hash altered in `requirements-dev.txt` | dev-lock step |
| G5 | untested 25-statement `services/planted.py` (CI=false copy, no Docker) | pytest (`Required test coverage of 85% not reached. Total coverage: 0.00%`) |
| G6 | `title="Bitscan planted"` in `create_app()` without re-export | OpenAPI export step (diff shows the title) |

In each plant run the other gate steps stayed green, except the pytest step: as written (`CI=true`, no local Docker) it is red in every run.

### web.yml plants

| Gate | Plant | Red step | All other steps |
| --- | --- | --- | --- |
| G11 | `"left-pad": "1.3.0"` added to `package.json`, lock unchanged | npm ci | green (existing `node_modules`) |
| G12 | unused `const unused = 1` | lint (`no-unused-vars`) | green |
| G12 | `<p dangerouslySetInnerHTML={{ __html: "x" }} />` in `main.tsx` | lint ("Render API data as plain text (TS §6.3)") | green |
| G12 | `localStorage.setItem` | lint ("Keep the session token in memory only") | green |
| G12 | `fetch("/api/v1/agents")` in `src/plant.ts` | lint ("Call the API only through the generated client") | green |
| G13 | `export const n: number = "x"` | typecheck (TS2322) | green |
| G13 | `function f(a)` | typecheck (TS7006 implicit any) | green |
| G14 | `export const   x = {a:1}` | format:check | green |
| G15 | `expect(1).toBe(2)` in `src/plant.test.ts` | npm test | green |
| G16 | hand edit appended to `schema.d.ts`, staged | final `git diff` (regeneration removes it) | green |
| G16 | route `/api/v1/planted` added to `create_app()`, `openapi.json` re-exported and staged, client not regenerated | final `git diff` (new `paths` in `schema.d.ts`) | green |
| G16 | `/api/v1/x` added to the staged `openapi.json` only | final `git diff` (export restores `"paths": {}`) | green |

## Round 2 (reviewer CHANGES_REQUESTED, `work/reviews/TASK-009.md`: a deleted committed file passes the diff gates)

**Cause:** if a PR deletes `manager/openapi.json` or a file in `web/src/api/`, the export or `gen:api` recreates it as an untracked file, and `git diff --exit-code` ignores untracked files.

**Fix:** after each `git diff --exit-code`, the step now also runs `changed="$(git status --porcelain -- <paths>)"` and fails, printing the list, if that is non-empty.
- `manager.yml` (G6) checks `manager/openapi.json`.
- `web.yml` (G16) checks `manager/openapi.json` and `web/src/api/`. Its step became a block scalar.
- The `git diff` stays first, so a content change still prints the diff.

**Proof:** the two step scripts were extracted from the workflows with `awk` and run under `bash -eo pipefail` in a scratch git repo in a temp dir. That repo is unrelated to the project, and its throwaway commits were made with a per-command identity (`-c user.name=…`), because porcelain needs a `HEAD` to compare against. The repo was deleted afterwards.

| Case | Result |
| --- | --- |
| clean (files committed, unchanged) | manager step exit 0; web step exit 0 |
| committed deletion of `manager/openapi.json`, file present untracked | plain `git diff --exit-code` exit 0 (the gap); manager step exit 1 (`?? manager/openapi.json`); web step exit 1 |
| committed deletion of `web/src/api/schema.d.ts`, file present untracked | web step exit 1 (`?? web/src/api/schema.d.ts`) |
| content change to `manager/openapi.json` | manager step exit 1, diff printed by `git diff` |

## For the tester

- **NOT RUN locally:**
  - the live PR runs (CHK-M0-136, -137 live);
  - the pg tests with Docker;
  - `git diff` against real commits;
  - the Ryuk digest pull.
- The `CI=true` pytest step is red locally by design, because there is no Docker. To prove G5 locally, run the step with `CI` unset or `false`.
- G16 plants must be staged (`git add`) or committed in the copy. An unstaged hand edit of `schema.d.ts` is overwritten by `gen:api` and then matches the index, so the gate would wrongly pass.
