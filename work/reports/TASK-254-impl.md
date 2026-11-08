# TASK-254 IMPL: nightly end-to-end workflow `.github/workflows/e2e.yml`

Implementer: impl-deploy, 2026-11-08. REQ-285, REQ-286, REQ-287, REQ-288. Spec: TS §8.3 L1283 ("End-to-end (nightly, 3 VMs)"), §8.7 L1350 and §8.2 L1269 (N / N−1 both ways). Open items: #152, #153, PD-49; decisions 2026-11-08 (N / N−1 both ways; standing approval for the local-VM fallback); the lead's yes to the `[e2e]` push trigger (2026-11-08, conditions (1)–(5) below). Inputs: `work/plans/TASK-254-inputs.md` (tester-m11e), `e2e/m11/README.md`, `nightly.py` and `compat.py` argument parsers. Medium risk; the lead's second look (PD-47).

## File

- `.github/workflows/e2e.yml` (new, 242 lines, about 60 of them comments; over the 150 estimate because the report copy-out from the root-only work folder and the gate step are separate `if: always()` steps). No other file.

## What it does

- **Triggers:** `schedule` (`40 1 * * *`, nightly, UTC), `workflow_dispatch`, and `push` to any branch (tags excluded), where the jobs run **only** when the head commit message holds `[e2e]` (the `build` job's `if`; `e2e` needs `build`, so it is skipped with it). Any other push creates a run with every job skipped. The comment says why (pre-merge acceptance and throwaway-branch plants; schedule and dispatch need the file on the default branch), as `sandbox.yml` does for `[sandbox-plants]`.
- **Permissions:** `contents: read` at the workflow level; no job sets `permissions`. Every checkout has `persist-credentials: false`. `GH_TOKEN: ${{ github.token }}` is set on one step only (the v0.1.0 download). No secret is used. Nothing commits, tags, publishes or creates a release.
- **Actions pinned by SHA**, the same SHAs as `release.yml` / `package.yml` / `sandbox.yml`: checkout v7.0.1, setup-go v7.0.0, setup-node v7.1.0, setup-python v7.0.0, upload-artifact v7.0.2, download-artifact v8.0.2.
- **`build` job** (ubuntu-24.04): `bash deploy/debian/build-deb.sh "$RUNNER_TEMP/deb"` (the `.deb` with its `.sha256` beside it, input 3); `npm ci --ignore-scripts && npm run build` in `web/`; the wheel exactly as `release.yml` (hashed dev lock, `pip wheel --no-deps --no-build-isolation --no-index ./manager`), checked to carry `bitscan_manager/webui/index.html`; the REL folder (input 4): the wheel, `bitscan-manager-<v>-requirements.txt` (from `manager/requirements.txt`, `<v>` from `pyproject.toml`), the four manager units, exactly 6 files, then `SHA256SUMS` of them. Artifacts `e2e-deb`, `e2e-rel`.
- **`e2e` job**, matrix `run: [nightly, compat-a, compat-b]`, `fail-fast: false`, each on its own ubuntu-24.04 runner (parallel; each harness run boots its own manager container and guests), 75 min timeout:
  1. downloads both artifacts;
  2. `apt-get install qemu-system-x86 qemu-utils cloud-image-utils` (input 1), prints `ls -l /dev/kvm`;
  3. `docker build -t m6b-mgrhost -f e2e/m6/manager-host.Dockerfile` with an empty `extra-ca/` context (input 2);
  4. `sudo bash e2e/m11/guests.sh fetch "$RUNNER_TEMP/img"` (input 5);
  5. compat runs only: `gh release download v0.1.0 --dir "$RUNNER_TEMP/v010"` into a new empty folder and `gh release view v0.1.0 --json body -q .body > v010-notes.txt` (input 6; checked: v0.1.0 is a published, not draft, release with the 13 expected assets);
  6. runs the harness as root with the system `python3` (input 7): nightly `nightly.py --tree --rel --deb --images --work W --log W.log > W.log 2>&1`; compat `compat.py --phase a|b --tree --rel --deb-n --v010 --v010-sums --images --work W --log W.log > W.log 2>&1`. Paths are passed as `sh -c` positional arguments, never interpolated, and no `${{ }}` expression appears inside any `run:` script. `W.log` is created 0600 root first and is never printed or uploaded;
  7. `if: always()`: copies only `W/report.json` and `W/report.md` out of the root-only (0700) work folder, appends `report.md` to the step summary (or "no report");
  8. `if: always()`: uploads them as `e2e-report-nightly`, `e2e-report-compat-a`, `e2e-report-compat-b` (input 8);
  9. `if: always()`: the gate, red when `report.json` is missing, else `python3 -I e2e/m11/nightly.py --check-report report.json` (exit 1 on a FAIL row or a missing expected row, REQ-286). It runs whatever the harness exit code was, so a planted report the harness itself accepts still turns the job red.
- `--phase upgrade` is not run nightly (#153 (d): at the gate only); the header comment says so.
- **No KVM / local-VM fallback:** a runner without `/dev/kvm` makes the pre-check row FAIL and the run red (never a silent skip). The standing-approval fallback (local `bitscan-u2204` / `bitscan-u2404`, one VM at a time from `clean`, no token or `install.env` printed or saved) is documented in the header comment as **manual only**; the workflow has no path to the user's machine. The comment also notes that `e2e/m11/guests.sh` drives QEMU guests only, so that fallback would need a Hyper-V form of the guest script (tester-owned) before it can run.

## How to check

- Parsed with `js-yaml` (from `web/node_modules`): triggers, `permissions: {contents: read}`, two jobs, no job-level `permissions`, every `uses:` pinned to a 40-hex SHA; every `run:` script passes `bash -n`.
- Not run here: `actionlint` (not installed on this box; REQ-286 (3) says NOT RUN with the reason where unavailable), and no hosted run (the lead pushes the `[e2e]` commit).
- Acceptance (TP-M11-20): a push whose head commit message holds `[e2e]` on m11-results runs both jobs; the three `e2e` jobs green with every row PASS; then on a throwaway branch a planted FAIL row (CHK-M11-373) and a removed expected row (CHK-M11-374) must each turn the gate step red. A normal push (no `[e2e]`) must show every job skipped.

## For tester-m11e

- Report artifact names: `e2e-report-<run>`; each holds `report.json` and `report.md` only.
- The gate step is named "Every expected row present, none FAIL"; the harness step "Run the harness (<run>)".
- Memory: each runner runs one harness (nightly needs 1200 + 2 × 1024 MB available; compat 1200 + 1024).
- The harness runs from `$GITHUB_WORKSPACE` as root via `sudo` (secure_path, so `/usr/bin/python3`, Python 3.12 on ubuntu-24.04), and `GUESTS_DIR` is the harness's default under the work folder.

## r1 (tester-m11e nit, not a FAIL)

- "Collect the manager release folder": the count-mismatch message now prints its header once (`printf '%s\n' "want 6 release files, got:" "${files[@]}"`); before, printf repeated the header before every file. No other change.

## Builder checklist

| Item | How it is met |
| --- | --- |
| 11 | no token or secret printed: the run log is root-only and never printed or uploaded; only the masked, swept report goes to the summary and artifacts; `github.token` (auto-masked) only in the download step's env |
| 12 | no client input in any message |
| 15 | `pip install --require-hashes -r …`, `pip wheel … --no-index ./manager` |
| 16 | no readiness check after a `systemctl start` in the workflow (the harness has its own) |
| 1–10, 13, 14, 17–22 | don't apply |
