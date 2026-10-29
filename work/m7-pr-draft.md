# M7 commit split and PR draft (lead)

Draft only. Nothing is committed or pushed until the user says so. TASK-146 is deferred by the user (2026-10-29, a named gate exception): r1 `bit102.py` ships TEST PASS; its review, second approval and r2 (saved in `Documents\m7-deferred\task146-r2\`, not in the tree) move to M10. Second approvals and second looks are recorded (decisions 2026-10-29). Waiting: the reviewer's final closing verdict, then the user's go-ahead to commit.

## Commits on `m7-catalog`

The branch already has `c6b7e13` (M7 work in progress, pushed as `origin/m7`) and the local merge `25d41ec` (main into m7-catalog). New commits go on top:

1. `feat(manager,web,bits): M7 compliance catalog (importer, validator, catalog API and UI)`
   - `manager/bitscan_manager/services/importer/**` (parse, structure, values, validate, the BIT102 lexer and rules, store, pipeline, uploads, folders, rebuild, integrity, start-up, watcher, own_changes, service, delete, profiles, alerts)
   - `manager/bitscan_manager/repositories/{catalog,catalog_plugins,catalog_admin,catalog_integrity,catalog_lock,imports}.py`, `db/pool.py`, `runtime.py`, `app.py`, `cli/{serve,bits,__init__}.py`, `services/audit/{alerts,metrics}.py`
   - `manager/bitscan_manager/api/user/{policies,policy_import,imports,rebuild,__init__}.py`, `manager/openapi.json`
   - `manager/pyproject.toml`, `manager/requirements*.txt` (python-multipart, TASK-139)
   - `web/src/**` (non-test: `api/schema.d.ts`, `app/{App,routes,router,problems}.tsx/ts`, `components/{Icon,Findings}.tsx`, `screens/{Profiles,ProfileDetail,PolicyUpload,Imports,Rebuild}.tsx`)
   - `bits/samples/cis-ubuntu-24.04-l1-server.bit`, `bits/samples/cis-ubuntu-22.04-l1-server.bit`
   - `README.md` ("Policies" section)
2. `test(manager,web,bits): M7 importer, catalog, security and UI suites`
   - `manager/tests/**` (new and updated M7 files, `catalog_api.py`, `catalog_rows.py`), `bits/tests/**`, `web/src/**/*.test.ts(x)`, `web/src/test/harness.ts`
3. `docs: M7 plans, test and review records`
   - `work/` (requirements, tasks, plans, reports, reviews, decisions, open questions, status, this draft), `tests/m7/`, `tests/test-plan.md`
4. `chore(claude): supported hosts, testing by risk, capread socket note` (**the user's call**; `.claude/` edits are the user's, copied uncommitted from the main checkout)

Each commit message ends with `Co-Authored-By: Claude Code <noreply@anthropic.com>`. Before committing, check `git status --short --untracked-files=all` for scratch files. `manager/bitscan_manager/webui/` is a git-ignored build and stays out.

## PR description

Title: `M7: compliance catalog (.bit importer, validator, catalog API and UI)`

```markdown
## Summary

Milestone M7. `.bit` policy files are parsed safely, validated (BIT001–BIT017, BIT101–BIT103), stored as compliance profiles, and managed through the API, the CLI and the web UI. No scans run yet: the evaluator (M8), scan engine (M9) and runner (M10) follow.

Implements TS §4.1–§4.3, §4.6, §5.2 (catalog, bit_import, task), §6.2 (L1100–L1107), §6.3, §8.1, §8.3, §8.4, §8.7 (L1347) and SR §2–§4 for REQ-150 to REQ-185 (TASK-139 to TASK-175).

## Changes

- **Safe parse and validation:** defusedxml only (no DTD or entities), read once, 5 MiB / 5,000 plugins; canonical structure; the content rules; BIT102 through a POSIX `sh` lexer (no regex on commands).
- **Store:** natural-key upsert in one transaction, version bump on content change, plugins retired not deleted, server folder wins over uploads, BIT007/BIT015 ownership.
- **Loading:** the server folder (discovery, inotify watcher, start-up reconcile) and uploads (`POST /policies/import`, in-memory multipart, `uploaded/policy-<id>.bit` via a temp file with O_EXCL|O_NOFOLLOW, renamed after commit).
- **Rebuild:** `POST /policies/rebuild` (TOTP session) and `bitscan-manager bits rebuild`, each file in its own savepoint, ids kept; `GET /tasks/{id}`.
- **Start-up:** finish interrupted uploads, fail stale tasks, reconcile, integrity check with one alert; mutating routes answer 503 with Retry-After until it ends.
- **Profiles:** list, detail, enable/disable/override (`PATCH`), delete (`DELETE`, TOTP session), import history (`GET /imports`).
- **Audit and alerts:** every import, rejection, refusal, move, delete, re-enable and rebuild is audit-logged; the M7 alert kinds and `bitscan_import_failures_total`.
- **Web UI:** Profiles, Profile detail, Upload policy, Import history, Rebuild catalog, in a new Compliance menu group.
- **Samples:** CIS Ubuntu 24.04 and 22.04 Level 1 server, read-only checks.

## Decisions and accepted risks (work/decisions.md)

- **BIT102, non-literal command words allowed (user, 2026-10-27).** Residual risk: `c=rm; "$c" -rf /` passes BIT102. The runner sandbox (M10) is the control.
- BIT102 is stricter than #108 in several places (verbs anywhere, `<>` as output, `env -S`).
- **Gate exception (user, 2026-10-29): TASK-146 (BIT102 rules) ships as r1 with TEST PASS (1,160/1,160, plants red) but without its code review and TS §8.2 second approval.** Both, plus the r2 gap closure (wrappers such as `time`/`nsenter`/`flock`, `su -c`, `trap`, brace expansion in `bash -c`), move to M10. No plugin command runs before M10's sandbox.
- #100 (a) widened: a reactivated plugin counts as a changed Execute in the import alert.
- Crash window: a deleted policy's leftover upload is removed, never revived.
- Rebuild alerts only for changed policies (#23); `policy_version` only on success (SR §3.5).
- The watcher handles a batch's incoming paths before outgoing ones (a rename is a move).
- Process (no product effect): routes built in parallel with a single openapi regeneration (PD-24 (a) relaxed); the full suite run at the gate only; the M6 VM plants CHK-M6-340..345 waived by the user.

## Testing

- M7 gate PASS (`work/reports/M7-gate-test.md`, closing review `work/reviews/M7-gate.md`): full manager suite 8,866 passed, 0 failed, 0 skipped; services coverage 95.34 % (floor 85 %); G54–G61 green; web 516/516; every mutation row CHK-M7-320..371 red; no gate lowered (G54's 100 ms bound unchanged, measured in a clean subprocess).
- Per-task records: `tests/m7/report.md`.
- NOT RUN: the TS §8.3 sandbox half (no runner until M10), the VM end-to-end import (M11), load tests (deferred). TASK-146: see the gate exception above; its BIT102 rows (CHK-M7-191 with all fixtures, G59) ran and passed on r1.

## Approvals

TS §8.2 second approval (user): every two-approval M7 task (W1 on 2026-10-27; W2/W3 on 2026-10-28; the rest on 2026-10-29), except TASK-146 (deferred). PD-35 second looks: TASK-139, 161, 174 and 175 given.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
