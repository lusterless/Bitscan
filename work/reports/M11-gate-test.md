# M11 gate (TP-M11-15, -23, -24): PASS, except G39 NOT RUN (safety-check refusal; CI covers it on the PR). The merge is held by the open CHK-M11-387 finding (REQ-275, REQ-276 at fleet size), pending the user

Tester: tester-m11g, 2026-11-09. Tree: worktree `Bitscan-m11`, branch `m11-results` at **`c090303`** (all 28 M11 tasks committed) plus this gate's test changes (uncommitted): the new `manager/tests/test_security_m11.py` (TP-M11-15) and the CHK-M9-276 (M11) rewrite in `manager/tests/test_security_m9.py` (PD-51, approved by main). The lead's later commit **`c62da73`** (TASK-260) changes only `README.md` (+1 line) and `deploy/runbooks/manager-operations.md` (+6 lines) among the files tests read, so the tests that read them were re-run on `c62da73` (below). No product file was edited. Every plant was made in a throwaway copy that was deleted after its row, and the worktree holds none (`git status`: those two test files, `tests/m11/test-plan.md` (the TP-M11-15 binding note), this report, and the lead's `work/decisions.md` and `work/status.md`).

**Summary.** Every gate run is green on a clean tree and red on its planted violation: G1–G6, G12–G16, G18 (**11,908/11,908**, 0 skipped, after the PD-51 rewrite of CHK-M9-276 and one environment timing flake re-run alone), G19, G30–G34, G37, G38, G40, G41 (23/23), G80–G84, and G85–G87 (cited: hosted run 42488215323; G87's plants -373 and -374 red in runs 42594910837 and 42594935136). Services coverage (G5) is **98.5920 %**. TP-M11-15 is written: `test_security_m11.py`, **45/45**, with 24 of its 25 plants red; -322 stays green there by design. The mutation table holds every row from CHK-M11-320 onwards; all are red where the table names them, and no gate was lowered. **NOT RUN:** G39, the reproducible double build. A safety check refused the network step its fresh-cache builds need, and nothing was worked around; it is covered by M10's identical builds of the unchanged agent, 95/95 other build checks, and the PR's CI job. **Open, pending the user:** CHK-M11-387 (tester-m11t's #151 timing). Retention cannot delete a scan of more than about 600 hosts, or any inventory job, within `statement_timeout` at fleet size (no index on `scan_job.retry_of` or `scan_result_reeval.job_id`). It is recorded, neither passed nor failed, and it holds the merge. **Process note:** no M11 manager full suite ran between waves, so the stale CHK-M9-276 was first seen at this gate.

User decisions applied (decisions 2026-11-09): (1) #155 stays as built, so the 100,000-row CSV cap is tested as approved; (2) the G87 plant branches were allowed, and main pushed, ran and deleted them; (3) if the #151 timing changes `SCAN_CHUNK`, the retention suites are re-run for that fix round; (4) this report is the merge evidence.

Environments:
- **L:** Windows 11, worktree; web gates from `web/` with the worktree's `node_modules`.
- **W:** WSL Ubuntu 24.04 (14 vCPU, 3.9 GB, shared with tester-m11t's CHK-M11-387 timing database), `CI=true`, PostgreSQL 16 by Testcontainers. Own folder `/root/m11g`: `tree/` rsync'd from the worktree (no `.git`, venv, `node_modules` or caches), `venv/` from `pip install --require-hashes -r manager/requirements-dev.txt` then `-e tree/manager`, `venv-g41/` (the same lock) for G41, whose harness re-points the editable install. Scripts in `C:\Users\kaiquan.koh\Documents\m11g-scripts\`; `bs[uaek]_` strings masked in every log before reading.
- **Web UI for the M5 walk:** built outside the tree (a temp copy of `web/` with a junction to `node_modules`, `vite build --outDir m11g-scripts/webui`) and copied into the WSL copy only. Its bytes equal tester-m11d's build (`index-C0l5idKQ.js` `b2953f67…`, `index-BJT0iK-w.css` `ffe816ca…`).
- **Zscaler:** WSL's `/etc/ssl/certs/ca-certificates.crt` mounted read-only into every container that needs the network.

## TP-M11-15: the M11 security suite, `manager/tests/test_security_m11.py` (G83)

Written at this gate as one file (45 tests: 39 CODE, 6 PostgreSQL; the `-m "not pg"` plant runs show "39 passed, 6 deselected"). It reuses the task suites' builders: `m11_pg_fixtures` (callers of every role and kind, `results_world`, `aged_world`, the audit chain, `RoleSpy`, checksums, the sink outage), the re-evaluate world and state probes of `test_reevaluate_api_pg.py`, the page walker of `test_results_api_pg.py` and the route-walk markers of `test_auth_dependencies.py`. Lint: `ruff check`, `ruff format --check` and `mypy --strict` on the file are clean (W).

| Check | Tests | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-240 route walk | `test_the_scan_operations_are_exactly_the_spec_routes_with_their_markers`, `test_no_operation_of_the_app_takes_command_text` | PASS | The live app's scan operations are exactly M9's two and M11's six; markers `role viewer` ×5 and `totp_session admin` with the sink gate for re-evaluate; no M11 operation takes a body; no request schema of any operation has a command-like field; no rerun, run, exec or shell path |
| CHK-M11-241 response models | `test_only_the_operator_results_model_carries_output` | PASS | Only `ScanResultItemWithOutput` has `stdout`/`stderr`; `ScanItem`, `ScanDetailItem`, `HostSummary`, `HostJob`, `ReevalItem` have no output, `execute`, `expected`, `operator` or `resolved_agents` |
| CHK-M11-242 one writer | `test_reevaluate_scan_is_the_one_writer_of_reevaluations`; the spy in `test_viewers_never_receive_output_and_reads_write_nothing` | PASS | SQL text of every product module (migrations aside): `INSERT INTO scan_result_reeval` only in `repositories/reeval.py`; no UPDATE, DELETE or TRUNCATE of `scan_result*`; `DELETE FROM scan` only in `repositories/retention.py`; `reevaluate_scan` referenced only by `api/user/reevaluate.py` (defined in M8's module). Every M11 read route, every role, JSON and CSV: no write to `scan`, `scan_job`, `scan_result*` |
| CHK-M11-243 import graph | `test_the_m11_routes_reach_no_repository[2]`, `test_the_m11_layers_point_down_only[10]` | PASS | `scan_views.py` and `reevaluate.py`, and every `bm.api` module they reach at module level, import no repository and no psycopg; M11 services import no `bm.api`; M11 repositories import no service or api; the pure modules import no database code (the results view only its row type, CHK-M11-014) |
| CHK-M11-244, -245 frozen files | `test_the_frozen_files_are_byte_unchanged`, `test_no_file_was_added_to_a_frozen_folder[3]` | PASS | 38 files pinned by sha256 at `6efe0fb`: `auth/*` (11), `services/jobs/*` (11, M9), the five migrations and `versions/__init__.py`, `services/evaluator/{score,scores,reevaluate}.py`, `repositories/{results,reeval,scan_progress}.py`, `api/user/{scans,scan_schedules}.py`, `services/packages/csv_export.py`, `services/audit/{chain,verify}.py`; each byte-identical (also checked with `git show 6efe0fb:<path>` against the worktree on L). No file added to `auth/` or the migrations; `services/jobs/` gains exactly the three M11 modules |
| CHK-M11-246 agent components | `test_m11_contract.py::test_earlier_components_are_byte_identical` (kept there) | PASS | in G18 |
| CHK-M11-247 token groups | `test_tokens_are_refused_outside_their_route_group` | PASS | `bsa_` (an agent's real one, and one whose hash a `user_token` row holds) and `bse_` (likewise) get 401 `unauthorized` on all six M11 operations; a `bsk_` with its row gets 200 on the five reads (control). On an agent route, `bsk_` and `bsu_` whose hash an `agent` row holds get 401, and an operator session and an admin API token get 401; the agent's own `bsa_` pulls 200 (control) |
| re-evaluate refusals | `test_reevaluate_refuses_everyone_but_a_totp_admin_session`, `test_reevaluate_is_refused_from_15_minutes_of_sink_outage_until_the_drain` | PASS | admin API token 403 `totp_session_required`; restricted admin (no TOTP) and an admin whose session is not TOTP-verified 403 `totp_enrolment_required`; operator and viewer sessions 403 `forbidden`; operator and viewer API tokens 403; revoked token, `bsa_`, `bse_`, no token 401. Each refusal leaves the `scan_result_reeval`, `audit_log` and `scan_result` checksums unchanged. The admin TOTP session then gets 200, 3 rows, one `scan.reevaluate` entry. Clock control: 14 min 59 s into a sink outage 200; at 15 min 503 `audit_sink_unavailable`, nothing written; after the drain 200 again |
| CHK-M11-248 canary sweep | `test_no_canary_or_token_leaves_through_logs_problems_or_audit` | PASS | One flow at DEBUG over every M11 operation: 6 callers (viewer, operator, admin; session and API token) × every page (limit 2), every status filter, the CSV per filter, list, detail, host history; 5 bad requests each; the re-evaluation and 4 refusals. No log record (message, args, every attribute) holds OUT, ERR, EXEC, EXP or any caller's or agent's token; no problem body and no new audit detail holds a canary |
| CHK-M11-249 retention role limits | `test_retention_code_cannot_update_alter_or_insert`, `test_only_the_scheduler_runs_retention`, `test_serve_gives_retention_its_own_bitscan_retention_pool`, `test_retention_runs_as_bitscan_retention_within_its_role` | PASS | Static: the retention SQL has no UPDATE, row lock, DDL or INSERT, and deletes only the nine TS §5.2 retention tables; the service is imported only by the scheduler runner; serve gives the runner `AppDatabase(bounded_dsn(config.retention_dsn), name='bitscan_retention')`. APP: a `SchedulerRunner` built as serve builds it (an app pool and the retention pool) runs retention over the aged world: every statement is `bitscan_retention`'s, none the app pool's; no DDL, UPDATE or `FOR UPDATE`; INSERT only `INTO audit_log` (the checkpoint); all seven steps done with `skipped` null and no failure; the never-deleted tables (`os_info`, `agent_package`, `agent`, catalog, …) checksum-identical; the old scan gone, the inside one kept; the log holds no canary and no deleted scan or job id |
| CHK-M11-250 S608 and `re` | `test_s608_is_green_as_is_and_red_on_an_f_string_query[4]`, `test_the_re_ban_is_green_as_is_and_red_on_an_re_import[12]` | PASS | `ruff check` on stdin under the tree's configuration (`--stdin-filename`): each new repository is clean as it is and S608 on an appended f-string query; each of the 12 new modules is clean as it is and TID251 "`re` is banned" with `import re` |
| G83 run | `run.sh sec4 -n 2 tests/test_security_m11.py` (W) | **PASS** | **45/45 passed, 0 failed, 0 errors, 0 skipped** (33 s). First run 42/45: three test bugs, fixed in the test (the results view's allowed row-type import, CHK-M11-014; a lone surrogate in a product string constant that RE2 cannot encode; the auth-failure rate limit answering 429 before the token check, so each refused call now comes from its own address). Then the fixed `writer` row re-ran alone, 1/1 passed, and the whole file 45/45. Also in G18 |

G83 plants (throwaway copies, the whole file run each time; logs `g83code.jsonl` with `-m "not pg"` for the CODE-only rows, `g83pg.jsonl`):

| Plant | Red rows | Result |
| --- | --- | --- |
| CHK-M11-320 | viewer row | red |
| CHK-M11-321, -321-csv | viewer row (each) | red ×2 |
| CHK-M11-322 | none: survives by design (the route's viewer model drops the planted key) | green (expected; not a G83 row) |
| CHK-M11-323 | viewer row (CSV header) | red |
| CHK-M11-331 | viewer row (item count, another scan's rows) | red |
| CHK-M11-335 | markers, refusals, sink outage (and the clean-ruff row: an unused import) | red |
| CHK-M11-336 | markers, 15-minute row | red |
| CHK-M11-337 | markers, refusals | red |
| CHK-M11-339 | one-writer row, viewer row (the read spy saw the INSERT) | red |
| CHK-M11-341 | retention static row, retention run row (the packages step failed: permission denied) | red |
| CHK-M11-342 (serve), -342b (runner) | serve wiring row; retention run row (app-pool statements, every delete refused) | red ×2 |
| CHK-M11-344, -345 | S608 row for that repository | red ×2 |
| CHK-M11-346 | scan operations, command body | red |
| CHK-M11-357 | retention run row (a deleted scan id in the log) | red |
| CHK-M11-358 | canary sweep row | red |
| CHK-M11-359 | import-graph row | red |
| CHK-M11-367 | frozen-file row | red |
| CHK-M11-369 | retention static row, retention run row | red |
| CHK-M11-390 | re-ban row for `services/retention/task.py` | red |
| SEC-tok-user: the user parser takes `bsa_`/`bse_` as API tokens | token-group row, frozen-file row | red |
| SEC-tok-agent: the agent check takes `bsk_`/`bsu_` | token-group row, frozen-file row | red |
| SEC-reads-operator-only | markers row | red |

**25 plants: 24 red, 1 green by design (-322, red in G80 and G82 where it belongs).** Every S row of the mutation table marked G83 is red in G83.

## Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check .` from `manager/` (W, `static.sh`) | **PASS** | "All checks passed!". Plants red (`static.jsonl`): -344 and -345 (S608, `Found 1 error`), -390 (TID251 in `task.py`) |
| G2 | `ruff format --check .` (W) | **PASS** | "419 files already formatted" (420 with this gate's file). Plant red: one misformatted line in `results_read.py`, "1 file would be reformatted" |
| G3 | `mypy --strict .` (W) | **PASS** | "Success: no issues found in 419 source files"; this gate's file alone: no issues. Plant red: an untyped function in `results_read.py`, "results_read.py:19: error: Function is missing a type annotation [no-untyped-def]", "Found 1 error in 1 file (checked 420 source files)" |
| G4 | `pip install --require-hashes -r manager/requirements-dev.txt` (the venv) and `-r manager/requirements.txt` (a fresh venv) (W) | **PASS** | both rc 0 (the runtime lock: 35 pinned packages, 678 hashes). `git diff 6efe0fb` of the locks is empty; `pyproject.toml` changed only `precision` 2 → 4 (TASK-255). Plant red: the alembic entry with wrong hashes, `pip download --require-hashes` rc 1 "THESE PACKAGES DO NOT MATCH THE HASHES"; the unplanted entry rc 0 (control) |
| G5 | services coverage in G18 (`[tool.coverage.report]` `fail_under = 85`, `precision = 4`) | **PASS** | **98.5920 %** (6,022 of 6,108 statements; CHK-M11-311: 98.59 % to two decimals, not rounded up; gate 85). The M11 modules: `services/retention/task.py` 102/102, `rules.py` 62/62, `__init__.py` 0/0, `services/jobs/results_read.py` 34/34, `results_view.py` 54/54, `scan_views.py` 56/57 (line 115). Plant -391 red: 982 untested statements appended to `task.py` in a throwaway copy, the G18 data remapped onto the copy (control on the copy before the plant: 98.5920 %, rc 0), then "Coverage failure: total of 84.9246 is less than fail-under=85.0000", rc 2 (`cov.sh`) |
| G6 | `tests/test_openapi.py` in G18 | **PASS** | 6/6 in G18, including `test_committed_file_matches_a_fresh_export`. Plant -392 red (TASK-232) |
| G12 | `npm run lint` (L) | **PASS** | eslint `--max-warnings 0` exit 0. Plants -360, -361, -362 (b), -375 red (eslint exit 1; TASK-247, -248, -256) |
| G13 | `npm run typecheck` (L) | **PASS** | `tsc --noEmit` exit 0 |
| G14 | `npm run format:check` (L) | **PASS** | "All matched files use Prettier code style!" |
| G15 | `npx vitest run` (L; `testTimeout` 20000, TASK-257) | **PASS** | **755/755 passed in 31 files**, 0 failed, 0 skipped (42.8 s). Plants -360 to -366 red (G84 below) |
| G16 | in a temp folder: `openapi-typescript ../manager/openapi.json`, then Prettier with `--stdin-filepath src/api/schema.d.ts`; `cmp` with the worktree file (L) | **PASS** | byte-identical (sha256 `e7ffd8c4…c30a` both). Plant: a hand edit of line 2323 (`stdout: string \| null` → `string \| number \| null`) makes the regenerated file differ (`cmp` rc 1) |
| G18 | full manager suite: `pytest -n 2 -rfEs --tb=short --cov=bitscan_manager/services --cov-fail-under=85` (W, `CI=true`, `g18.sh`) | **PASS** (after the CHK-M9-276 (M11) rewrite) | Run 1 (57 min 20 s, 212 files): **11,906/11,908 passed, 2 failed, 0 errors, 0 skipped**; `Required test coverage of 85% reached`. The 2 failures: (a) `test_bit_parse.py::test_35015_elements_is_bit002_bounded`, an M7 timing bound ("2.878 s < 2.0 s" false) under the shared WSL load; **environment flake**, not a product change: re-run alone 1/1 passed, and 1/1 again later under lighter load. (b) `test_security_m9.py::test_no_m9_route_takes_command_text_or_names_inventory` (CHK-M9-276), deterministic (alone 1/1 failed): it asserted the `/api/v1/scans*` and `/scan-schedules*` operations are exactly M9's seven, and the extra items were exactly M11's five (`GET /scans`, `GET /scans/{id}`, `GET …/results`, `GET …/results.csv`, `POST …/reevaluate`). A test that M11's approved contract outdates (red since TASK-232, W1), not a product bug. **No M11 manager full suite ran between waves** (the speed rules ask for one per wave end; only targeted runs and the web full runs were recorded), which is why it was not seen until this gate. Rewritten under PD-51 with main's approval (old → new table): still an equality, M9's seven plus exactly M11's five, the M11 five checked to take no body, every body and parameter check kept. Re-run: `test_security_m9.py` **14/14** with the timing row **1/1** (15 passed); plant: a sixth, unknown operation `POST /api/v1/scans/{id}/rerun` in a throwaway `openapi.json` turns the row red. Final count: 11,908/11,908 (11,906 in run 1 plus the two node ids re-run green), 0 skipped. The web UI build and `README.md` were in the WSL copy (the M5 walk 1/1) |
| G19 | `pytest -m pg tests/test_schema_diff.py` (in G18) | **PASS** | **2/2** in G18 (no migration in M11; `db/migrations/versions/` byte-identical to `6efe0fb`, G83). Plant -393 red: a throwaway `m0006` adding `ix_reeval_job ON scan_result_reeval (job_id)`, `test_migrated_schema_equals_the_spec` failed (1 failed, 1 passed); G83's frozen-folder row also catches a new migration file |
| G30 | `tests/test_contract_agent.py` (in G18) | **PASS** | **569/569** in G18. Plant red: `stdout` added to `HeartbeatResponse`, `test_heartbeat_response_exact` (1 failed, 568 passed). My first form of the plant, an optional `stdout` on `HeartbeatRequest`, kept G30 green (569/569: the contract pins the request through the shared fixtures, which stay valid), and **G6 turns red on it** (`test_committed_file_matches_a_fresh_export`, 2 failed): recorded so the reviewer sees where each form is caught |
| G31 | `tests/test_agent_auth_pg.py tests/test_security_m3.py` (in G18) | **PASS** | **32/32** in G18. Plant red: the agent-route token check accepting `bsk_`/`bsu_` (`auth/tokens.py`, as G83's SEC-tok-agent), `test_wrong_prefix_refused_when_its_hash_is_an_agent_row[bsk_]`, `[bsu_]` (2 failed, 30 passed) |
| G32 | `tests/test_inventory_fuzz.py tests/test_inventory_decode.py` (in G18) | **PASS** | **129/129** in G18. Plant red: `DECOMPRESSED_CAP` 64 → 640 MiB, `test_64_mib_plus_one_is_413_after_at_most_cap_plus_one`, `test_gzip_bomb_is_refused_within_the_bounds` (2 failed, 127 passed) |
| G33 | `tests/test_sweep_pg.py tests/test_inventory_queue_pg.py tests/test_fleet_alerts_pg.py` (in G18) | **PASS** | **54/54** in G18. Plant red: the inventory upload window 30 min → 30 h in `sweep.py` (M3's G33 plant), 5 failed (`test_expiry_and_inventory_timeout`, the failing-step rows). The gate table's CHK-M11-341 as a G33 plant **stays green there (54/54)**, as expected: the sweep and inventory suites never run retention. -341 is red in G81 and G83, where it belongs. A table note for the planner, not a gap |
| G34 | `tests/test_invariants_m3.py` (in G18) | **PASS** | **33/33** in G18 (the six M11 operations in the spec route set, the M11 query-parameter sets). Plant -346 red: `test_every_operation_is_a_spec_route`, `test_no_request_schema_carries_a_command` (2 failed, 31 passed) |
| `.deb` | `deploy/debian/build-deb.sh` in `m4b-build-u24` from a copy of the tree (`pkg.sh build`) | **built** | `dpkg-parsechangelog` `0.2.0~pre2-1`; `bitscan-agent_0.2.0~pre2-1_amd64.deb` sha256 `800dc172…ea76`, `sha256sum -c` OK; binaries `bitscan-agent` `1d2c41a1…455e`, `bitscan-runner` `886cd319…0a13`, `bitscan-capread` `7d001846…e06e` (capread equals M10's; agent and runner carry the version string). The agent source is unchanged since `6efe0fb` (`git diff --stat 6efe0fb c62da73 -- agent deploy/debian deploy/systemd deploy/dbus`: only `changelog`) |
| G37 | `test_build_deb.sh --deb <that .deb> all`, lintian part (`pkg.sh g37`) | **PASS** | lintian **4/4**: `lintian --fail-on error,warning` passes, no E:/W: tag, no unused or mismatched override, every override has a reason. Plant red: a unit packaged 0666 (repacked copy), "W: bitscan-agent: non-standard-file-perm 0666 != 0644 [lib/systemd/system/bitscan-agent.service]", 2/4 |
| G38 | `test_maintainer_scripts.sh --deb <that .deb> all`, then `--from 0.1.0-1 upgradefrom`, in a privileged `m4b-sysd-u24` container (`pkg.sh g38`) | **PASS** | `all`: **OK 547/547** (install, missing, installenv, envvars, reinstall, upgrade, purge, reenrol, invalid, etcperm, stringpreseed, symlink, static), rc 0. `upgradefrom 0.1.0-1 -> 0.2.0~pre2-1`: **OK 20/20**, rc 0 (the 0.1.0-1 `.deb` checked against `SHA256SUMS-0.1.0` first). Plant red: postinst that refuses a second run (repacked copy), `reinstall` "exits 0 (got '100')", "half-configured" ×2 |
| G39 | `test_build_deb.sh … all`, repro part | **NOT RUN** (safety-check refusal) | The two repro builds each use a fresh Go module cache, so they download from `proxy.golang.org`. In the build container Go dialled only the IPv6 address ("connect: network is unreachable") for `santhosh-tekuri/jsonschema/v6@v6.0.3`, so both builds failed before compiling (3 FAIL rows, setup, not product). My next step, pinning the Go hosts to IPv4 in the container, **was refused by a safety check**, so per the brief it was not retried or worked around. Cover: the agent source is unchanged since M10, whose G39 found two builds identical (`.deb`, `.sha256`, three binaries, SBOMs); this gate's single build passed every other check (95/95: contents 24, static 14, SBOM 21, sha256 4, flags 28 with `-trimpath`, `CGO_ENABLED=0`, no VCS stamp, empty build id, lintian 4); and CI's `package.yml` job "Double build is byte-identical" runs on the pull request |
| G40 | `test_build_deb.sh … all`, SBOM part | **PASS** | **21/21**: each CycloneDX SBOM lists exactly the modules `go version -m` prints, with their versions and the Go version (runner and capread list `golang.org/x/sys v0.49.0`). Plant red: the runner SBOM says `v0.48.0`, "module golang.org/x/sys v0.49.0 … is in the SBOM (SBOM has ['v0.48.0'])", 20/21 |
| G41 | `e2e/agent_manager.sh /root/m11g/tree /root/m11g/pkg/out … m4b-sysd-u24` with the `0.2.0~pre2-1` `.deb` (`800dc172…ea76`) against a real `serve` from the M11 tree (W, `g41.sh`, `venv-g41`) | **PASS** | **OK 23/23 rows, rc 0** (about 20 min): serve ready (PostgreSQL 16, HTTPS, private CA); clean systemd host; admin by the CLI; TOTP session; `bse_` token (201); install with preseed `0.2.0~pre2-1 install ok installed active`; no `bse_` in debconf, `/etc` or logs; enrolment held (kind new); waits while held; approve 200; online; first inventory (`os_info` and the snapshot); package search; a dpkg change gives one unscheduled upload after the 60 s quiet time; a second change during the hold-off is not sent for the manager's 10 minutes (571 s watched) and is sent when it ends; revoke 204; the 401 stops the loops (journal line once); no agent call in 400 s after the 401; no `bse_`/`bsa_` in the agent journal or `serve.log`. Plant red (the reverse-order `list_sha256` `.deb`, built from a throwaway copy whose only diff is `slices.SortFunc(lines, func(a, b []byte) int { return bytes.Compare(b, a) })` in `agent/internal/inventory/dpkg.go`, `.deb` `8bf4ec8f…5d52`): **FAIL 12/13 rows, rc 1**, at "the first inventory job is uploaded": `refused: [{reason: hash_mismatch, status: 422}, …]`, no `os_info`, and the chain stops there |
| G80 | `test_results_view.py`, `test_retention_rules.py` (in G18) | **PASS** | **167/167** in G18. Plants: the TASK-233 and TASK-236 rows of the mutation table, red |
| G81 | the TP-M11-01, -03 to -06, -08 to -10, -13, -22 files (in G18) | **PASS** | **237/237** in G18 (12 files: `test_m11_fixtures_pg`, `test_scan_reads_pg`, `test_result_reads_pg`, `test_results_property_pg`, `test_retention_repo_pg`, `test_retention_grants_pg`, `test_scan_views_pg`, `test_results_read_pg`, `test_retention_pg`, `test_retention_race_pg`, `test_retention_wiring`, `test_serve_retention_linux`). Plants: the TASK-234, 235, 237, 238, 240, 241, 242, 245 rows, red |
| G82 | `test_scan_views_api_pg.py`, `test_results_api_pg.py`, `test_reevaluate_api_pg.py`, with `test_m11_contract.py` and `test_m11_contract_api_pg.py` (in G18) | **PASS** | **231/231** in G18 (5 files). Plants: the TASK-232, 243, 244 rows, red |
| G83 | `test_security_m11.py` | **PASS** | 45/45 (above), and in G18; 24 of 25 plants red, -322 green by design |
| G84 | the M11 web suites (inside G15) | **PASS** | in G15's 755/755. Plants -360 to -366 red (TASK-239, -246, -247, -248, -251), and tester extras -375 to -379, -430 to -440 red |
| G85 | nightly end to end (`e2e/m11/nightly.py` through `e2e.yml`) | **PASS** (cited) | Hosted e2e run **42488215323** on `5671c82`: `nightly` 19/19 PASS (both hosts: install held, approve, online, inventory 598 = 598 and 665 = 665, SR §1.1 import, scan `completed`, score 1.0, the plugin PASS, `results.csv`, the viewer without output, sweep 0 hits). Plants -370 (16/19) and -371 (18/19) red. Source: `work/reports/M11-e2e-test.md`. Not re-run, per the brief |
| G86 | N / N−1 (`e2e/m11/compat.py`) | **PASS** (cited) | Run 42488215323: `compat-a` 10/10 (agent 0.1.0 with manager N; every plugin ERROR `runner_unavailable`, score null), `compat-b` 8/8 (agent N with manager 0.1.0; no compliance job). The upgrade walk CHK-M11-307 16/16 (WSL, `5671c82`). Plant -372 red. Source: M11-e2e |
| G87 | `e2e.yml` itself | **PASS** | Scheduled and dispatch triggers, `[e2e]` push runs (42488215323 green) and a plain push skipped (run 42485349317, `skipped`). Plants: -373 run **42594910837** red ("FAIL CHK-M11-303 all", "FAIL CHK-M11-309 sweep:a", "sweep:b"); -374 run **42594935136** red ("missing CHK-M11-302 viewer"; compat-a and compat-b green as controls). Both throwaway branches deleted (main, 2026-11-09, under the user's decision (2)) |

Re-runs on `c62da73` (TASK-260: README +1 line, `manager-operations.md` +6 lines, docs only): the four README walks `test_readme_walk_linux.py`, `test_readme_m5_walk_linux.py`, `test_readme_m7_walk_linux.py`, `test_readme_m9_walk_linux.py` **4/4 passed** (3 min 32 s, W); `check_runbook_text.py`: `README.md` "OK 11 sh blocks, 0 findings", `manager-operations.md` "OK 24 sh blocks, 0 findings", `agent-install.md` its two known M6 placeholder findings (unchanged since M10). `e2e/m11/compat.py` walks `manager-operations.md` §1, which TASK-260 did not touch (the new §8 has no shell block).

## Open finding, pending the user: CHK-M11-387 (#151, retention at fleet size)

**Recorded, neither PASS nor FAIL** (CHK-M11-387 was planned as "recorded, not a gate"; main, 2026-11-09). tester-m11t's measurement (`work/status.md`, 2026-11-09 FINDING): on data set A (10,000 hosts, 1.82 M `scan_job` rows), retention runs past `statement_timeout` 300 s **per deleted job**, not per scan. 100 single-host scans took 105–108 s (fits); 1,000 inventory jobs (one `JOB_CHUNK`) were cancelled at 300 s; one scan of 1,000 hosts (1,019 jobs, a chunk of one scan) was cancelled at 300 s. Cause, confirmed by the lead against TS §5.2: no index on `scan_job.retry_of` (the self-reference) or on `scan_result_reeval.job_id` (FK, `ON DELETE CASCADE`), so each deleted job seq-scans both tables. Consequences: a fleet scan of more than about 600 hosts can never be deleted, and, as the oldest, it blocks every later scan; inventory jobs are never deleted. **An open finding against REQ-275 and REQ-276 at fleet size**, beyond the slow-but-working retention the user accepted for v1 (decisions 2026-11-08 (2)). **It holds the merge until the user decides**, and tester-m11t is measuring the options. The retention suites here (G81 237/237, G83's retention rows) pass at test size and say nothing about fleet size. If the fix changes `SCAN_CHUNK` or the retention code, the retention suites (G80, G81, G83's retention rows, G5) are re-run for that round (decisions 2026-11-09 (3)).

## NOT RUN at the M11 gate, with reason and cover

| Row | Reason | Cover |
| --- | --- | --- |
| G39 (reproducible double build) | **Safety-check refusal.** The repro builds need module downloads from `proxy.golang.org` into fresh caches; the build container's Go dialled only IPv6 ("network is unreachable"), and the step that would have pinned the Go hosts to IPv4 was refused. Not retried or worked around | The agent source is unchanged since `6efe0fb` (only the changelog), and M10's G39 found the two builds identical. This gate's build passed the other 95 build checks. The CI `package.yml` job "Double build is byte-identical" runs on the pull request; main checks it there |
| G7 to G11, G17, G35, G36 | Not re-run beyond CI, by the gate plan: M11 changes no agent or unit file (`git diff --stat 6efe0fb c62da73 -- agent deploy/systemd deploy/dbus` empty) | CI `agent.yml`, `units.yml` on the PR |
| CHK-M11-387 | Not a gate, and tester-m11t's row (run in parallel, not run here, per the brief): the open finding above | tester-m11t's report |
| Load tests (TS §8.3 L1284) | Deferred by the user | none |
| Debian 12, arm64 rows (TS §8.3) | Not supported (decisions 2026-10-24) | none |

REQ-288 (agent N with manager N−1) is built and passed (the user answered the N / N−1 marker "both ways", decisions 2026-11-08 (1)): G86 `compat-b` 8/8.

## Old → new check ids at this gate (PD-51)

| Old | New | Rule | Source |
| --- | --- | --- | --- |
| CHK-M3-233 / CHK-M9-219 (stop record: one "pool closed") | the TASK-245 rewrite in `test_serve_scheduler_linux.py` | two "pool closed" events (retention, then app), both after the single "scheduler stopping" and after the running sweep ended; the pool names are CHK-M11-198 | TASK-245 (CHK-M11-385) |
| CHK-M9-218 (job set, from CHK-M3-230) | unchanged for the three-argument runner; the four-job row is CHK-M11-196 | plus `test_without_the_retention_pool_three_jobs_and_no_retention_read` | TASK-245 |
| CHK-M9-285 (README text: results routes "not part of this version yet") | CHK-M11-386 | the Scans section has `### Scan results` and no "not part of this version"; the keys and lag clauses kept | TASK-252 |
| CHK-M5-280 (nav entries) | CHK-M5-280 (M11) | Scans after Profiles for every role; Schedules after Scans for operator and admin; everything else unchanged | TASK-251 |
| CHK-M9-276 (the operations under `/scans` and `/scan-schedules` are exactly M9's seven) | **CHK-M9-276 (M11)** | still an equality: M9's seven plus exactly M11's five under `/scans` (TS §6.2, plan TASK-232 §3); the five checked to take no request body; every body and parameter check kept for all twelve. `manager/tests/test_security_m9.py` (`M9_OPS`, `M11_SCAN_OPS`), approved by main 2026-11-09 under PD-51. Re-run 14/14; plant (a sixth operation in a throwaway `openapi.json`) red | this gate |

## Files of this gate

- `manager/tests/test_security_m11.py` (new, TP-M11-15, G83).
- `manager/tests/test_security_m9.py` (CHK-M9-276 (M11), above).
- `tests/m11/test-plan.md`: one note under TP-M11-15 binding CHK-M11-240 to -250 to the test names.
- This report. Scripts and logs outside the tree: `C:\Users\kaiquan.koh\Documents\m11g-scripts\` and `/root/m11g/logs/`.

## M11 mutation table (CHK-M11-320 onwards)

Every row was planted in a throwaway copy and turned its named check red for the planted reason, unless the row says otherwise. "Gate" in the Source column means planted at this gate (logs `/root/m11g/logs/g83code.jsonl`, `g83pg.jsonl`, `static.jsonl`, `gates2.jsonl`; runner `m11g-scripts/plant.py`, plants `plants-gate*.json`, `plants-static.json` from the `mk_plants_*.py` generators). Otherwise the source is the per-task report (folded into `tests/m11/report.md`). S = security row.

| CHK | Plant | Red in | Result | Source |
| --- | --- | --- | --- | --- |
| -320 S | `include_output` true for viewer | G80 (role table); **G83** (viewer row) | red | TASK-233; gate |
| -321 S | role read from the token kind (a viewer API token reads as operator); CSV variant passes `"admin"` | G82 (`viewer:api`, demoted); **G83** (viewer row) ×2 | red | TASK-244; gate |
| -322 S | viewer items carry `stdout: null` | G80 (viewer keys); G82 (the route-level variant `-322-route`) | red | TASK-233, TASK-244. At this gate the view-level plant **survives G83, as it should**: the route's viewer model `ScanResultItem` has no `stdout` field and pydantic drops extra keys, so no key or byte reaches a viewer (45/45 green). Not a G83 row in `work/tasks.md` |
| -323 S | viewer CSV keeps the two columns (empty) | G80; **G83** (CSV header row, through the API) | red | TASK-233; gate |
| -324 S | `csv` module instead of `write_csv` | G80 (70 failed) | red | TASK-233 |
| -325 S | `escape_cell` skipped for stdout and stderr | G80 (23 failed) | red | TASK-233 |
| -326 S | original verdict instead of the latest re-evaluation | G81 (12) | red | TASK-235 |
| -327 S | latest by `reevaluated_at`, not `reeval_id` | G81 (14) | red | TASK-235 |
| -328 S | `original_result` from the effective verdict | G80 (view part), G81 (12) | red | TASK-233, TASK-235 |
| -329 | not-run plugins left out | G81 (15) | red | TASK-235 |
| -330 | not-run name from the current catalog | G81 (13) | red | TASK-235 |
| -331 S | back-join without the job key (another scan's rows) | G81 (13); **G83** (15 items, no `other-scan`) | red | TASK-235; gate |
| -332 | score counts ERROR as FAIL | G81 (2) | red | TASK-240 |
| -333 | detail re-derives the state | G81 (2) | red | TASK-240 |
| -334 | CSV cap removed | G81 (2), G82 (1) | red | TASK-241, TASK-244 |
| -335 S | re-evaluate on `require_role("admin")` | G82 (TASK-232: 3; TASK-243: 3); **G83** (markers, refusals, sink outage) | red | TASK-232, TASK-243; gate |
| -336 S | `sink_gate=False` | G82 (2; 1); **G83** (markers, 15-minute row) | red | TASK-232, TASK-243; gate |
| -337 S | minimum role operator | G82 (2; 1); **G83** (markers, `operator:session` refusal) | red | TASK-232, TASK-243; gate |
| -338 | shipper's wake removed | G82 (2) | red | TASK-243 |
| -339 S | a second caller of `reevaluate_scan` (from the results route) | **G83** (one-writer static row; the read-route spy saw the INSERT) | red | gate (also TASK-243's -413, a second import, red in G82) |
| -340 | alert raised on re-evaluation | G82 (3) | red | TASK-243 |
| -341 S | retention deletes `agent_package` rows | G81 (4: refused by the grants); **G83** (static DELETE-target row; the scheduler run row: the packages step failed with permission denied) ; in G33 it stays green (54/54), as expected: those suites never run retention (see G33) | red | TASK-237; gate |
| -342 S | retention through the app pool: serve `retention_db=db` (-342), runner `run_retention(self._db, …)` (-342b) | G81 (3; 3); **G83** (serve wiring row; the scheduler run row) | red ×2 | TASK-245; gate |
| -343 S | audit rows deleted without a checkpoint | G81 (5) | red | TASK-242 |
| -344 S | f-string SQL in `result_reads.py` | **G1** (S608); **G83** (S608 row) | red | TASK-235; gate |
| -345 S | f-string SQL in `retention.py` | **G1** (S608); **G83** (S608 row) | red | TASK-237; gate |
| -346 S | `POST /scans/{id}/rerun` with an `execute` body | G34 (TASK-232: 4); **G34** (2 failed at this gate); **G83** (scan operations, command body) | red | TASK-232; gate |
| -347 S | checkpoint after the delete | G81 | red | TASK-242 |
| -348 S | audit delete by `at` (a hole) | G80 (4), G81 (2) | red | TASK-236, TASK-238 |
| -349 S | audit rows above the shipper's cursor | G80 (2), G81 | red | TASK-236, TASK-242 |
| -350 S | pending requests deleted | G81 (3) | red | TASK-237 |
| -351 | a scan deleted at 399 days | G80 (5) | red | TASK-236 |
| -352 | user tokens deleted at expiry | G80 (5) | red | TASK-236 |
| -353 S | clock guard removed | G81 (1 h ahead, 1 h behind) | red | TASK-242 |
| -354 | jobs deleted without the scan | G81 (3) | red | TASK-237 |
| -355 | re-evaluation lock not tried | G81 (repository 1; service race) | red | TASK-237, TASK-242 |
| -356 | retention not scheduled (serve; runner) | G81 (4; 4) | red | TASK-245 |
| -357 S | retention logs a deleted row's content (scan ids) | G81 (counts-only row); **G83** (the scheduler run row: a deleted scan id in the log) | red | TASK-242; gate |
| -358 S | results route logs the items at DEBUG | G82 (2); **G83** (the canary and token sweep row) | red | TASK-244; gate |
| -359 | route module imports a repository | G82 (1); **G83** (import-graph row) | red | TASK-244; gate |
| -360 S | `dangerouslySetInnerHTML` for stdout | G12 (eslint exit 1), G84 (1 failed / 14) | red | TASK-248 |
| -361 S | a `fetch(` in `ScanDetail.tsx` | G12 (eslint exit 1) | red | TASK-247 |
| -362 S | API-token fallback; token in `sessionStorage` | G84 (1 failed / 19); G12 (storage ban) | red ×2 | TASK-247 |
| -363 | `Score` 0 % for null | G84 (3 failed / 26) | red | TASK-239 |
| -364 | 0.9996 → "100.0 %" | G84 (6 failed / 26) | red | TASK-239 |
| -365 | `original_result` hidden | G84 (component 4 / 10, variant 2 / 10; screen 2 / 14) | red | TASK-239, TASK-248 |
| -366 | a viewer offered Run scan or Schedules | G84 (screen 1 / 15; shell and profile 1, 2, 1) | red | TASK-246, TASK-251 |
| -367 S | frozen `results.py` edited | G81 (PD-46 hash); **G83** (frozen-file row) | red | TASK-235; gate |
| -368 | correlated subquery on `scan_result_reeval` | G81 (EXPLAIN row only) | red | TASK-235 |
| -369 S | retention runs DDL (`DROP TABLE … scan_result_default`) | G81 (4: refused, not owner); **G83** (static DDL row; the scheduler run row: the scans step failed) | red | TASK-237; gate |
| -370 E2E | agent `.deb` whose runner returns no results | G85 (CHK-M11-302 ×3 FAIL, 16/19) | red | `work/reports/M11-e2e-test.md` (n5 r2, WSL dev run) |
| -371 E2E | results route leaves out a host | G85 (CHK-M11-302 u2204 FAIL, 18/19) | red | M11-e2e (n6) |
| -372 E2E | manager refuses the 0.1.0 heartbeat body | G86 (CHK-M11-305 heartbeat FAIL) | red | M11-e2e (TP-M11-19 r3) |
| -373 E2E | a FAIL row in the report | G87: e2e run **42594910837** red ("FAIL CHK-M11-303 all", "FAIL CHK-M11-309 sweep:a", "sweep:b") | red | main, 2026-11-09 (throwaway branch, deleted); local form red in M11-e2e |
| -374 E2E | an expected row removed | G87: e2e run **42594935136** red ("missing CHK-M11-302 viewer"; compat-a and compat-b green as controls) | red | main, 2026-11-09 (throwaway branch, deleted); local form red in M11-e2e |

Tester extras:

| CHK | Plant | Red in | Result | Source |
| --- | --- | --- | --- | --- |
| -375 S | a `<script>` hostname rendered as HTML (detail, results, table, picker) | G12 + G84 in each file | red | TASK-247, TASK-248, TASK-256 |
| -376 S | output column shown for viewer items | G84 (1 / 14) | red | TASK-248 |
| -377 | score formatter `floor(s*100*10)` | G84 (7 / 26) | red | TASK-239 |
| -378 | CSV download without `parseAs: "blob"` | G84 (1 / 15) | red | TASK-239 |
| -379 | tag check relaxed (a), (b) | G84 (1 / 37; 4 / 54) | red | TASK-256 |
| -390 | `import re` in a new module (`services/retention/task.py`) | **G1** (TID251); **G83** (re-ban row) | red | gate |
| -391 | untested function in `services/retention/task.py`, sized from the clean report | **G5** (84.9246 %, rc 2) | red | gate |
| -392 | route parameter without re-export | G6, M3 query allow-list (3) | red | TASK-232 |
| -393 | throwaway migration adding `ix_reeval_job` | **G19** (`test_migrated_schema_equals_the_spec`) | red | gate |
| -394 | tokens probe back on `expires_at` | G81 (3; 6) | red | TASK-237, TASK-242 |
| -395 | `FOR UPDATE SKIP LOCKED` back | G81 (3: permission denied) | red | TASK-237 |
| -396 | `<=` for `<`, each rule | G80 (2), G81 (3, 2, 2, 2, 2) | red | TASK-236, TASK-237 |
| -397 | `clock_doubt` with `>=` | G80 (1) | red | TASK-236 |
| -398 | `future_rows` with `>=` | G80 (1) | red | TASK-236 |
| -399 | prefix not capped; returns the cursor itself | G80 (4; 3) | red | TASK-236 |
| -400 | years as 365-day steps | G80 (6) | red | TASK-236 |
| -401 | `delete_requests` without `decision IS NOT NULL` | G81 (1) | red | TASK-237 |
| -402 | `delete_inventory_jobs` without `kind = 'inventory'` | G81 (3) | red | TASK-237 |
| -403 | `delete_through` with `<` | G81 | red | TASK-238 |
| -404 | `include_output` true for an unknown role | G80 (8) | red | TASK-233 |
| -405 | results keyset `>=` | G81 (5) | red | TASK-235 |
| -406 | scan list by `scan_id` only; `created_after` exclusive | G81 (9; 6) | red | TASK-234 |
| -407 to -412, -414 | re-evaluate: own alert, repository import, 404 echo, wake before commit, `PolicyDeleted` unmapped, shared lock, `allow_restricted=True` | G82 (6, 1, 1, 4, 2, 1, 5) | red | TASK-243 |
| -413 | a second import of `reevaluate_scan` | G82 (1) | red | TASK-243 |
| -415 to -421 | scan views: snapshot removed, decommissioned agents left out, `AgentNotFound` removed, host order, retry grouping, deleted policies filtered, `resolved_agents` in the target | G81 (1, 1, 1, 1, 2, 1, 3) | red | TASK-240 |
| -422 to -429 | results service: cap after the text, unbounded read, viewer statement reads output, `include_output` for viewer, `next_after` at `>=`, `limit` rows, snapshot removed, `ScanNotFound` for CSV | G81 (2, 1, 1, 16, 3, 7, 1, 1) | red | TASK-241 |
| -430, -431 | router: any scan id; any Run scan profile id | G84 (15; 8 / 148) | red | TASK-251 |
| -432, -433, -438 | double click; new key per send; host filter untrimmed | G84 (1 / 17; 1 / 17; 1 / 15) | red | TASK-246 |
| -434, -436 | Cancel for viewers; reload after a refusal | G84 (1 / 19; 4 / 19) | red | TASK-247 |
| -435 | edit always sends `cron` | G84 (4 / 17) | red | TASK-249 |
| -437 | CSV export drops the filters | G84 (1 / 14) | red | TASK-248 |
| -439, -440 | unknown stored target as All hosts; passed to `toTarget` | G84 (12; 2 / 68) | red | TASK-258 |
| -455 to -458 | read routes: raw-id cursor scopes, written-time scope, any-form cursor id, cursor position bounds, cap text, filename case, `AnchorGone` unmapped | G82 (1 each; 4; 2; 1, 1, 1) | red | TASK-244 |
| SEC-tok-user (gate) S | user-route parser accepts `bsa_`/`bse_` as API tokens | **G83** (token-group row: a `bsa_` whose hash a `user_token` row holds got 200; frozen-file row) | red | gate |
| SEC-tok-agent (gate) S | agent-route check accepts `bsk_`/`bsu_` | **G83** (token-group row: a `bsk_` whose hash an `agent` row holds pulled 200; frozen-file row) | red | gate |
| SEC-reads-operator-only (gate) | the five reads on `require_role("operator")` | **G83** (markers row) | red | gate |

CHK-M11-441 to -449 are unused ids. CHK-M11-450 to -454 and -459 are checks (TASK-245, TASK-244), not plants; all PASS in their reports.

**No gate lowered.** Since `6efe0fb`: `fail_under` stays 85 and `precision` went from 2 to 4 (TASK-255, stricter); the only workflow change is the new `e2e.yml`; `vite.config.ts` gained only `testTimeout: 20000` (TASK-257, no assertion changed); ruff, mypy, eslint, tsconfig and Prettier configurations are unchanged; the added test lines hold no `skip`, `xfail`, `.only` or `.todo` except the Windows-only `pytest.skip` guard of `test_serve_retention_linux.py`, the same as M9's `test_serve_scheduler_linux.py`, which never fires on Linux (G18: 0 skipped).
