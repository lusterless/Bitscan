# TASK-135 (and TASK-136): the release workflow

REQ-141. Answers used: #90 (versions), #91 (release page and download origin), #92 (manager SBOM), PD-31 (helpers inline). File: `.github/workflows/release.yml` (TASK-135 creates it; TASK-136 adds the manager SBOM step). The existing `deploy/debian/build-deb.sh` builds the `.deb`, its SBOMs and its SHA-256 and is not changed.

## 1. Spec quotes

- TS §3.1 L165: "Check the file with `sha256sum -c` against the SHA-256 on the release page, which is served from a different origin than the download."
- L177: "v1 ships the `.deb` file directly, with its SHA-256 published on the release page (a different origin from the download host). Builds are reproducible Go builds, and every release ships an SBOM. A signed APT repository is deferred (§1.2)."
- TS §8.1 L1258: "`.deb` published with its SHA-256 on a separate origin; … reproducible builds; SBOM per release; hashed Python dependencies."
- TS §8.2 L1267: "semantic versioning for agent and manager".

## 2. Jobs

| Job | Runs on | Does | Permissions |
| --- | --- | --- | --- |
| `versions` | ubuntu-24.04 | Reads the tag (`v<upstream>`, or the manual input), `manager/pyproject.toml` `version`, and `dpkg-parsechangelog -S Version` of `deploy/debian/changelog`. Requires: tag upstream = pyproject version = changelog upstream (the part before `-`), and the changelog version has no `~` (a release, not a pre-release). Fails with one line naming the disagreeing pair. | `contents: read` |
| `agent-a`, `agent-b` | ubuntu-24.04, clones at two different paths | `deploy/debian/build-deb.sh` (Go as `agent.yml` pins it) | `contents: read` |
| `agent-compare` | ubuntu-24.04 | `.deb` and the three binaries byte-identical between `agent-a` and `agent-b` (as `package.yml` does) | `contents: read` |
| `manager` | ubuntu-24.04 | Node as `web.yml` pins it: `npm ci --ignore-scripts && npm run build` in `web/`; Python 3.12: `pip install --require-hashes -r manager/requirements-dev.txt`, then `pip wheel --no-deps --no-build-isolation -w dist manager`; a `python -I` check that the wheel holds `bitscan_manager/webui/index.html` and at least one `webui/assets/` file; copies `manager/requirements.txt` to `bitscan-manager-<v>-requirements.txt` and the four manager unit files from `deploy/systemd/` unchanged. TASK-136 adds the SBOM step here (§4). | `contents: read` |
| `sums` | ubuntu-24.04 | Downloads every artifact into one folder, writes `SHA256SUMS` (`sha256sum` of every file, sorted by name), then checks that every file is listed exactly once and nothing else is, and that `sha256sum -c SHA256SUMS` passes. Writes `notes.md`: a short text plus `SHA256SUMS` in a code block. | `contents: read` |
| `publish` | ubuntu-24.04, **only on a tag push** | `gh release create <tag> --draft --title "Bitscan <v>" --notes-file notes.md <files>`. A manual run stops after `sums` (artifacts only). | `contents: write` (this job only) |

Top level: `permissions: contents: read`; `concurrency` per tag; every job has `timeout-minutes`; every `uses:` pinned by a 40-hex commit with the version in a comment, as the other workflows do.

## 3. Release files (0.1.0)

- `bitscan-agent_0.1.0-1_amd64.deb`
- `bitscan-agent_0.1.0-1_amd64.bitscan-agent.cdx.json`, `….bitscan-runner.cdx.json`, `….bitscan-capread.cdx.json` (the names `build-deb.sh` writes)
- `bitscan_manager-0.1.0-py3-none-any.whl`
- `bitscan-manager-0.1.0-requirements.txt`
- `bitscan-manager.service`, `bitscan-manager-migrate.service`, `bitscan-manager-maintain.service`, `bitscan-manager-maintain.timer`
- `bitscan-manager-0.1.0.python.cdx.json`, `bitscan-manager-0.1.0.web.cdx.json` (TASK-136)
- `SHA256SUMS` (also pasted into the release notes)

The `.deb.sha256` file `build-deb.sh` writes is not released; `SHA256SUMS` replaces it.

## 4. Manager SBOMs (TASK-136, #92)

- **Python:** a `python -I` step with the standard library only reads `bitscan-manager-<v>-requirements.txt` (`name==version` lines with their `--hash=sha256:` lines) and writes CycloneDX 1.5 JSON: `metadata.component` = `bitscan-manager` `<v>`; one `library` component per requirement with `name`, `version`, `purl` `pkg:pypi/<name>@<version>` and every listed hash as `{"alg": "SHA-256", "content": …}`. Output sorted, `serialNumber` derived from the lock's SHA-256 so two runs give the same bytes.
- **Web (bundled UI):** `npm sbom --sbom-format cyclonedx --omit dev --package-lock-only` in `web/` (npm ships with the pinned Node; no new tool).
- **Completeness check** in the same job: every requirement name is a component of the Python SBOM; every package that `npm ls --omit=dev --all --json` lists is a component of the web SBOM; otherwise the job fails naming the missing one.

No new dependency is added to either lock.

## 5. Plants the tester runs (TP-M6-06; mutation rows CHK-M6-327 to -332)

Tag/changelog/pyproject disagreement accepted; one action pinned by tag; no `--draft` or `contents: write` at workflow level; `SHA256SUMS` written before the last file; a wheel without `webui/index.html`; a requirement missing from the Python SBOM. The tester runs the jobs' shell steps locally in an Ubuntu 24.04 container on the M6 head (the GitHub run itself waits for a push the user makes).

## 6. Edge cases

- A tag on a commit whose changelog still says `0.1.0~pre1-1` must fail in `versions`, before anything is built.
- The `publish` job never runs on `pull_request` or a manual run.
- Nothing in the workflow prints a secret; `GITHUB_TOKEN` is used only by `gh` in `publish`.
- The workflow publishes nothing; the human publishes the draft after checking it (#91).
