# TASK-136 IMPL: manager SBOMs in the release workflow

Implementer: impl-deploy. REQ-141 (4). Plan: `work/plans/TASK-135.md` §3–§4. Spec: TS §3.1 L177 ("every release ships an SBOM"), §8.1 L1258. Answer: #92 (the manager SBOMs are in scope), PD-31 (helpers inline).

## Files

| File | Change |
| --- | --- |
| `.github/workflows/release.yml` | Three new steps in the `manager` job, after "Collect the manager release files": the Python SBOM, the web SBOM, and the completeness check. The `sums` job's expected file list gains `bitscan-manager-<v>.python.cdx.json` and `bitscan-manager-<v>.web.cdx.json`, so both are in `SHA256SUMS` and attached to the draft. No other file changed. |

## What the steps do

- **Python SBOM** (`python -I`, standard library only). It reads the released `bitscan-manager-<v>-requirements.txt`, joining continuation lines and skipping comments and option lines, and writes CycloneDX 1.5 JSON:
  - `metadata.component` is `bitscan-manager` `<v>` (`pkg:pypi/bitscan-manager@<v>`).
  - Each lock entry becomes one `library` component with `name`, `version`, `purl` `pkg:pypi/<normalised name>@<version>` (`bom-ref` = purl) and every `--hash=sha256:` as `{"alg": "SHA-256", "content": …}`.
  - Entries with environment markers (`tzdata ; sys_platform == 'win32'`, for example) are listed too: "every package of `requirements.txt`".
  - Components are sorted, JSON uses `sort_keys` and `indent=2`, and `serialNumber` is `urn:uuid:` + uuid5 of the lock's SHA-256. Two runs give the same bytes.
  - It refuses an unexpected lock line (no `==`, or no hash).
- **Web SBOM:** `npm sbom --sbom-format cyclonedx --package-lock-only` in `web/`, using the pinned Node 24's npm, unmodified.
- **Completeness check** (`python -I`). It parses the inputs independently of the generator: a line regex over the lock, and `npm ls --omit=dev --all --json` of the installed tree (`npm ci` ran earlier in the job). It fails, naming each gap:
  - a lock `name==version` missing from the Python SBOM;
  - a lock package whose SHA-256 set differs from its component's;
  - an installed runtime package (with its version) that isn't a `scope: required` component of the web SBOM;
  - either list being empty.

## Deviation from the plan's exact command (lead ruling 2026-10-26: accepted; keep the full npm SBOM and the `required` check, no filter)

Plan §4 says `npm sbom … --omit dev --package-lock-only`. Run on the M6 `web/` lock with npm 11.19.1 / Node v24.22.0, that SBOM holds only `openapi-fetch`, `openapi-typescript-helpers` and `qrcode-generator`. It **drops `react`, `react-dom` and `scheduler`**, although the lock doesn't mark them `dev` (no `dev`, `peer` or `devOptional` flag). They are also peers of dev packages. REQ-141 (4) names React and React DOM explicitly. The completeness check caught it.

Without `--omit dev`, npm lists all 236 lock packages. Exactly the six bundled runtime packages have `scope: "required"`: openapi-fetch 0.17.0, openapi-typescript-helpers 0.1.0, qrcode-generator 2.0.4, react 19.3.1, react-dom 19.3.1 and scheduler 0.28.0. The 230 build and test tools have `scope: "optional"`, which in CycloneDX means not needed at runtime.

So the step drops `--omit dev`, and the check requires every runtime package as a `required` component. The file stays npm's own output, with no post-filter. The cost is that the web SBOM also lists the build tools, each marked `optional`. A comment in the workflow explains this. If the lead wants a runtime-only file, a filter to `scope == "required"` is a few lines more.

## Checks run here

- **The real generator and check,** extracted from the parsed YAML (js-yaml) and run locally on the M6 inputs. The run used `npm ls --package-lock-only` because the M6 tree has no `node_modules`. CI uses the installed tree.
  - Clean run: rc 0, "python: 34 lock packages; web: 6 runtime packages".
  - The generator twice: byte-identical.
- **Plants, all rc 1:**

  | Plant | Message |
  | --- | --- |
  | `alembic` removed from the Python SBOM | `python sbom lacks alembic==1.20.0` |
  | one hash removed | `python sbom hashes differ for alembic==1.20.0` |
  | `react` removed from the web SBOM | `web sbom lacks react@19.3.1 as a required component` |
  | `qrcode-generator` re-scoped `optional` | `web sbom lacks qrcode-generator@2.0.4 as a required component` |

- **Whole-workflow sweep:**
  - Top-level `contents: read`, and only `publish` has `contents: write`.
  - Every `uses:` is pinned by a 40-hex commit.
  - No `${{` inside any `run:`.
  - All 17 `run:` scripts pass `bash -n`.
- **Not run:** actionlint, and the jobs on Ubuntu 24.04.

## Notes for the tester (TP-M6-06, CHK-M6-332)

- To plant CHK-M6-332, drop a component in the generator (or from the written file) before the check step. The check names the package.
- The expected release folder is now the full plan §3 list: the earlier ten files plus the two `bitscan-manager-<v>.{python,web}.cdx.json` files.
- `npm ls` in the check runs on the installed tree. In a local run without `node_modules`, add `--package-lock-only`, as I did.
