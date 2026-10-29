# M8 test plan (evaluator: result evaluation and scoring)

Owner: tester (`tester-m8`). Written 2026-10-29 from `work/tasks.md` "M8 evaluator" (TASK-176 to TASK-185 acceptance tests, design notes D1 to D4, TP-M8-00 to TP-M8-14, gates G62 to G65, mutation table CHK-M8-320 to -364), `work/requirements.md` REQ-186 to REQ-205, `work/plans/M8-breakdown.md`, `TASK-178.md`, `TASK-182.md`, `TASK-185.md`, the approved answers in `work/open-questions.md` "M8" (#112 to #120, PD-38; #11, #12, #13 reused; user pre-approval in `work/decisions.md` 2026-10-29: every recommended answer applies), and the spec itself (TS §4.5 L585–L603, §5.2 scanning tables and grants L859–L938, L992–L1013, §8.3; SR §1.1 L87 and §2.4 L124–L160). Written **before any M8 product code was read**. Results go to [report.md](report.md).

`bm/` means `manager/bitscan_manager/`; `ev/` means `bm/services/evaluator/`; `mt/` means `manager/tests/`.

## Conventions

- Type: **CODE** = static gate, unit or property test on the tree (no database). **APP** = the real code against a real PostgreSQL 16 through the Testcontainers harness (M1 bootstrap from TS §5.2, then `bitscan-manager db migrate`).
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m8` (ruff, `ruff format`, `mypy --strict` only). **W** = WSL2 Ubuntu 24.04 with Docker, tester-m8 only: working copy `/root/bstest-m8-<label>` (tree copied without `.venv`, `node_modules`, `__pycache__`), own venv `/root/venv-m8` (`pip install --require-hashes -r manager/requirements-dev.txt`, then `pip install --no-deps -e <copy>/manager`), `PYTHONPATH` pinned to the copy, `CI=true` (nothing skipped), `BSTEST_RUN_LABEL=m8t-<label>`, every run under `timeout`. **Python tests run on W only.** Memory before a W run: Windows free ≥ 2,000 MB for one worker, ≥ 3,000 MB for `-n 2`; containers removed after each run. **CI** = GitHub Actions only.
- PostgreSQL rows connect as `bitscan_app` for product code. Scans, jobs, results and catalog rows that no M8 code writes are written by the test as **owner** (`bitscan_migrate` + `SET ROLE bitscan_owner`) through the TP-M8-01 builder.
- **Row checksum** = `md5(string_agg(t::text, '|' ORDER BY <pk>))` per table, read as owner. "Unchanged" means equal checksums for `scan_result` (parent and every partition), `scan`, `scan_job`, and, where named, `scan_result_reeval` rows that existed before.
- **Canary** = a fixed unique string `M8CANARY-<uuid4>` placed in stdout, stderr and the expected value (and in a pattern) of fixture rows; "leaves no trace" = absent from every `caplog` record (message and args), `capsys` out/err, every raised exception's `str()`/`repr()`, every audit `detail` and every `eval_detail` read back.
- **Time** is never waited out (decisions 2026-10-26). **Races** use two connections or threads held at a `threading.Barrier` or a held advisory lock, with a lock-wait probe on `pg_locks` / `pg_stat_activity` (`wait_event_type = 'Lock'`) polled at 20 ms with a 10 s bound; never a sleep for ordering.
- **Planted violations** are made in a throwaway copy (`/root/bstest-m8-mut-<id>` on W, `$TEMP/m8t-mut-<id>` on L for ruff and mypy rows), never in the worktree. The unmodified copy is green first. "Red" = non-zero exit **and** the named test fails for the planted reason.
- **Results are totals**: `passed/total`, plus failed, errors, skipped. A failing test is re-run alone by node id after the fix, as its own row (`1/1 passed`).
- Every expected value below comes from the spec or an approved answer, never from the implementation.

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Return codes | 0 PASS, 1 FAIL, 2 ERROR; nothing else is ever returned or stored | TS §4.5 L589–L593; SR §2.4 |
| `evaluate` signature | exactly `(operator, expected, stdout, exit_code, timed_out, truncated)` in that order | TS §4.5 L600; REQ-186 (2) |
| Operators | exactly the 14, same order as `importer.model.OPERATORS`; `EQUALS`, `equal`, `""` are not operators here (lowercased at import only) | SR §2.4; #11; REQ-192 (4) |
| Normaliser | every CRLF → LF, then trim `" \t\n\v\f\r"` at both ends; lone interior CR kept; U+00A0, U+2003, U+2028 kept; no case fold; no Unicode normalisation; applies to expected too | TS §4.5 L597; #115; REQ-187 |
| Number grammar | #13 (`values.parse_number`): decimal integer or float, optional sign; `1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `5 6`, `5\n6`, `٣` are not numbers; compared as exact `Decimal` | SR L153; #13; REQ-190 |
| RE2 | `values.compile_pattern` (adds `(?m)`), `search` semantics, `.` does not match `\n`; refused pattern or un-encodable stdout → ERROR `cannot evaluate` for `regex` **and** `not_regex` | SR L134; TS §4.5 L600; REQ-189 |
| Exit codes | ERROR: None `no exit code`, 126 `cannot run`, 127 `not found`, ≥ 128 or < 0 `killed by signal`; 0, 1, 2, 125 never decide | TS §4.5 L593, L598; #114; REQ-192 |
| `truncated` | true → ERROR `stdout truncated` for every operator; stderr-only truncation is not a separate case | #113; REQ-192 (2) |
| Detail vocabulary | exactly: `oversize`, `spool_overflow`, `runner_unavailable`, `timed out`, `no exit code`, `cannot run`, `not found`, `killed by signal`, `stdout truncated`, `cannot evaluate`, `stdout not numeric`; PASS/FAIL detail NULL | #112 (a); REQ-193 |
| Detail order | `oversize` → runner error → `timed out` → `no exit code` → `cannot run` → `not found` → `killed by signal` → `stdout truncated` → `cannot evaluate` → `stdout not numeric` (first match wins) | #112 (c) |
| Intake details | `INTAKE_DETAILS` = {`oversize`, `spool_overflow`, `runner_unavailable`}; kept as ERROR with the same detail on re-evaluation | #12; #118 (e) |
| Caps | UTF-8 bytes; stdout 65,536 passes, 65,537 `oversize`; stderr 16,384 passes, 16,385 `oversize`; strictly over; flags do not avoid it; `oversize` before runner error | TS §4.5 L599; #57; #116 |
| Runner `error` | `spool_overflow` / `runner_unavailable` → ERROR with that detail, `classify` not called; any other non-null value → ERROR `cannot evaluate` | #12; #112 (a) |
| `eval_spec` JSON | `{"plugins": [{"plugin_uuid", "name", "operator", "expected"}]}` in payload order; 1–5,000 entries; lowercase unbraced uuid, unique; operator one of 14; `name` 1–400 chars; `expected` 0–4,000 chars; all strings; no `execute`, no `timeout_s`; strict parser, fixed message quoting no input | #117; REQ-195 |
| SR §1.1 entry | `name` `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`, `operator` `equals`, `expected` `install ok installed`; stdout `install ok installed` PASS, `""` FAIL (exit 0 and exit 1) | SR L87; REQ-205 |
| Score | passed ÷ (passed + failed), unrounded, in [0, 1]; None when passed + failed = 0; errors and not run carried beside it, never in the ratio; negative count → `ValueError` | TS §4.5 L602; #120; REQ-196 |
| Effective verdict | latest `scan_result_reeval` by highest `reeval_id` for (job, plugin), else the original; original always returned beside it; `reevaluated_at` and list order irrelevant | TS §4.5 L601; #119; REQ-197 |
| Not run | plugins of the agent's original job payload (`retry_of IS NULL`) with no result in that job or its retry | TS §4.4 L577–L583; REQ-198 |
| Re-evaluation | one transaction; per-scan `pg_advisory_xact_lock`; definitions + version in one statement; one row per result whose plugin the current version lists; dropped plugins none; deleted policy `PolicyDeleted`; disabled allowed; unknown `ScanNotFound`; audit `scan.reevaluate`, actor `user:<id>`, target `scan:<scan_id>`, detail keys exactly {`policy_id`, `scan_policy_version`, `policy_version`, `rows_added`, `not_in_version`}; no alert; chunks ≤ 1,000 | TS §4.5 L601; #118; REQ-200, REQ-201 |
| Grants | `bitscan_app` cannot UPDATE/DELETE `scan_result` (parent, current partition, default partition) or `scan_result_reeval` | TS §5.2 L1005–L1006; REQ-204 (1) |

## Gate map

| Gate | Checks |
| --- | --- |
| G1–G4 ruff (S608, `re` ban), ruff format, mypy --strict, hashed locks | CHK-M8-300, -301; plants -320, -349, -350 |
| G5 services coverage ≥ 85 % incl. `services/evaluator` (W) | CHK-M8-302 |
| G6 OpenAPI byte-identical, G34 route walk (no new route) | CHK-M8-303, -304 |
| G18 full W run, 0 skipped | CHK-M8-305 |
| G62 evaluator unit suite | CHK-M8-001 to -099, -100 to -129 |
| G63 property suite | CHK-M8-130 to -139 |
| G64 PostgreSQL integration | CHK-M8-140 to -219 |
| G65 security and boundary suite | CHK-M8-220 to -259 |

## TP-M8-01: PostgreSQL fixture builder (REQ-198 to REQ-201, REQ-204) — `mt/evaluator_pg_fixtures.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-140 | APP | Builder writes, as owner: a family, a policy (version, enabled/disabled, soft-deleted variant), plugins and `policy_plugin` rows; agents; a `scan`; original and retry `scan_job` rows with a TS §6.5 payload (`plugins: [{plugin_uuid, execute, timeout_s}]`) and a #117 `eval_spec`; `scan_result` rows with `job_created_at = scan_job.created_at` (the trigger accepts them) and the four NOT NULL snapshots; `scan_result_reeval` rows with chosen `reeval_id` order. A self-test reads every row back as `bitscan_app` | W |
| CHK-M8-141 | APP | Row-checksum helper is sensitive: changing one byte of one `scan_result` column (as owner) changes the checksum; equal trees give equal checksums | W |
| CHK-M8-142 | APP | Jobs can be created in two different months (results in two partitions) and a retry job can carry the plugins missing from the original | W |
| CHK-M8-143 | CODE | Canary helper: one `M8CANARY-…` value per run, injected into stdout, stderr, expected and a regex pattern of fixture rows | W |

## TP-M8-02: model and normaliser (TASK-176; REQ-187, REQ-193, REQ-202) — `mt/test_evaluator_model.py`, `mt/test_evaluator_normalise.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-001 | CODE | `typing.get_args(model.Operator)` equals `importer.model.OPERATORS` element for element, in order (14 values) | W |
| CHK-M8-002 | CODE | `PASS == 0`, `FAIL == 1`, `ERROR == 2`; `get_args(VerdictCode) == (0, 1, 2)` | W |
| CHK-M8-003 | CODE | `{d.value for d in Detail}` is exactly the eleven #112 strings; every value is lowercase ASCII; `INTAKE_DETAILS` is exactly {oversize, spool_overflow, runner_unavailable} and is immutable (frozenset) | W |
| CHK-M8-004 | CODE | `STDOUT_CAP == 65536`, `STDERR_CAP == 16384` | W |
| CHK-M8-005 | CODE | `Verdict(0, None)`, `Verdict(1, None)`, and `Verdict(2, d)` for each of the 11 details construct; `Verdict(0, Detail.TIMED_OUT)`, `Verdict(1, Detail.OVERSIZE)`, `Verdict(2, None)`, `Verdict(3, None)`, `Verdict(-1, None)`, `Verdict(2, "timed out")` if not a `Detail` member, `Verdict(2, "bogus")`, `Verdict(True, None)` (bool is not a verdict code, if the model refuses it; otherwise reported) raise `ValueError` (REQ-193 (4), CHK-M8-337/-364) | W |
| CHK-M8-006 | CODE | `Verdict` and `PluginSpec` are frozen (assignment raises) | W |
| CHK-M8-007 | CODE | `ResultLike`: a `ResultItem` from `bm/api/agent/schemas.py` type-checks as `ResultLike` under `mypy --strict` (a typed probe file in `mt/` checked by mypy) | L, W |
| CHK-M8-008 | CODE | `ev/__init__.py` holds only a docstring (AST: one `Expr` string node, no import, no assignment) | W |
| CHK-M8-010 | CODE | REQ-187 (1) table: `"install ok installed\r\n"`, `"\r\n  install ok installed \n"`, `"install ok installed"` → same text; `"a\r\nb"` → `"a\nb"`; `"a\rb"` unchanged; `"\u00a0x"`, `"x\u00a0"`, `"\u2003x"`, `"x\u2003"`, `"\u2028x"` unchanged; `"\v\fx\t"` → `"x"`; `"\r"` → `""`; `"\r\r\n"` → `""`; `"a\r\r\nb"` → `"a\r\nb"`; interior spaces and tabs kept; `"ABC"` unchanged (no case fold); `"e\u0301"` vs `"\u00e9"` not unified (no NFC) | W |
| CHK-M8-011 | CODE | CRLF inputs are in-code literals (the test file contains no CR byte: a guard test reads its own bytes) | W |
| CHK-M8-012 | CODE | `normalise` is idempotent on 10,000 hypothesis strings (incl. surrogates, CR, VT, FF, U+00A0) (REQ-187 (2)) | W |
| CHK-M8-013 | CODE | Every char the result trims is in `" \t\n\v\f\r"` and every other char at an edge survives (hypothesis over `str` with all of `\x1c-\x1f`, `\x85`, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF at the edges: kept) | W |
| CHK-M8-014 | CODE | Pure-module imports (model, normalise): no `logging`, `re`, `db`, `repositories`, `api`, `psycopg` (AST) | W |

## TP-M8-03: operators (TASK-177; REQ-188 to REQ-191) — `mt/test_evaluator_operators.py`

`compare(op, expected, stdout)` on already-normalised text; signals `NotNumeric` and `CannotEvaluate`.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-020 | CODE | Dispatch covers exactly the 14 (each op in `importer.model.OPERATORS` returns a bool for a valid input; any other string raises `CannotEvaluate`: `EQUALS`, `Equals`, `equal`, `""`, `" equals"`, `equals\x00`, `regexp`, `!=`, `eq ` ) | W |
| CHK-M8-021 | CODE | `equals` ≥ 4 rows: match; no match; multi-line stdout equal; case difference FAIL; non-ASCII match (`"Ünïcødé ✓"`); prefix-only FAIL (`"abc"` vs `"abcd"`) | W |
| CHK-M8-022 | CODE | `not_equals` ≥ 4 rows: differ → True; identical → False; case difference → True; multi-line; non-ASCII; empty vs non-empty | W |
| CHK-M8-023 | CODE | `contains` ≥ 4 rows: expected at start, end, middle; absent; case difference False; non-ASCII; REQ-188 (2) `PermitRootLogin no` in a multi-line `sshd_config` dump → True, `permitrootlogin no` → False; empty expected (forced) → True (`"" in s`) | W |
| CHK-M8-024 | CODE | `not_contains` ≥ 4 rows: absent → True; present → False; REQ-188 (3) `nullok` vs a PAM line with `nullok_secure` → False (substring); case difference → True; non-ASCII | W |
| CHK-M8-030 | CODE | REQ-189 (1): `^MaxAuthTries\s+[1-4]$` vs `"Port 22\nMaxAuthTries 3\nX"` True, vs `MaxAuthTries 6` False; `not_regex` `^\s*PermitEmptyPasswords\s+yes` vs `PermitEmptyPasswords no` True and vs `PermitEmptyPasswords yes` False | W |
| CHK-M8-031 | CODE | REQ-189 (2): `foo` vs `xfoo` True (search); `^foo$` vs `"a\nfoo\nb"` True (multiline); `^foo` vs `xfoo` False | W |
| CHK-M8-032 | CODE | REQ-189 (3): `^a.b$` vs `"a\nb"` False; `a.b` vs `a\nb` False | W |
| CHK-M8-033 | CODE | REQ-189 (4): `(?=x)`, `(?!x)`, `(?<=x)`, `(a)\1`, `[`, `(`, `a{100000}` (RE2 limit, if refused) under `regex` and `not_regex` raise `CannotEvaluate`, never return a bool (false-PASS hunt for `not_regex`) | W |
| CHK-M8-034 | CODE | Lone surrogate (`"\ud800"`) in stdout under `regex` and `not_regex` raises `CannotEvaluate`, not `UnicodeEncodeError` | W |
| CHK-M8-035 | CODE | REQ-189 (5): `(a*)*b` vs 65,536 `a` finishes < 1 s (wall clock bound, measured) under `regex` and `not_regex` | W |
| CHK-M8-036 | CODE | REQ-189 (6): a spy on `values.compile_pattern` sees one call per regex compare; a spy that raises on `re2.compile` / `re.compile` called from `operators` is never hit; `operators.py` source has no `import re` / `re2` (AST) | W |
| CHK-M8-037 | CODE | Case-sensitive regex: `^permitrootlogin` vs `PermitRootLogin no` False; `(?i)` inline flag in the pattern is honoured (it is the author's choice) | W |
| CHK-M8-040 | CODE | REQ-190 (1) PASS rows: `eq 0`/`0`, `eq 0`/`-0`, `eq 1`/`1.0`, `gt 13`/`14`, `ge 14`/`14`, `lt 91`/`90.999`, `eq 7`/`007`; FAIL rows: `le 90`/`90.0001`, `ne 0`/`+0`; plus each op both ways at the boundary (`gt 14`/`14` False, `lt 14`/`14` False, `ge`/`le` equal True, `ne 1`/`2` True, negative numbers `lt -1`/`-2` True) | W |
| CHK-M8-041 | CODE | REQ-190 (2): `eq 9007199254740992` vs `9007199254740993` False and `gt` True; 5,000-digit stdout vs 5,000-digit expected differing in the last digit compares correctly for all six ops (no `int()` limit, no exception); `eq 0.1`/`0.10` True; `eq 0.30000000000000004`/`0.3` False | W |
| CHK-M8-042 | CODE | REQ-190 (3): stdout `abc`, `""`, `1e3`, `1E3`, `nan`, `NaN`, `inf`, `-inf`, `Infinity`, `1_000`, `0x10`, `.5`, `5.`, `5 6`, `5\n6`, `٣`, `１` (full-width), `+`, `-`, `--1`, `1-` raise `NotNumeric` for each of `eq ne gt ge lt le` (`ne` never True) | W |
| CHK-M8-043 | CODE | REQ-190 (5): expected `abc`, `""`, `1e3`, `nan` with each numeric op raise `CannotEvaluate`; expected checked before stdout (expected `abc` + stdout `abc` → `CannotEvaluate`) | W |
| CHK-M8-044 | CODE | Numeric ops never call `float()` or `int()` on input: spy patches in `operators` namespace (if names are looked up there) or a source AST check | W |
| CHK-M8-050 | CODE | REQ-191 (1) on normalised input: `""` empty; `"0"`, `"x"`, `"\u00a0"` not empty (after `normalise`: `"\n"`, `" \r\n\t"` → `""` → empty; `" "` → `""`, see note); (3) expected `"something"` does not change `empty`/`not_empty` | W |
| CHK-M8-051 | CODE | `compare` raises only `NotNumeric`/`CannotEvaluate`: hypothesis over (any str op, any str expected, any str stdout) 5,000 cases | W |

Note on REQ-191 (1): REQ-191 says `" "` (#115) is "not empty"; but `" "` (U+0020) normalises to `""` under #115. The row is read as the #115 reference meaning U+00A0 (`"\u00a0"`), which #115 keeps. **Asked of `main` (Q1 below)** before the test is final.

## TP-M8-04: `classify` and `evaluate` (TASK-178; REQ-186, REQ-192, REQ-193, REQ-205) — `mt/test_evaluate.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-060 | CODE | REQ-186 (2): `inspect.signature(evaluate)` and `classify` parameter names are exactly `operator, expected, stdout, exit_code, timed_out, truncated`, in order, all positional-or-keyword, no defaults | W |
| CHK-M8-061 | CODE | REQ-186 (1): for every row of CHK-M8-020 to -050 and -062 to -072 run through `classify`/`evaluate`, `evaluate(...) == classify(...).code` and code ∈ {0, 1, 2} | W |
| CHK-M8-062 | CODE | REQ-192 (1): `equals x`/`x`: exit 0, 1, 2, 125 → PASS; 126 `cannot run`, 127 `not found`, 128, 129, 137, 255, 256, 2³¹−1 `killed by signal`; −1, −2³¹ `killed by signal`; None `no exit code` | W |
| CHK-M8-063 | CODE | REQ-192 (2): `timed_out` true with exit 0 and passing output → ERROR `timed out`, for each of the 14 operators with an input that would PASS | W |
| CHK-M8-064 | CODE | REQ-192 (2): `truncated` true with passing output → ERROR `stdout truncated`, for each of the 14 operators (incl. `contains` with the expected text inside the kept stdout) | W |
| CHK-M8-065 | CODE | REQ-192 (3): exit 1, stdout `""`, `empty` → PASS; exit 1, `""`, `not_empty` → FAIL (exit never decides) | W |
| CHK-M8-066 | CODE | REQ-192 (4): operators `EQUALS`, `equal`, `""` → ERROR `cannot evaluate` | W |
| CHK-M8-067 | CODE | REQ-193 (1) one case per evaluation detail: `timed out`, `no exit code`, `cannot run`, `not found`, `killed by signal`, `stdout truncated`, `cannot evaluate`, `stdout not numeric` (the intake three in CHK-M8-100 to -106) | W |
| CHK-M8-068 | CODE | REQ-193 (2) order: timed out + exit 137 + truncated → `timed out`; exit 127 + truncated → `not found`; truncated + non-numeric stdout under `eq` → `stdout truncated`; None + truncated → `no exit code`; 126 + timed_out → `timed out`; unknown operator + non-numeric stdout → `cannot evaluate`; numeric op with bad expected + bad stdout → `cannot evaluate`; exit 128 + bad operator → `killed by signal` | W |
| CHK-M8-069 | CODE | REQ-193 (3): every PASS/FAIL in the tables has detail None | W |
| CHK-M8-070 | CODE | REQ-187 (3), (5) through `classify`: `equals` stdout `Install ok installed` vs `install ok installed` FAIL; expected `"x\r\n"` with stdout `x` PASS; expected `"  x\t"` with stdout `"\r\nx\r\n"` PASS; stdout `" 42\r\n"` `eq 42` PASS (REQ-190 (4)) | W |
| CHK-M8-071 | CODE | Normaliser runs before comparison for every family: `regex ^x$` vs `"x\r\n"` PASS; `empty` vs `"\r\n"` PASS; `not_empty` vs `" \t"` FAIL; stdout `"a\r\nb"` with `regex ^a$` PASS (CRLF→LF before `$`) | W |
| CHK-M8-072 | CODE | False-PASS hunt through `classify`: `not_regex` with refused patterns, `not_regex` with lone-surrogate stdout, `ne` with non-numeric stdout, `ne` with non-numeric expected, `not_equals`/`not_contains`/`not_empty` with unknown-operator spelling (`NOT_EQUALS`) — never PASS | W |
| CHK-M8-073 | CODE | REQ-205 (1): `evaluate("equals", "install ok installed", "install ok installed", 0, False, False) == 0`; stdout `""` exit 0 → 1; `"install ok installed\n"` exit 0 → 0; `""` exit 1 → 1 | W |
| CHK-M8-074 | CODE | REQ-186 (4): two calls same inputs same `Verdict`; no log record (caplog at DEBUG on root), nothing on stdout/stderr (capsys), and a `sys.addaudithook` probe sees no `open`, `socket.connect`, `socket.socket`, `subprocess.Popen`, `os.system` during 200 calls covering every operator and ERROR path | W |
| CHK-M8-075 | CODE | `classify` details never contain the stdout, expected, or exit code (canary in all strings, detail ∈ the 11 constants) (REQ-193, CHK-M8-363) | W |
| CHK-M8-076 | CODE | `evaluate`/`classify` read no clock: `time.time`, `time.monotonic`, `datetime.now` patched to raise; all paths still give a verdict | W |
| CHK-M8-077 | CODE | Huge inputs: 1 MiB stdout and expected for each operator return within 2 s (no quadratic path); 65,536 newlines under `regex ^$` | W |

## TP-M8-05: `result_verdict` (TASK-179; REQ-194, REQ-205 (2)) — `mt/test_evaluator_verdict.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-100 | CODE | REQ-194 (1) stdout bytes: 65,536 ASCII bytes passes the cap (verdict from `classify`); 65,537 → `oversize`; 21,845 × `"€"` (3 bytes) + `"a"` = 65,536 bytes passes; 21,846 × `"€"` = 65,538 bytes (21,846 chars) → `oversize` (chars < cap, bytes > cap); 16,384 × `"😀"` (4 bytes) = 65,536 passes, one more `"a"` → `oversize` | W |
| CHK-M8-101 | CODE | REQ-194 (1) stderr bytes: 16,384 passes, 16,385 → `oversize`; 5,462 × `"€"` = 16,386 bytes → `oversize` (5,462 chars); `truncated=False`, `timed_out=False`, `error=None` do not avoid it; `truncated=True` with 65,537 → `oversize` not `stdout truncated` | W |
| CHK-M8-102 | CODE | Lone surrogate in stdout or stderr: size counted without raising (`utf8_size("\ud800") == 3` if `surrogatepass`; whatever it is, no exception and the cap decision is consistent at 65,536/65,537) | W |
| CHK-M8-103 | CODE | REQ-194 (2): oversize + `error` `spool_overflow` → `oversize`; oversize + `runner_unavailable` → `oversize`; oversize stderr only + timed_out → `oversize` | W |
| CHK-M8-104 | CODE | REQ-194 (3): `error` `spool_overflow` with passing stdout → ERROR `spool_overflow`; `runner_unavailable` → ERROR `runner_unavailable`; a spy replacing `classify` in the verdict module (and `evaluate.classify`) records zero calls; with `error=None` the spy records exactly one call with `(spec.operator, spec.expected, stdout, exit_code, timed_out, truncated)` | W |
| CHK-M8-105 | CODE | Unknown runner error value (`"bogus"`, `""`) → ERROR `cannot evaluate`, `classify` not called (#112 (a)) | W |
| CHK-M8-106 | CODE | REQ-194 (4): stderr of 16,384 bytes of `"ERROR: permission denied\n"` repeated never changes a PASS; stderr containing the expected value never turns a FAIL into PASS (stderr not compared) | W |
| CHK-M8-107 | CODE | REQ-194 (5) and REQ-205 (2): the spec entry from `build_eval_spec` on the SR §1.1 plugin, with stdout `install ok installed` exit 0 → PASS; `""` exit 0 → FAIL; `""` exit 1 → FAIL; `"install ok installed\n"` → PASS | W |
| CHK-M8-108 | CODE | REQ-194 (6): a typed probe passes an `api.agent.schemas.ResultItem` to `result_verdict` under `mypy --strict`; `verdict.py` imports nothing from `api` (AST) | L, W |
| CHK-M8-109 | CODE | For every non-intake row, `result_verdict(spec, r) == classify(spec.operator, spec.expected, r.stdout, r.exit_code, r.timed_out, r.truncated)` | W |

## TP-M8-06: `eval_spec` (TASK-180; REQ-195) — `mt/test_eval_spec.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-110 | CODE | REQ-195 (1): round trip `parse_eval_spec(json.loads(json.dumps(build_eval_spec(x)))) == x` for 1, 2, 5,000 plugins with non-ASCII names and expected values; `build` output is JSON-ready (`json.dumps` with `allow_nan=False` succeeds; only dict/list/str values); order kept | W |
| CHK-M8-111 | CODE | REQ-195 (2) one `EvalSpecError` each: not an object (list, str, int, None); missing `plugins`; extra top key; `plugins` not a list; empty list; 5,001 entries (5,000 accepted); entry not an object; missing/extra entry key (each of the four missing; `execute`, `timeout_s` extra); duplicate `plugin_uuid`; uppercase uuid; braced uuid; urn form; no hyphens; not a uuid; operator outside the 14 (`EQUALS`, `""`); `name` `""`; `name` 401 chars (400 accepted); `expected` 4,001 chars (4,000 and `""` accepted); a non-string value for each of the four (int, None, list, bool) | W |
| CHK-M8-112 | CODE | The `EvalSpecError` message is identical for every refused input (or drawn from a fixed set) and holds none of the input (canary in name, expected, uuid-like strings, keys) | W |
| CHK-M8-113 | CODE | REQ-195 (3): `EvalSpec.get(uuid)` returns the entry for each listed uuid and None for an unknown uuid | W |
| CHK-M8-114 | CODE | REQ-195 (4): built from the SR §1.1 plugin: `name` `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`, `operator` `equals`, `expected` `install ok installed`; no key `execute` or `timeout_s` anywhere in the JSON (recursive key walk) | W |
| CHK-M8-115 | CODE | Lengths counted in characters as the DB `VARCHAR(400)` does: a 400-char non-ASCII name (1,200 bytes) is accepted; a lone-surrogate name is refused or accepted without crashing (`json.dumps` would not encode it: reported) | W |
| CHK-M8-116 | CODE | `parse_eval_spec` never raises anything but `EvalSpecError` (hypothesis over JSON-like values, 2,000 cases) | W |

## TP-M8-07: score and effective rule (TASK-181; REQ-196, REQ-197 (1), (2)) — `mt/test_evaluator_score.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-120 | CODE | REQ-196 (1): (3,1,5,7) → 0.75 with errors 5, not run 7; (0,0,4,2) → None; (0,3,0,0) → 0.0 and `is not None`; (1,0,0,0) → 1.0; (1,2,0,0) → exactly 1/3 (unrounded) | W |
| CHK-M8-121 | CODE | REQ-196 (2): each of the four counts negative → `ValueError` | W |
| CHK-M8-122 | CODE | REQ-197 (1): no reeval → original code and detail, reeval fields None; ids 5, 9, 7 (every permutation, and with `reevaluated_at` reversed / equal) → id 9's code and detail; original code and detail returned unchanged beside it | W |
| CHK-M8-123 | CODE | REQ-197 (2): rows for another plugin or another job (same plugin) are ignored, even with a higher id | W |
| CHK-M8-124 | CODE | Effective of an ERROR original re-evaluated to PASS is PASS with detail None; of a PASS original re-evaluated to ERROR carries the reeval detail | W |

## TP-M8-08: property suite (REQ-186, -187, -190, -195, -196, -203) — `mt/test_evaluator_property.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-130 | CODE | REQ-186 (3): ≥ 10,000 hypothesis inputs (operators: the 14, case variants, random text, `""`; strings with lone surrogates, CR, NUL; exit codes over [−2³¹, 2³¹−1] and None; both booleans): no exception, code ∈ {0,1,2}, detail None iff code ∈ {0,1}, `evaluate == classify.code` | W |
| CHK-M8-131 | CODE | Normaliser idempotence and trim-set property (CHK-M8-012, -013) | W |
| CHK-M8-132 | CODE | `Decimal` oracle: for generated #13 number strings a, b (sign, leading zeros, long digits, fractional), each numeric op equals the `Decimal(a) <op> Decimal(b)` oracle; equal values in different spellings (`1`, `1.0`, `01`, `+1`) are `eq` | W |
| CHK-M8-133 | CODE | `evaluate`, `classify` and `result_verdict` agree on codes for inputs inside the caps with `error=None` | W |
| CHK-M8-134 | CODE | Score bounds: None iff passed + failed = 0, else in [0, 1]; errors and not run never change it | W |
| CHK-M8-135 | CODE | `eval_spec` round trip for generated specs (1–50 plugins per example, plus one 5,000-plugin case in CHK-M8-110) | W |
| CHK-M8-136 | CODE | Exit-code monotone rule: for random int `e` with no flags and a passing input, ERROR iff `e is None or e < 0 or e in (126, 127) or e >= 128` | W |

## TP-M8-09: results repository (TASK-182; REQ-197, REQ-198) — `mt/test_results_repo_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-150 | APP | REQ-198 (1a) as `bitscan_app`: `effective_results` returns exactly the scan's results (original and retry jobs), each with agent, original verdict and effective verdict; with no reeval the effective equals the original and reeval fields are None | W |
| CHK-M8-151 | APP | Effective = highest `reeval_id` (ids inserted out of order by owner with explicit ids 5, 9, 7 and `reevaluated_at` reversed); returned with that row's `policy_version`, `reevaluated_by`, `reevaluated_at` | W |
| CHK-M8-152 | APP | REQ-198 (1b) counts: host A all four kinds (2 PASS, 1 FAIL, 1 ERROR, 1 not run); host B original missing plugins that the retry holds (counted once, not run 0); host C job `queued`, no results (all not run); host D FAIL re-evaluated to PASS (counted PASS); host E all ERROR | W |
| CHK-M8-153 | APP | REQ-198 (2): a second scan with results for the same agents and plugins never appears in either function | W |
| CHK-M8-154 | APP | REQ-198 (3): a re-evaluation row of another scan's job for the same plugin, with a higher id, is ignored | W |
| CHK-M8-155 | APP | Not run uses only original jobs' payload: a retry payload's plugins are not double counted; a planted duplicate result (original and retry both hold plugin P, a defect M9 must prevent) is counted twice, not hidden (TASK-182 plan §3) | W |
| CHK-M8-156 | APP | Results in two partitions (jobs created in different months) are both read | W |
| CHK-M8-157 | APP | Unknown scan → `[]` for both; scan with jobs but no results → `effective_results` `[]` and counts all not run | W |
| CHK-M8-158 | APP | REQ-198 (5): `EXPLAIN` of the counts and the effective statements shows `scan_result_reeval` scanned exactly once and no SubPlan / correlated Nested Loop inner side on it | W |
| CHK-M8-159 | APP | Statement spy: each call issues exactly one statement and it is a SELECT (or WITH … SELECT); parameters are bound (no scan id text in the SQL string) | W |
| CHK-M8-160 | APP | Inventory jobs of the same agent are ignored (only `kind = 'compliance'`) | W |

## TP-M8-10: re-evaluation repository (TASK-183; REQ-200, REQ-201) — `mt/test_reeval_repo_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-170 | APP | As `bitscan_app` with only the TS §5.2 grants: `lock_scan`, `current_definitions`, `stored_results`, `insert_reevals` each work; `lock_scan` of an unknown id returns None | W |
| CHK-M8-171 | APP | `current_definitions` is one statement (statement spy) and returns the current version, `deleted` flag and exactly the listed plugins' (operator, expected); a plugin owned by the policy but not in `policy_plugin` is not listed | W |
| CHK-M8-172 | APP | `stored_results(chunk=k)` for k ∈ {1, 3, 1000} over 2,500 results: every chunk ≤ k, every result exactly once, the original `eval_detail` carried; uses a server-side (named) cursor (`pg_cursors` shows it during iteration) | W |
| CHK-M8-173 | APP | `insert_reevals` of N rows adds exactly N (`count(*)` delta), with the given `policy_version`, `reevaluated_by`, codes and details; N = 0 adds 0 | W |
| CHK-M8-174 | APP | Lock: two sessions `lock_scan` on one scan serialise (second waits on `advisory` lock until the first commits; probe on `pg_locks`); two different scans do not wait; the lock is released at rollback | W |
| CHK-M8-175 | APP | Statement spy: no UPDATE, DELETE, `FOR UPDATE`/`FOR SHARE` in any function | W |
| CHK-M8-176 | CODE | ruff S608 passes on `bm/repositories/reeval.py`; planted f-string red (CHK-M8-350) | L |

## TP-M8-11: host scores service (TASK-184; REQ-197 (3), REQ-199) — `mt/test_scores_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-180 | APP | REQ-199 (1): the CHK-M8-152 fixture gives the expected score per host: A 2/3, B per its rows, C None (queued), D per its rows, E None (all ERROR); counts carried | W |
| CHK-M8-181 | APP | REQ-199 (2): adding a late result row (owner) changes the next call's score; then adding a re-evaluation row changes it again | W |
| CHK-M8-182 | APP | REQ-199 (3): unknown `scan_id` → `[]` | W |
| CHK-M8-183 | APP | REQ-199 (4): statement spy sees only SELECT | W |
| CHK-M8-184 | APP | REQ-197 (3): 200 random sets (random hosts, plugins, originals, reeval rows across jobs and scans with random ids): `effective_results` and `effective()` give the same code and detail for every result | W |

## TP-M8-12: re-evaluation service (TASK-185; REQ-200, REQ-201, REQ-202, REQ-204) — `mt/test_reevaluate_pg.py`, `mt/test_reevaluate_race_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-190 | APP | REQ-200 (1): 6 results (PASS, FAIL, `stdout not numeric`, `oversize`, `runner_unavailable`, a since-dropped plugin) after an owner-made "import" bumping the version, changing one ExpectedResult and one Operator, and dropping one plugin from `policy_plugin`: 5 rows with the expected new verdicts, intake errors unchanged, `policy_version` new, `reevaluated_by` the user; none for the dropped plugin; `ReevalResult` counts `rows_added=5`, `not_in_version=1` | W |
| CHK-M8-191 | APP | REQ-200 (2): `scan_result` checksums (parent and each partition) identical before and after; pre-existing `scan_result_reeval` rows identical | W |
| CHK-M8-192 | APP | REQ-200 (3): a second run adds 5 more rows; `effective_results` then shows the second run's verdicts | W |
| CHK-M8-193 | APP | REQ-200 (4): audit entry action `scan.reevaluate`, actor `user:<id>`, target `scan:<scan_id>`, detail keys exactly the #118 (g) five with the right values; chain verifies (`audit verify` or the M1 verifier); no alert entry or alert metric | W |
| CHK-M8-194 | APP | REQ-200 (5): deleted policy → `PolicyDeleted`; unknown id → `ScanNotFound`; each with zero rows and no audit entry | W |
| CHK-M8-195 | APP | REQ-200 (6): fault injected after the first chunk's insert (chunk forced small, the second `insert_reevals` raises) → no row, no audit entry; `wake` not called | W |
| CHK-M8-196 | APP | REQ-200 (7): a scan with no results → audit entry with `rows_added 0`, no row | W |
| CHK-M8-197 | APP | REQ-200 (8): a disabled policy's scan is re-evaluated normally | W |
| CHK-M8-198 | APP | REQ-200 (9): statement spy sees no UPDATE or DELETE (and no TRUNCATE) | W |
| CHK-M8-199 | APP | Intake details kept for all three (`oversize`, `spool_overflow`, `runner_unavailable`) even when the current Operator would PASS on the stored stdout (`empty` on an empty stdout) | W |
| CHK-M8-200 | APP | `wake` is called once, only after commit (`on_commit`); not called on rollback | W |
| CHK-M8-201 | APP | Re-evaluation uses the stored `exit_code`, `timed_out`, `truncated` (a stored timed-out row stays `timed out` even when the new expected matches) | W |
| CHK-M8-210 | APP | REQ-201 (1): two concurrent re-evaluations of one scan (barrier): the second waits for the first (lock probe), both commit, every result's latest row comes from the second (higher ids, second run's verdicts after a definitions change between the runs) | W |
| CHK-M8-211 | APP | REQ-201 (2): an import thread (owner, one transaction: bump version, change an ExpectedResult) released by a barrier between lock and definitions, and again between definitions and results: no row records one version while using the other's definitions | W |
| CHK-M8-212 | APP | REQ-201 (3): a result inserted (owner, second session) after the re-evaluation's first fetch and before commit gets no row; the next run includes it | W |
| CHK-M8-213 | APP | REQ-201 (4): 20,000 results re-evaluated with peak `tracemalloc` under 64 MiB; chunk spy sees ≤ 1,000 per chunk | W |
| CHK-M8-214 | APP | REQ-201 (5): re-evaluations of two different scans do not wait for each other (both hold their lock at the same barrier) | W |

## TP-M8-13: security and boundaries (REQ-189, REQ-202, REQ-204) — `mt/test_security_m8.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-220 | CODE | REQ-202 (1): import graph per pure module (`model`, `normalise`, `operators`, `evaluate`, `verdict`, `eval_spec`, `score`): no import (direct, or transitively inside `bm`) of `bm.db`, `bm.repositories`, `bm.api`, `psycopg`, `bm.services.importer` other than `importer.model` and `importer.values`; no `logging`, no `re` | W |
| CHK-M8-221 | CODE | The two services import no `bm.api` and no `repositories.catalog*` (re-evaluation reads definitions only through `repositories.reeval`) | W |
| CHK-M8-222 | APP | REQ-202 (2): canary run over the unit paths and the PostgreSQL service paths (`effective_results`, `host_counts`, `scan_host_scores`, `reevaluate_scan` incl. `PolicyDeleted`, fault injection): canary in no log record, exception text, audit `detail` or `eval_detail` | W |
| CHK-M8-223 | CODE | REQ-202 (3): no `logging`/`logger.*` call in `ev/` formats a result field (AST: logging calls' args never reference `stdout`, `stderr`, `expected`, `pattern`, `result.*`) | W |
| CHK-M8-224 | CODE | No `import re` / `from re` anywhere under `ev/` and the two new repositories; ruff config bans `re` for these paths (G1) | L, W |
| CHK-M8-225 | APP | REQ-204 (1) grant probes as `bitscan_app`: UPDATE and DELETE on `scan_result` (parent, current-month partition, default partition) and UPDATE and DELETE on `scan_result_reeval` each raise `InsufficientPrivilege`; TRUNCATE on both refused | W |
| CHK-M8-226 | CODE | No new route: route walk (G34) and OpenAPI export unchanged | W |
| CHK-M8-227 | CODE | `eval_spec` never in the agent payload: `build_eval_spec` output has no `execute`/`timeout_s`, and the M3 job-pull schema has no `operator`/`expected` field (contract unchanged) | W |
| CHK-M8-228 | CODE | No migration added by M8 (`db/migrations` file list equals main `67a6dfa`); schema-diff test still green | W |

## Gate rows (TP-M8-14)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M8-300 | CODE | G1/G2: `ruff check manager && ruff format --check manager` green | L |
| CHK-M8-301 | CODE | G3: `mypy --strict --config-file manager/pyproject.toml manager` green; G4 `pip install --require-hashes` | L, W |
| CHK-M8-302 | APP | G5: coverage of `bm/services/` ≥ 85 % incl. `services/evaluator` (W full run) | W |
| CHK-M8-303 | CODE | G6: OpenAPI export byte-identical to the committed document | W |
| CHK-M8-304 | CODE | G34: `pytest mt/test_invariants_m3.py` | W |
| CHK-M8-305 | APP | G18: full manager suite, 0 skipped, `-n 2` | W |
| CHK-M8-306 | CODE | G62 unit suite list runs green; G63 property suite green | W |
| CHK-M8-307 | APP | G64 PostgreSQL suite green | W |
| CHK-M8-308 | APP | G65 security suite green | W |

## Mutation table (CHK-M8-320 to -364, from `work/tasks.md`)

Each plant goes in a throwaway copy and must turn the named gate red; rows marked S are security rows. The test that must fail is named per row.

| CHK | Plant | Must fail | Target |
| --- | --- | --- | --- |
| CHK-M8-320 S | `import re` in `operators.py`, `regex` via `re.search` | G1 (ruff ban); CHK-M8-033 (`(?=x)` must be `cannot evaluate`) | TASK-177 |
| CHK-M8-321 | own `re2.compile` without `(?m)` | CHK-M8-031 multiline row; CHK-M8-036 spy | TASK-177 |
| CHK-M8-322 | `fullmatch`/`match` instead of `search` | CHK-M8-031 `foo`/`xfoo` | TASK-177 |
| CHK-M8-323 S | `not_regex` True on compile failure | CHK-M8-033, -072 | TASK-177 |
| CHK-M8-324 | normaliser keeps CRLF | CHK-M8-010, -070, -071 | TASK-176 |
| CHK-M8-325 | normaliser `str.strip()` | CHK-M8-010 U+00A0 rows, CHK-M8-013 | TASK-176 |
| CHK-M8-326 | comparison case-folded | CHK-M8-021, -023, -070 | TASK-177 |
| CHK-M8-327 | numeric via `float()` | CHK-M8-041 2⁵³ + 1 row | TASK-177 |
| CHK-M8-328 | numeric via bare `Decimal()` (accepts `1e3`, `nan`) | CHK-M8-042 | TASK-177 |
| CHK-M8-329 S | `ne` PASS on non-numeric stdout | CHK-M8-042, -072 | TASK-177 |
| CHK-M8-330 | exit 1 gives FAIL | CHK-M8-062, -065 | TASK-178 |
| CHK-M8-331 | `> 128` instead of `>= 128` | CHK-M8-062 128 row | TASK-178 |
| CHK-M8-332 | 126 or 127 not ERROR | CHK-M8-062, -067 | TASK-178 |
| CHK-M8-333 | negative / None compared normally | CHK-M8-062, -067 | TASK-178 |
| CHK-M8-334 S | `timed_out` ignored | CHK-M8-063 | TASK-178 |
| CHK-M8-335 S | `truncated` ignored | CHK-M8-064 | TASK-178 |
| CHK-M8-336 | `stdout truncated` before `timed out` | CHK-M8-068 | TASK-178 |
| CHK-M8-337 | `Verdict` invariant removed | CHK-M8-005 | TASK-176 |
| CHK-M8-338 S | `classify` raises on unknown operator | CHK-M8-066, -130 | TASK-177, 178 |
| CHK-M8-339 S | caps in characters | CHK-M8-100, -101 multi-byte rows | TASK-179 |
| CHK-M8-340 | caps with `>=` | CHK-M8-100 65,536 row, -101 16,384 row | TASK-179 |
| CHK-M8-341 S | oversize from `truncated` flag only | CHK-M8-100, -101 | TASK-179 |
| CHK-M8-342 S | runner error still evaluated | CHK-M8-104 spy row | TASK-179 |
| CHK-M8-343 | stderr compared | CHK-M8-106 | TASK-179 |
| CHK-M8-344 S | parser accepts extra key or duplicate uuid | CHK-M8-111 | TASK-180 |
| CHK-M8-345 S | `build_eval_spec` writes `execute` | CHK-M8-114, -110 | TASK-180 |
| CHK-M8-346 | ERROR in denominator | CHK-M8-120 | TASK-181 |
| CHK-M8-347 | 0 ÷ 0 → 0.0 | CHK-M8-120 | TASK-181 |
| CHK-M8-348 S | lowest `reeval_id` or by `reevaluated_at` | CHK-M8-122 (unit), CHK-M8-151 (PG) | TASK-181, 182 |
| CHK-M8-349 S | f-string query in `repositories/results.py` | G1 S608 | TASK-182 |
| CHK-M8-350 S | f-string query in `repositories/reeval.py` | G1 S608 | TASK-183 |
| CHK-M8-351 | counts via lateral/correlated subquery over `scan_result_reeval` | CHK-M8-158 | TASK-182 |
| CHK-M8-352 | not run ignores retry results / double counts retry plugins | CHK-M8-152 host B | TASK-182 |
| CHK-M8-353 S | re-evaluation UPDATEs `scan_result.eval_code` | CHK-M8-191, -198 (and the grant error surfaces) | TASK-185 |
| CHK-M8-354 S | definitions read per plugin in separate statements | CHK-M8-171 (one statement), CHK-M8-211 race | TASK-183 |
| CHK-M8-355 S | intake ERRORs re-evaluated | CHK-M8-190, -199 | TASK-185 |
| CHK-M8-356 | rows for dropped plugins | CHK-M8-190 | TASK-185 |
| CHK-M8-357 | deleted policy allowed | CHK-M8-194 | TASK-185 |
| CHK-M8-358 S | per-scan lock removed | CHK-M8-174, -210 | TASK-183 |
| CHK-M8-359 S | audit missing or in own transaction | CHK-M8-193, -195 | TASK-185 |
| CHK-M8-360 | `fetchall`, no chunks | CHK-M8-172, -213 | TASK-183, 185 |
| CHK-M8-361 S | pure module imports `repositories.catalog` | CHK-M8-220 | TASK-178 |
| CHK-M8-362 S | stdout logged at DEBUG in `classify` / in exception | CHK-M8-074, -222 | TASK-178, 185 |
| CHK-M8-363 S | `eval_detail = "stdout not numeric: " + stdout` | CHK-M8-075, -005, -222 | TASK-178 |
| CHK-M8-364 | `Verdict` accepts code 3 | CHK-M8-005, -130 | TASK-176 |

## Questions for `main`

- **Q1 (REQ-191 (1) vs #115). Answered 2026-10-29 by `main`:** the `" "` in the row is U+00A0 (bytes 0xC2 0xA0). Tests assert U+0020 alone \u2192 empty and `"\u00a0"` (written as an escape) \u2192 not empty.
- **Ruling 2026-10-29 ("Normaliser: one-pass CRLF \u2192 LF", `work/decisions.md`):** the replace is one pass, so `"a\r\r\nb"` \u2192 `"a\r\nb"`. CHK-M8-012 and -013 are claimed for inputs without a CR right before a CRLF. Must-hold rows: `"a\r\r\nb"` \u2192 `"a\r\nb"`, `"a\r\nb"` \u2192 `"a\nb"`, `"a\rb"` kept.
- **Ruling 2026-10-29 ("Re-evaluation fails closed on an unrecognised stored ERROR detail"; TASK-183 r1, TASK-185 r1):** the order is intake detail, then an ERROR whose detail is not a `Detail` value (NULL, `' Oversize '`, `'OVERSIZE'`, unknown text) \u2192 `cannot evaluate`, then NULL stdout \u2192 `cannot evaluate`, then `classify()`. Added to CHK-M8-199 as must-hold rows, with plants for the order swap and the dropped step 2.

## NOT RUN at the M8 gate (by design, with reasons)

- TS §8.3 Integration "verdict uses the queued `eval_spec` after a catalog change" end to end through intake: **M9** (M8 proves the API-level half through CHK-M8-220 and the `PluginSpec` signatures).
- End-to-end scan → results: **M11** nightly. Load: deferred by the user.
