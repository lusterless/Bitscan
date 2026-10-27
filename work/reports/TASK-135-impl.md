# TASK-135 IMPL: release workflow

Implementer: impl-deploy. REQ-141 (1)–(3), (5); (4) is TASK-136. Plan: `work/plans/TASK-135.md`. Spec: TS §3.1 L165, L177; §8.1 L1258; §8.2 L1267. Answers: #90 (versions 0.1.0 / 0.1.0-1, tag `v0.1.0`), #91 (draft GitHub release, `SHA256SUMS` in the notes), PD-31 (helpers inline, no new folder).

## Files

| File | Change |
| --- | --- |
| `.github/workflows/release.yml` | **New** (about 330 lines of YAML, most of it the job and step scaffolding the plan names). No other file changed. `build-deb.sh` and the units are unchanged. |

## Triggers and jobs (plan §2)

Top level:
- **Triggers:** a `push` of a `v*` tag, or `workflow_dispatch` with input `version`.
- **Settings:** `permissions: contents: read`, `concurrency` per version, `LC_ALL=C`, bash with `-eo pipefail`.

Jobs:
- **`versions`** (5 min): reads the tag (or `v<input>`) and requires the strict `^v[0-9]+\.[0-9]+\.[0-9]+$` pattern. It reads the `pyproject.toml` version with `tomllib` and the changelog version with `dpkg-parsechangelog -S Version`. It refuses, with one line naming the disagreeing pair: tag ≠ pyproject; a changelog version holding `~` (a pre-release); or a changelog upstream (`${deb%-*}`) ≠ tag. Outputs: `version`, `deb_version`.
- **`agent`** (a matrix of two, 30 min): `build-deb.sh` from clones at `src` and `rebuild/copy/src`. Go comes from `agent/go.mod`. It's the same as `package.yml`'s build.
- **`agent-compare`** (10 min):
  - Both outputs must hold exactly the five `build-deb.sh` files, and each file must `cmp` identical.
  - The three binaries are extracted with `dpkg-deb -x` and each compared with `cmp`.
  - It re-uploads `release-agent` with the `.deb` and the three `.cdx.json` files. The `.deb.sha256` is not released (plan §3).
- **`manager`** (20 min):
  - Node 24: `npm ci --ignore-scripts && npm run build`.
  - Python 3.12: a venv with `--require-hashes -r manager/requirements-dev.txt`, then `pip wheel --no-deps --no-build-isolation -w dist manager`.
  - `dist` must hold exactly `bitscan_manager-<v>-py3-none-any.whl`.
  - A `python -I` zip check: `bitscan_manager/webui/index.html` and at least one file under `webui/assets/`.
  - `check_units_verbatim.py manager`: the same call `units.yml` makes, so the released units are proven verbatim.
  - It copies the lock to `bitscan-manager-<v>-requirements.txt` and the four unit files.
- **`sums`** (10 min):
  - Downloads both artifacts into one folder, which must hold exactly the plan §3 list (without TASK-136's two SBOMs).
  - Writes `SHA256SUMS` over the sorted list, then checks that every file except `SHA256SUMS` is listed exactly once and nothing else is listed, then `sha256sum -c`.
  - Writes `notes.md`: one line on versions, the instruction to copy from the page and run `sha256sum -c --ignore-missing`, the runbook names, and `SHA256SUMS` in a code block.
- **`publish`** (10 min):
  - Runs only on a tag push (`github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`). This is the only job with `contents: write`.
  - Re-checks the listed/present set and runs `sha256sum -c` after the download.
  - Then `gh release create "$TAG" --draft --verify-tag --title "Bitscan <v>" --notes-file notes.md <files>`, `SHA256SUMS` included.
  - `GH_TOKEN` is `github.token`, used only here. No checkout.

Hardening:
- Every `uses:` is pinned by a 40-hex commit with the same versions as the other workflows. Every checkout has `persist-credentials: false`.
- Every `${{ }}` value reaches scripts only through `env:`. None sits inside `run:`, so the tag and the input can't inject shell.
- Every job has `timeout-minutes`.

## Checks run here

- **YAML parse and pins:** parsed with js-yaml from the main tree's `web/node_modules` (PyYAML and actionlint aren't installed here).
  - Top-level `contents: read`, and only `publish` has `contents: write`.
  - All `uses:` are pinned by 40-hex commits.
  - No `${{` inside any `run:`.
  - All 14 `run:` scripts pass `bash -n`.
  - One `gh release create` call, with `--draft`.
- **Version-agreement logic run locally** (bash; `dpkg-parsechangelog` emulated by reading line 1 of the changelog):

  | Tag | Changelog | Result |
  | --- | --- | --- |
  | `v0.1.0` | `0.1.0-1` | OK |
  | `v0.1.1` | `0.1.0-1` | refused, "tag and pyproject disagree" (pyproject is 0.1.0) |
  | `v0.1.0` | `0.1.0~pre1-1` | refused, pre-release |
  | `v0.1.0-rc1` | (any) | refused, pattern |
  | `v0.1.0` | `0.1.1-1` | refused, "tag and changelog disagree" |

- **The wheel UI check** on three synthetic zips: full UI → 0; no UI → 1; `index.html` without assets → 1.
- **Not run:** actionlint, the jobs themselves (needs Ubuntu 24.04), and the GitHub run and publication (REQ-141 (5): waits for a user tag push).

## Notes for the tester (TP-M6-06)

- **Plant CHK-M6-327** (tag/changelog): with `pyproject.toml` at 0.1.0, a `v0.1.1` tag is refused on the pyproject pair first. To see the changelog message, also set the pyproject version to 0.1.1 in the planted copy. Either way the job goes red before anything is built.
- **CHK-M6-330** (a file missing from `SHA256SUMS`): the exact-folder check before writing, the listed-vs-present check after writing, and the same check in `publish` each catch it. A file changed after `SHA256SUMS` is caught by `sha256sum -c` in `sums` and again in `publish`.
- **CHK-M6-331:** the wheel check fails with `wheel without the UI: …`.
- **CHK-M6-328 / 329:** a tag-pinned `uses:`, a missing `--draft`, or `contents: write` at workflow level. These are static checks for your `check_release_workflow.py`.
- **Running the build commands locally:** the `agent` job's commands are `build-deb.sh "$OUT"`. The `manager` job needs `npm ci` and `npm run build` first. The expected final folder is plan §3 without the two `bitscan-manager-<v>.*.cdx.json` files, which TASK-136 adds.
- **TASK-129 dependency:** the wheel name and the `webui/` contents come from TASK-129's `pyproject.toml`. I didn't edit that file.

## r1 (TEST FAIL from tester-m6b: TP-M6-06, CHK-M6-112)

Finding: `pip wheel … manager` (job `manager`, step "Build the wheel from the hashed dev lock") treated the bare `manager` as a requirement, not a path, and fetched the unrelated PyPI sdist `Manager-2.0.5`. With `--no-build-isolation`, a PyPI project of that name could run its build hooks in the release job.

Change (only `.github/workflows/release.yml`, one line, L216):

```text
"$RUNNER_TEMP/build/bin/python" -m pip wheel --no-deps --no-build-isolation --no-index -w "$RUNNER_TEMP/dist" ./manager
```

- `./manager` makes pip read the local folder. `--no-index` makes any download impossible.
- The build backend still resolves: `pyproject.toml` requires `hatchling`, which `manager/requirements-dev.txt` pins with hashes (`hatchling==1.32.4`). The line before installs that lock into the build venv, and `--no-build-isolation` uses it.
- **Every other pip call in the file:** there is one more, L215, `pip install --require-hashes -r manager/requirements-dev.txt`. It downloads, and it is hash-checked. The SBOM steps (TASK-136) run `python -I` with the standard library and `npm sbom` / `npm ls`, with no pip call. No other workflow was touched.

Checks run here (r1), js-yaml from the main tree's `web/node_modules`:
- YAML parses. Top level `contents: read`, and only `publish` has `contents: write`.
- Every `uses:` is pinned by a 40-hex commit. No `${{` in any `run:`.
- All 17 `run:` scripts pass `bash -n` (14 from r0 plus TASK-136's 3).
- Not run: the job itself (needs Ubuntu 24.04). The tester re-runs CHK-M6-112.
