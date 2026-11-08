# TASK-254 REVIEW: nightly end-to-end workflow `.github/workflows/e2e.yml`

Reviewer: reviewer-m11, 2026-11-08. Round 1, on r1 (the file in the tree includes the printf fix). Second look: the lead's (PD-47).

Verdict: APPROVED, for the file as written, on static review and the local evidence.

**Scope reviewed:** `.github/workflows/e2e.yml` (new, 242 lines, the only file).

**Checked against:**
- TS §8.3 L1283, §8.7 L1350, §8.2 L1269.
- REQ-285 to REQ-288; #152, #153; PD-49.
- Decisions 2026-11-08: N / N−1 both ways; the local-VM standing approval; the `[e2e]` push trigger and its conditions (1)–(5).
- `.claude/rules/testing.md`, `.claude/rules/security-invariants.md`, builder checklist 11, 15, 16.

**Reports:** `work/reports/TASK-254-impl.md`; the local TP-M11-20 part of `work/reports/M11-e2e-test.md`. Every `run:` script was extracted and passes `bash -n`. Each step below was run as written with local stand-ins:
- the release-folder step: rc 0, and a 7th-file plant gives rc 1;
- the cloud-image fetch and the v0.1.0 download: 13 assets, sums OK;
- the row report and gate on a 19/19 report: rc 0;
- the FAIL-row, missing-row and no-`report.json` plants: each rc 1.

**Not covered by this approval:** the hosted acceptance run (REQ-286 (1)), the throwaway-branch plants CHK-M11-373 and -374 (NOT RUN, pending the user's OK to push those branches), and the "push without `[e2e]` skips everything" row. All three stay TEST rows. Any change to the file after the hosted run reopens this review.

## Checks

- **Triggers (decision row "TASK-254 … `[e2e]`"):**
  - `schedule` (nightly) and `workflow_dispatch` are present.
  - `push` covers every branch; tags are excluded because `branches:` is given. The `build` job runs on a push only when the head commit message contains `[e2e]`, and `e2e` needs `build`, so an ordinary push runs nothing.
  - The commit message is used only in an `if:` expression, never in a script.
  - A header comment explains the trigger.
- **Permissions and secrets (security invariants; checklist 11):**
  - `permissions: contents: read` at the workflow level, with no job override.
  - Every checkout uses `persist-credentials: false`.
  - The only credential is `github.token`, given to one step for `gh release download` / `gh release view` of v0.1.0, which are read-only. No secret is used.
  - Nothing commits, tags, publishes, uploads a release or signs.
  - The harness log stays 0600 root on the runner and is never printed or uploaded. Only `report.json` and `report.md` are uploaded; the harness masks and sweeps them (CHK-M11-303).
- **Script injection:** there is no `${{ }}` inside any `run:` script. Matrix and paths reach the scripts through `env` (`RUN`) or through `sh -c` positional arguments. `${{ }}` appears only in `name:`, `with:`, `env:`, `if:` and `concurrency`, and every value there is static or GitHub-controlled.
- **Pins:**
  - Every `uses:` is a 40-hex SHA.
  - The checkout, setup-go, setup-node and setup-python pins are the same as in the existing workflows.
  - The upload-artifact and download-artifact pins are the same as in `package.yml`, `release.yml` and `sandbox.yml`.
- **Builds (checklist 15):**
  - The wheel is built as in `release.yml`: `pip install --require-hashes -r manager/requirements-dev.txt`, then `pip wheel --no-deps --no-build-isolation --no-index … ./manager`, with the UI checked inside it.
  - `npm ci --ignore-scripts`.
  - The release folder is exactly the 6 files `manager-install.md` §2 checks, plus `SHA256SUMS`. A count mismatch is red, and its message prints its header once (r1).
- **Gate (REQ-286):**
  - "Row report" and the gate run under `if: always()`.
  - The gate is red when `report.json` is missing, and otherwise runs `nightly.py --check-report`, which exits 1 on a FAIL row or a missing expected row, whatever the harness exit code was.
  - If an earlier step fails, there is no report, so the gate is red.
- **N / N−1:** compat-a (manager N with agent 0.1.0) and compat-b (agent N with manager 0.1.0, built because the user answered the marker "yes") run nightly. The upgrade walk is left to the gate (#153 (d)), as the header says.
- **No silent skip:** without `/dev/kvm`, the pre-check row FAILs and the run is red. The approved Hyper-V fallback is documented as manual only. The workflow has no path to the owner's machine and changes no host setting.
- **Scope:** one file under `.github/workflows/`, owned by impl-deploy. There are no agent, unit, manager or migration changes.

## Findings

1. nit, `e2e.yml` line 39–40 (`push: branches: ["**"]`): every push to any branch creates an `e2e` run with all jobs skipped. This is accepted and documented, as for `sandbox.yml`. It can be narrowed after the merge if the noise matters. No change.
2. nit (evidence, not code): `actionlint` is NOT RUN locally because it is not installed, as REQ-286 (3) allows. If it is available on the hosted runner image, the first hosted run could record it.
