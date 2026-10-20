# TASK-010 REVIEW: CI workflows for agent gates and systemd units verify

Reviewer: reviewer. Date: 2026-10-20. REQ-017, REQ-010, REQ-011, REQ-012, REQ-016. Spec: TS §2.2 L111, §3.7, §8.1, §8.2 L1265/L1268, §8.3 L1280. Inputs: `work/plans/TASK-010.md`, `work/tasks.md` "Changes since approval" (2026-10-20 rows), `work/reports/TASK-010-impl.md` (round 3), `work/reports/TASK-010-test.md` (PASS round 3, local checks), `tests/m0/report.md` CHK-M0-140 to -147 and -142-sub.

Verdict: APPROVED

Round 3. This is the reviewer approval, the first of two. I treat TASK-010 as an agent/runner change under TS §8.2 L1268:
- `agent.yml` enforces the REQ-012 listener and TLS guards and the nolint, linkname, cgo, assembly and object-file blocks;
- `units.yml` verifies the TASK-007 agent and runner units.

TASK-010 is approved pending the user's second approval, which `main` collects. G7 to G10 and G17 count as passed only after the first live PR run is green (see note 4).

## Round 3 re-review

- **Only change:** the listing step at `.github/workflows/agent.yml:104-113`. It is now "No cgo, assembly or object files (go list)", with template `{{if or .CgoFiles .SFiles .SysoFiles}}…`, for amd64 and arm64, and it fails on any output. `units.yml` is unchanged (60 lines).
- **The exact step script, extracted from the workflow,** run with `bash --noprofile --norc -eo pipefail` and `CC=/nonexistent/cc` in throwaway copies:

  | Case | Exit | Output |
  | --- | --- | --- |
  | clean tree | 0 | none |
  | my round-2 plant: body-less `func Sock() int64` + `raw_amd64.s` with `SYSCALL` 41 (`socket`) | 1 | `asm=[raw_amd64.s]` |
  | an arm64-only `raw_arm64.s` | 1 | `asm=[raw_arm64.s]`, from the arm64 pass |
  | `blob_linux_amd64.syso` | 1 | `syso=[blob_linux_amd64.syso]` |

- **actionlint v1.7.12** (throwaway `GOPATH`): 0 findings on both files.
- **Unchanged and fine from round 2:**
  - action SHAs equal the newest tags (`git ls-remote`);
  - `contents: read` only, `persist-credentials: false`, no `pull_request_target`, no secrets, `cache: false`;
  - no `|| true`, `continue-on-error` or `if:`;
  - the nolint/linkname grep catches the spaced form, `//go:build ignore` files and `vendor/`;
  - the `_test.go` exemption is safe;
  - the stubs step logic;
  - `go install golangci-lint@v2.14.0`, checked against sumdb;
  - the dev lock in `units.yml`.

## Findings (round 3)

1. **Closed.** Round-2 should-fix: assembly and `.syso` evasion of the agent gates.
2. **nit, for M6.** If the module is vendored, add `--exclude-dir=vendor` to the grep, in a two-approval task. The listing covers only the module's own packages (`./...`), so assembly in dependencies such as `x/sys` is not flagged.
3. **nit, user decision.** The arm64 stubs are built and statically checked but never executed (an arm64 runner or emulation is needed; TS §8.3 plans arm64 hardware in M6).
4. **note.** Not run locally, and must be green on the first PR:
   - the live runs (CHK-M0-144);
   - the real `systemd-analyze verify` (CHK-M0-124 and -125);
   - the ELF stub run (CHK-M0-146).

   Any verify output for the verbatim units is a spec question for `main`, not something to filter.

## History

Round 2 was CHANGES_REQUESTED with one should-fix: a body-less Go function with a `.s` implementation issuing raw syscalls passed the build, golangci-lint, the nolint/linkname grep and the CgoFiles-only listing. It was fixed in round 3 by widening the listing to `SFiles` and `SysoFiles`.
