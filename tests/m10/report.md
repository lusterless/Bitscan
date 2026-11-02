# M10 test report

Phase report for M10 (compliance runner). Each section is folded by the lead, unchanged, from the tester's per-task report `work/reports/<id>-test.md` (the source); headings are demoted one level. The harness blocks tester sub-agents from writing this file (user ruling 2026-10-27). TASK-230 (sandbox CI) is held under the named VM exception (decisions 2026-11-01) and has no test report.

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-209 | TASK-209 TEST: PASS (r1) | `work/reports/TASK-209-test.md` |
| TASK-210 | TASK-210 TEST: PASS | `work/reports/TASK-210-test.md` |
| TASK-211 | TASK-211 TEST: PASS | `work/reports/TASK-211-test.md` |
| TASK-212 | TASK-212 TEST: PASS | `work/reports/TASK-212-test.md` |
| TASK-213 | TASK-213 TEST: PASS | `work/reports/TASK-213-test.md` |
| TASK-214 | TASK-214 TEST: PASS | `work/reports/TASK-214-test.md` |
| TASK-215 | TASK-215 TEST: PASS | `work/reports/TASK-215-test.md` |
| TASK-216 | TASK-216 TEST: PASS | `work/reports/TASK-216-test.md` |
| TASK-217 | TASK-217 TEST: PASS | `work/reports/TASK-217-test.md` |
| TASK-218 | TASK-218 TEST: PASS | `work/reports/TASK-218-test.md` |
| TASK-219 | TASK-219 TEST: PASS | `work/reports/TASK-219-test.md` |
| TASK-220 | TASK-220 TEST (r0 and r1): PASS | `work/reports/TASK-220-test.md` |
| TASK-221 | TASK-221 TEST (r1 and r2): PASS | `work/reports/TASK-221-test.md` |
| TASK-222 | TASK-222 TEST: PASS | `work/reports/TASK-222-test.md` |
| TASK-223 | TASK-223 TEST (r0 and r1): PASS | `work/reports/TASK-223-test.md` |
| TASK-224 | TASK-224 TEST (r1 and r2): PASS | `work/reports/TASK-224-test.md` |
| TASK-225 | TASK-225 TEST: PASS | `work/reports/TASK-225-test.md` |
| TASK-226 | TASK-226 TEST: PASS | `work/reports/TASK-226-test.md` |
| TASK-227 | TASK-227 TEST: PASS | `work/reports/TASK-227-test.md` |
| TASK-228 | TASK-228 TEST: PASS | `work/reports/TASK-228-test.md` |
| TASK-229 | TASK-229 TEST (r0, r1, r2; local parts): PASS | `work/reports/TASK-229-test.md` |
| TASK-231 | TASK-231 TEST: PASS (the VM runbook walk NOT RUN: VM hold) | `work/reports/TASK-231-test.md` |
| M10-gate | M10 gate (TP-M10-24): PASS, except G38 and G41 NOT RUN (safety-check refusal) and the named VM exception NOT RUN | `work/reports/M10-gate-test.md` |

## TASK-209


Tester: tester-m10, 2026-10-30. Full rigor (protocol, TS §8.2 second approval). REQ-234; TS §3.7 L281–L283, §3.5 L249, L252, §6.5 L1165–L1184; #29, #60, #116 (a), #130 (b)–(e), (i), #131 (b), #140. Lead ruling Q1 (decisions row "tester-m10's M10 plan questions"): over the socket, out-of-bound jobs, including `max_parallel_plugins` 0 or 9, get `malformed`; inventory gets `not_compliance`.

Code under test (impl-agent-m10, `work/reports/TASK-209-impl.md`, r1): `agent/internal/runner/proto/frame.go` (sha256 `db691d15b463e71a…`) and `proto.go` (`cbfef864391248a1…`). Test file (new): `agent/internal/runner/proto/proto_test.go` (`d20390a47a62998c…`). Plan rows: CHK-M10-001 to -010, plus mutation rows CHK-M10-323 and -324 (`tests/m10/test-plan.md`). I wrote the plan rows before reading the code, then bound them to the interface. The interface additions are `RefusalFor` and `ErrNotCompliance`.

**Round 0 finding (fixed in r1):** `RefusalFor` mapped `max_parallel_plugins` 0 or 9 to `bad_parallel`, which goes against the lead's Q1 ruling. I raised it before the verdict, and impl-agent-m10 fixed it in r1 (`ErrBadParallel` removed). Every run below is on r1.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows, go1.27.2) | `go test -count=1 -v ./internal/runner/proto/` from `agent/` | **108/108 passed** (9 tests, 99 subtests), 0 failed, 0 errors, 0 skipped |
| W (WSL Ubuntu 24.04, `/root/bstest-m10-base`, go1.27.2 linux/amd64) | `go test -race -count=1 -v ./internal/runner/proto/` | **108/108 passed**, 0 failed, 0 errors, 0 skipped |
| static | `gofmt -l internal/runner/proto`, `golangci-lint run --uniq-by-line=false ./internal/runner/proto/` (Windows and `GOOS=linux`, v2.14.0), `GOOS=linux go vet` | clean, 0 issues |
| plants | 12 plants, each in its own `/root/bstest-m10-mut-<id>` (a copy of the base, removed afterwards), running only the named test | **12/12 red**, each a test failure (no build error) |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-001 | CODE | L, W | `TestRoundTrip` | PASS | A request, `accepted`, `done`, `refused` with each of the 13 words, and three results (plain; `runner_unavailable` with null exit; multi-byte + NUL + quotes, exit 137, both flags) round-trip to equal values. The header is the body length (BE uint32). Bodies are compact JSON. Exact wire shapes `{"type":"accepted"}`, `{"type":"done"}`, `{"type":"refused","reason":"busy"}` |
| CHK-M10-002 | CODE | L, W | `TestContractFixtureJobsCarriedUnchanged` | PASS | Every compliance job in `manager/tests/contract/fixtures/jobs/response_valid_*.json` (compliance, mixed, plugins_5000, ten_jobs) goes through WriteRequest → ReadRequest with its JSON deep-equal to the fixture |
| CHK-M10-003 | CODE | L, W | `TestRequestRefusals`, `TestRequestRecordedCases` | PASS | 31 refusals, each with a zero `Request` returned: `command` beside `job`; unknown key in the job or a plugin; `v` 0/2/"1"/1.0/missing; mpp missing/0/9/−1/"2"/1.5/null; job missing/null; 0 and 5,001 plugins; timeout 0/601; 51 patterns; two values; value + number; array; bare string; `plugins` without a job; `V`/`Job` case variants; broken JSON. `RefusalFor` gives `not_compliance` for the inventory job and `malformed` for all 30 others (Q1). Accepted: mpp 1 and 8, 5,000 plugins, 50 patterns, `[]`, uppercase agent id. `WriteRequest` refuses mpp 0/9 and v 2 and writes 0 bytes. **Recorded:** invalid UTF-8 inside `execute` is refused; a duplicate `v` key is accepted; trailing whitespace after the object is accepted |
| CHK-M10-004 | CODE | L, W | `TestFrameBounds` | PASS | Headers 33,554,433 (request), 1,048,577 (reply) and 0xFFFFFFFF are refused with `ErrFrame` after reading exactly 4 bytes (a reader that fails the test on any further read). At exactly 33,554,432 and 1,048,576 the body is read and refused as `ErrMalformed`, not `ErrFrame`. A valid ~30 MiB request (5,000 × 6,000-char commands) is accepted. A zero header, 2 header bytes, and 100 announced with 50 sent are each `ErrFrame` for request and reply. A clean EOF wraps `io.EOF`. Exactly one frame is consumed per read. Constants 33,554,432 / 1,048,576 / 65,536 / 16,384 / v 1 |
| CHK-M10-005 | CODE | L, W | `TestReplyRefusals` | PASS | 18 reply refusals, all `ErrMalformed`: unknown/missing/number `type`; extra keys on each shape; `accepted` with `reason`; `refused` with an unknown, empty, uppercase or missing word; `result` without `result`; an unknown key or `error: "timeout"` inside the item; `Type` case variant; two values; array. `WriteReply` refuses an unknown kind, an unknown word, a missing word and a zero `Result`, writing 0 bytes |
| CHK-M10-006 | CODE | L, W | `TestResultCaps` | PASS | By both `NewResult` and a hand-built reply frame: stdout 65,536 B ok and 65,537 refused (ASCII; 21,845 × `€` + 1/+2; 16,384 emoji / +1); stderr 16,384 ok, 16,385 and 8,192 × `é` + 1 refused; `error` null/`runner_unavailable`/`spool_overflow` ok, `timeout`/`""` refused; error with exit code, stdout or stderr refused; bad UUID refused; NUL kept. `NewResult` refuses invalid UTF-8 in stdout or stderr. A maximal item (65,536 + 16,384 × U+0001, 6 bytes each escaped) fits one reply frame |
| CHK-M10-007 | CODE | L, W | `TestResultEncapsulation` | PASS | `Result` has no exported field. The input item and `Item()`'s output are both copies (exit-code and error pointers too). The zero `Result` can't be sent |
| CHK-M10-008 | CODE | L, W | `TestUnavailableAndOverflow` | PASS | `UnavailableResult(uuid, now +01:00)`: exit null, empty streams, flags false, `runner_unavailable`, `started_at` = `finished_at` = now, sent in UTC `Z`. `OverflowMarker` keeps the uuid and both original timestamps (text equal), with exit null, empty streams, flags false and `spool_overflow`. Both pass `NewResult` and have exactly the nine Results keys |
| CHK-M10-009 | CODE | L, W | `TestNoCommandAPI` | PASS | AST listing: the exported API is `Item, NewResult, OverflowMarker, ReadReply, ReadRequest, RefusalFor, UnavailableResult, WriteReply, WriteRequest`. None takes a `string`, `[]string`, `[]byte`, rune or variadic string parameter, or any `wire` type other than `UUID`, `Job` or `ResultItem`. No exported struct field is a plain string or bytes. `Request` has exactly `V:int, Job:wire.Job, MaxParallelPlugins:int` |
| CHK-M10-010 | CODE | L, W | `TestPurityWordsAndErrors` | PASS | Non-test files import only the standard library and `internal/agent/wire`: no `os*`, `syscall`, `net*`, `log*`, `unsafe` or third-party import, and no platform file. The exported `Reason` constants are exactly the 13 #130 (d) words, and each can be sent. Request and reply decode errors, and `NewResult` errors, for canary-bearing inputs (unknown key, execute, `v`, bare body, type, reason, a 160 KB stdout) contain no canary. REQ-234 (5): passes on Windows and Linux |
| CHK-M10-323 | CODE | W | plant: `ReadRequest` uses `json.Unmarshal` instead of `wire.DecodeStrict` | PASS (red) | `TestRequestRefusals` failed ("command beside job" and the other unknown-key rows accepted) |
| CHK-M10-324 | CODE | W | plant: the `Kind` case of `checkRequest` removed | PASS (red) | `TestRequestRefusals` failed (inventory job accepted) |
| extra 209a | CODE | W | plant: body read before the length check | PASS (red) | `TestFrameBounds` failed (read past 4 bytes) |
| extra 209b | CODE | W | plant: zero-length frame allowed | PASS (red) | `TestFrameBounds` failed |
| extra 209c, d | CODE | W | plants: stdout cap + 1; stderr cap + 3 | PASS (red) | `TestResultCaps` failed for each |
| extra 209e | CODE | W | plant: error item may carry an exit code | PASS (red) | `TestResultCaps` failed |
| extra 209f | CODE | W | plant: refused word not validated on read | PASS (red) | `TestReplyRefusals` failed |
| extra 209g | CODE | W | plant: `Item()` returns the inner item without copying | PASS (red) | `TestResultEncapsulation` failed |
| extra 209h | CODE | W | plant: `RefusalFor` never answers `not_compliance` | PASS (red) | `TestRequestRefusals` failed |
| extra 209i | CODE | W | plant: stdout UTF-8 check removed | PASS (red) | `TestResultCaps` failed |
| extra 209j | CODE | W | plant: `accepted`/`done` decoded leniently | PASS (red) | `TestReplyRefusals` failed (extra keys accepted) |

### Acceptance (TASK-209: "Unit on Windows and Linux: REQ-234 (1)–(5) hold")

| REQ-234 | Rows | Verdict |
| --- | --- | --- |
| (1) round trips, fixtures carried unchanged | CHK-M10-001, -002 | PASS |
| (2) refused at decode without reading an oversize frame whole | CHK-M10-003, -004, -005; plants 323, 324, 209a, 209b | PASS |
| (3) result caps and error rules, by both NewResult and the decoder | CHK-M10-006, -007, -008 | PASS |
| (4) no command API | CHK-M10-009 | PASS |
| (5) Windows and Linux | L and W runs | PASS |

### Notes (no finding)

1. Recorded, not asserted (none of these is a REQ-234 criterion): a duplicate key (`{"v":1,"v":1,…}`) is accepted, because Go's decoder takes the last value and `checkShape` sees the collapsed map. That's consistent in both passes, so the value checked is the value used. Trailing whitespace after the object is accepted. The agent's own encoder never sends either.
2. G75 (the import-boundary half) and G78 are covered later by CHK-M10-196 and the serve-loop rows (TASK-225). 323 and 324 turn G75 red here; their G78 half is re-planted at TASK-225.

## TASK-210


Tester: tester-m10, 2026-10-30. Full rigor (redaction, TS §8.2 second approval). REQ-242, REQ-243, REQ-244 (package level); TS §3.5 L251, §8.1 L1249, §8.3 L1275, §8.6 L1324, L1329–L1339; #57, #113, #116 (a), #121, #133, #134.

Code under test (impl-agent-m10, `work/reports/TASK-210-impl.md`): `agent/internal/redact/redact.go` (sha256 `a7e12392dbbca58d…`), `cutoff.go` (`9b44992050a919a0…`), `patterns.go` (`c5ae62c2d8a6da2e…`).

Test files (new):
- `agent/internal/redact/redact_test.go` (`0627cdcda5d07922…`)
- `agent/internal/redact/fuzz_test.go` (`c420fd81eef4c817…`)
- `manager/tests/test_redaction_crosscheck.py` (`08e1b51539d1876f…`)
- the shared corpus `manager/tests/contract/fixtures/redaction/corpus.json` (`0b79cdd33986ea45…`, 44 cases)

Plan rows: CHK-M10-011 to -024, -080, -081, -083 (`tests/m10/test-plan.md`), and mutation rows CHK-M10-344, -345, -347 to -354.

The five default patterns are read from TS §8.6 at test time, by both Go and Python; they are never copied. The corpus's expected matches were written by hand from the pattern text, and the byte spans are derived by sequential search, not by an engine.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows, go1.27.2) | `go test -count=1 -v ./internal/redact/` | **78/78 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, `/root/bstest-m10-base`, -race) | `go test -race -count=1 -timeout 580s -v ./internal/redact/` | **78/78 passed**, 0 failed, 0 errors, 0 skipped (485 s; most of it is the property test under -race) |
| W python | `/root/venv-m10` (new venv, `pip install --require-hashes -r manager/requirements-dev.txt`), `CI=true`, `pytest -n 0 tests/test_redaction_crosscheck.py` | **45/45 passed**, 0 failed, 0 errors, 0 skipped |
| W fuzz | `go test -run XXX -fuzz FuzzApply -fuzztime 90s` and `-fuzz FuzzCompile -fuzztime 45s` | PASS: 7,738 and 214,166 execs, no failure, no crasher kept |
| static | gofmt; `golangci-lint run --uniq-by-line=false ./internal/redact/` (Windows and `GOOS=linux`); `ruff check`, `ruff format --check`, `mypy --strict` on the Python file | clean |
| plants | 12, each in its own `/root/bstest-m10-mut-<id>` | **12/12 red**, each a test failure for the planted reason (no build error) |

Two test bugs were found and fixed before the verdict (product unchanged):
- The CHK-M10-020 filler was a word character, so the token had no `\b`.
- `M10CANARY*` is not nullable.

The memory row was also changed, from total allocation to a peak-heap measure: under `-race`, `sync.Pool` is disabled, so total allocation counts churn rather than live memory.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-011 | CODE | L, W | `TestConstants` | PASS | 1,048,576 / 65,536 / 16,384 / 4,194,304 / 50 / `[REDACTED]` |
| CHK-M10-012 | CODE | L, W | `TestCompileRefusals` | PASS | 51 → `ErrTooMany`. 24 patterns are each refused at index 0 and at index 3, with `PatternError.Index` equal to the position: `(`, `a{1001}`, `\C`, `x*`, `(?:)`, `a?`, `\b`, `^`, `$`, `\B`, `\z`, `\A`, `(a\|)`, `a{0,3}`, `(a*)+`, `(?i)`, `""`, `(?m)^$`, `[a-z]*`, `()`, `(?:a?b?)`, `\|a`, `a\|(?:)`, `\b\B`. `errors.Is(…, ErrEmptyMatch)` holds for the nullable ones. No error text holds the pattern (canary) |
| CHK-M10-013 | CODE | L, W | `TestCompileAccepts` | PASS | 50 valid, the 5 TS defaults, `[]`, nil, and 14 non-nullable patterns (`a+`, `.`, `(?s).`, `\bx`, `x\b`, `^a`, `a$` …) |
| CHK-M10-014 | CODE | L, W | `TestDefaultFixtures`, `TestSampleOutputsUnchanged` | PASS | 20 exact fixtures: shadow sha512 and yescrypt → `root:[REDACTED]:…`; full PEM key → `before\n[REDACTED]\nafter`; cut-off PEM key; full OpenSSH key; `password=…`; `api_key: …`; `DB_PASSWORD = s3cr3t # comment` → `DB_[REDACTED] # comment`; `bsa_`/`bsu_`/`bse_`/`bsk_` (43 chars); `enroll.token=bse_…` → `enroll.[REDACTED]` (patterns applied in order); AKIA; ASIA. Unchanged: `install ok installed`, `PasswordAuthentication no`, `passwd: files`, a locked shadow line, sshd -T lines. Every `ExpectedResult` of both `bits/samples/*.bit` (32 plugins, XML parsed) and 14 representative sample outputs are unchanged |
| CHK-M10-015 | CODE | L, W | `TestCorpusGoRegexp`; `test_spec_list_equals_the_seeded_and_settings_defaults` | PASS | The TS list has 5 entries and compiles in Go and in google-re2. It equals `services/settings/redaction.py` `DEFAULT_PATTERNS` and migration m0005 `REDACTION_PATTERNS` (REQ-243 (2)) |
| CHK-M10-016 | CODE | L, W | `TestCorpusGoRegexp`; `test_corpus_matches_with_google_re2[*]` (44) | PASS | REQ-243 (3): on all 44 corpus inputs, Go `regexp` and google-re2 each give exactly the hand-written spans for every default pattern. That includes `\b` after `é`, `(?i)` folding of `ſ` (U+017F) and `K` (U+212A), CRLF, NUL, U+FFFD, `\v`, NBSP, glued AKIA ids and 19/20-character tokens. No engine difference was found |
| CHK-M10-017 | CODE | L, W | `TestLiteralAndOrder` | PASS | `(a)(b)` on `ab` → `[REDACTED]` (REQ-242 (5)); `a` on `a$1${1}` → `[REDACTED]$1${1}`; a named group too; order: `secret` then `DACT` → `[RE[REDACTED]ED]`, and the reverse order differs |
| CHK-M10-018 | CODE | L, W | `TestCutOffRule` | PASS | Empty list: RSA, OpenSSH, EC, ENCRYPTED and bare cut keys → prefix + `[REDACTED]`. A complete block is unchanged. Complete block + cut block: the first is kept and the second is redacted from its BEGIN. PUBLIC KEY, CERTIFICATE and lowercase markers are unchanged. BEGIN A, BEGIN B, END B is unchanged (the #133 definition). END glued to BEGIN (the impl note) → `-----END RSA PRIVATE KEY[REDACTED]`. The rule also applies with the four defaults minus pattern 2 |
| CHK-M10-019 | CODE | L, W | `TestKeyCutByReadLimit` | PASS | REQ-242 (2): BEGIN at 1 MiB − 100, END beyond the read limit, `Overflow` true. With the defaults, without pattern 2, and with `[]`: no key body and no BEGIN in the output, `truncated` true, ≤ 65,536 |
| CHK-M10-020 | CODE | L, W | `TestSecretAtTheCap` | PASS | REQ-242 (1): a `bsa_` token starting at 65,530, 65,520, 65,536 − 47, 65,535 and 65,536. No prefix of length ≥ 2 of the token is in the output, ≤ 65,536, `truncated` true. A `password=` straddling the 16,384 stderr cap leaves no part, and `truncated` stays false |
| CHK-M10-021 | CODE | L, W | `TestCapsAndRuneBoundaries` | PASS | REQ-242 (3): 65,536 → unchanged, false; 65,537 → 65,536, true; 32,769 × `é` → 65,536; 21,846 × `€` → 65,535; 16,385 emoji → 65,536; `a` + 16,384 emoji → 65,533. stderr 16,384 / 16,385 / 8,193 × `é` / `a` + 8,192 × `é` → ≤ 16,384, false. Every output is a valid UTF-8 prefix of its input |
| CHK-M10-022 | CODE | L, W | `TestInvalidUTF8` | PASS | REQ-242 (4): a run of 3 invalid bytes → one U+FFFD; two runs → two; NUL kept; a cut rune → U+FFFD; `password=\xffabc` redacted; a U+FFFD pattern matches the replacement; 65,535 + `\xff` → 65,535 bytes, true; JSON round trip ≤ cap, valid, for three hostile inputs on both streams |
| CHK-M10-023 | CODE | L, W | `TestOverflowTruncated` | PASS | REQ-242 (6): 1 MiB of `a` with `Overflow`, pattern `a+` → `[REDACTED]`, true; short + `Overflow` → true; stderr + `Overflow` → false; no overflow and no cut → false |
| CHK-M10-024 | CODE | L, W | `TestGrowthGuard` | PASS | REQ-242 (7): `[a-z]` then `[A-Z]` on 1 MiB `aB…` → `[REDACTED]` with stdout true and stderr false. Boundary with pattern `a` (×10): intermediate exactly 4,194,304 → no guard (cut to 65,536, true); 4,194,305 → guard. **Recorded:** peak heap during a guarded 1 MiB Apply is 10.6 MB (L) and 11.6 MB (W -race) above baseline, under the 64 MiB bound; total churn is 22 MB (L) and 811 MB (W, -race disables `sync.Pool`) |
| (extra) | CODE | L, W | `TestDataOverReadLimit`, `TestRedactImports` | PASS | Data over 1 MiB (a caller bug) → 65,536, true. The package imports only `bytes`, `errors`, `fmt`, `regexp`, `regexp/syntax`, `unicode/utf8`; there is no platform file and nothing logs |
| CHK-M10-080 | CODE | W | `FuzzApply` (seeds in every run; 90 s fuzz) | PASS | Random secrets (crypt hashes, `bs[aeku]_`, AKIA/ASIA, PEM complete or cut, key=value) after fuzzed filler at any offset up to 1 MiB: no 8-byte window of a secret body leaks, output ≤ cap and valid, stderr never truncated. 7,738 execs, no failure |
| CHK-M10-081 | CODE | W | `FuzzCompile` (45 s) | PASS | An accepted pattern is accepted by Go, never matches empty on 9 probe strings, and gives valid capped output. 214,166 execs, no failure |
| CHK-M10-083 | CODE | L, W | `TestPropertySecretsNeverLeak` | PASS | 564 deterministic cases: each secret type placed straddling 16,384, 65,536 and 1,048,576 (120, 120 and 24 cases), plus 300 buffers with 1–12 secrets each. No body leaks, caps hold, output valid |
| CHK-M10-344 | CODE | W | plant: stdout cut to 65,536 before the patterns | PASS (red) | `TestSecretAtTheCap` failed: the token prefix was returned. `TestPropertySecretsNeverLeak` failed. G79 half: NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-345 | CODE | W | plant: `cutOff` only when the list is non-empty | PASS (red) | `TestCutOffRule` (8 subtests) and `TestKeyCutByReadLimit` failed |
| CHK-M10-347 | CODE | W | plant: `overflow` ignored in `truncated` | PASS (red) | `TestOverflowTruncated` failed |
| CHK-M10-348 | CODE | W | plant: the rune step-back removed | PASS (red) | `TestCapsAndRuneBoundaries` (`21846 euro`, `a + 16384 emoji`, `stderr a + 8192 e-acute`) failed |
| CHK-M10-349 | CODE | W | plant: a stderr cut sets `truncated` | PASS (red) | `TestCapsAndRuneBoundaries` (3 stderr subtests) failed |
| CHK-M10-350 | CODE | W | plant: `re.ReplaceAll(b, "$1")` | PASS (red) | `TestLiteralAndOrder` failed |
| CHK-M10-351 | CODE | W | plant: `> MaxPatterns+1` (51 accepted) | PASS (red) | `TestCompileRefusals` failed |
| CHK-M10-352 | CODE | W | plant: a compile error is skipped (`continue`) | PASS (red) | `TestCompileRefusals` failed |
| CHK-M10-353 | CODE | W | plant: the nullable check is off | PASS (red) | `TestCompileRefusals` failed |
| CHK-M10-354 | CODE | W | plant: the growth-guard return removed | PASS (red) | `TestGrowthGuard` failed |
| extra 210a | CODE | W | plant: no UTF-8 sanitising (`bytes.Clone`) | PASS (red) | `TestInvalidUTF8` failed |
| extra 210b | CODE | W | plant: the BEGIN search starts at the last END + 1 instead of after it (overlap case) | PASS (red) | `TestCutOffRule` failed |

### Acceptance (TASK-210: "REQ-242 (1)–(8) and REQ-244 (1), (2) hold at package level, and the REQ-243 fixtures pass with the five patterns extracted from TS §8.6")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-242 (1) secret at 65,530 | CHK-M10-020, plant 344 | PASS |
| REQ-242 (2) key past the read limit, with and without pattern 2 | CHK-M10-019, -018, plant 345 | PASS |
| REQ-242 (3) caps, rune boundary, stderr not truncated | CHK-M10-021, plants 348, 349 | PASS |
| REQ-242 (4) invalid UTF-8 first; JSON ≤ cap | CHK-M10-022, plant 210a | PASS |
| REQ-242 (5) no `$1` | CHK-M10-017, plant 350 | PASS |
| REQ-242 (6) 1 MiB + 1 → truncated | CHK-M10-023, plant 347 | PASS |
| REQ-242 (7) growth guard, memory bounded | CHK-M10-024, plant 354 | PASS |
| REQ-242 (8) fuzz | CHK-M10-080, -083 | PASS |
| REQ-244 (1), (2) at package level | CHK-M10-012, -013, -081, plants 351–353 | PASS (the runner-check half is TASK-213) |
| REQ-243 (1)–(3) fixtures, spec = seed, Go = RE2 | CHK-M10-014, -015, -016 | PASS |

No finding against the product.

## TASK-211


Tester: tester-m10, 2026-10-30. Full rigor (lint and dependency rules, TS §8.2 second approval). REQ-256, plus REQ-251 (2) and REQ-235 (6) through G8. TS §2.2 L111, §3.3, §3.7, §8.2 L1265; PD-41 (a). The lead's notes (decisions row "TASK-211 lint rules accepted as built"): the G9 plant uses a cold module cache; the `os/exec` exemption covers `internal/inventory/command_linux.go` and nothing else; `syscall.StartProcess` and `unix.Exec` each need a red plant.

Code under test (impl-agent-m10b, `work/reports/TASK-211-impl.md`): `agent/.golangci.yml` (sha256 `cc61e7aade335898…`), `agent/go.mod` (`b2c347739ad6d07d…`), `agent/go.sum` (`857f9cc9c0a345d8…`). There is no test file in the tree: the evidence is these runs (TP-M10-04). Plan rows: TP-M10-04, CHK-M10-300 to -304, CHK-M10-378, -379.

### Runs

All runs are on W (WSL Ubuntu 24.04, `/root/bstest-m10-base`, go1.27.2 linux/amd64). golangci-lint v2.14.0 linux/amd64 was installed at `/root/go-m10/bin` from the GitHub release, and its `sha256sum -c` against the release's `checksums.txt` was OK. The flags were `golangci-lint run --uniq-by-line=false --max-same-issues=0 --max-issues-per-linter=0 ./...` from `agent/`. Each plant ran in its own `/root/bstest-m10-mut-<id>`, which was removed afterwards.

| Run | Count |
| --- | --- |
| G8 on the unmodified tree (Linux) | 0 issues, exit 0 |
| Red plants | **18/18 red**, each with the planted file's own finding (the forbidigo message named below) |
| Green controls (allowed spots) | **4/4 green** (exit 0) |
| G9 | clean cold cache: `go mod download` 0, `go mod verify` "all modules verified". Altered `go.sum` with a cold cache: `go mod download` **exit 1** "verifying golang.org/x/sys@v0.49.0: checksum mismatch" |
| G7, G10, G11 | `gofmt -l .` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...` gives three ELF 64-bit statically linked binaries; the CI nolint grep has 0 hits |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command / plant | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-301 | CODE | W | G8 on the TASK-211 tree | PASS | 0 issues, exit 0 (Linux, authoritative) |
| CHK-M10-379 | CODE | W | `exec.Command("/bin/sh","-c",s).Run()` in `internal/agent/loops/compliance.go` | PASS (red) | forbidigo "processes start only in …" on `exec.Command` and `.Run`, plus G204 |
| CHK-M10-378 | CODE | W | `net.FileListener` in `internal/runner/serve.go` | PASS (red) | forbidigo "only the sdsock listener adopts the systemd socket" |
| TP-M10-04 a | CODE | W | `os.StartProcess` in `internal/redact/plant.go` | PASS (red) | forbidigo `os.StartProcess` |
| TP-M10-04 b | CODE | W | `syscall.ForkExec` in `internal/runner/job.go` | PASS (red) | forbidigo `syscall.ForkExec` |
| TP-M10-04 c | CODE | W | `syscall.Exec` in `cmd/bitscan-agent/main.go` | PASS (red) | forbidigo `syscall.Exec` |
| TP-M10-04 d | CODE | W | type-only `*exec.Cmd` parameter in `internal/spool/plant.go` | PASS (red) | forbidigo `exec.Cmd` |
| TP-M10-04 e | CODE | W | `net.Listen("unix", …)` in `internal/runner/plant_listen.go` | PASS (red) | forbidigo `net.Listen` |
| TP-M10-04 f | CODE | W | `unix.Socket` in `internal/sdsock/peer_linux.go` | PASS (red) | forbidigo `unix.Socket` (REQ-235 (6)) |
| TP-M10-04 g | CODE | W | `syscall.StartProcess` in `internal/agent/loops/plant.go` (lead's note 3) | PASS (red) | forbidigo `syscall.StartProcess` |
| TP-M10-04 h | CODE | W | `unix.Exec` in `internal/capread/client.go` (lead's note 3) | PASS (red) | forbidigo `unix.Exec` |
| TP-M10-04 i | CODE | W | `os/exec` in `internal/inventory/plant.go` (lead's note 2) | PASS (red) | forbidigo `exec.Command` |
| TP-M10-04 j | CODE | W | `os/exec` in `internal/inventory/command_extra.go` (lead's note 2: a name close to the exempt one) | PASS (red) | forbidigo `exec.Command` |
| TP-M10-04 j' | CODE | L | `os/exec` in `internal/inventory/command_windows.go`, Windows golangci-lint (on Linux the file is not built) | PASS (red) | 2 forbidigo findings, exit 1 |
| TP-M10-04 k | CODE | W | `net.FileListener` in `internal/sdsock/peer_linux.go` | PASS (red) | only `listen_linux.go` is exempt |
| TP-M10-04 l | CODE | W | `exec.Command(s)` in `internal/runner/plant_g204.go` | PASS (red) | forbidigo `exec.Command`, `exec.Cmd` |
| TP-M10-04 q | CODE | W | `exec.Command(s)` in `internal/runner/job.go` (G204 exemption is spawn-only) | PASS (red) | forbidigo |
| TP-M10-04 r | CODE | W | a bare `// nolint` in `internal/runner/checks_extra.go` | PASS (red) | nolintlint (unused, no specific linter, no explanation) |
| CHK-M10-304 | CODE | W | G11 grep (`agent.yml` step) on the tree; plant `//nolint:unused // planted` in `internal/runner/plant_nl.go` | PASS | tree 0 hits; plant 1 hit (red) |
| control m | CODE | W | `net.FileListener` in `internal/sdsock/listen_linux.go` | PASS (green) | exit 0 |
| control n | CODE | W | `exec.Command("/bin/sh","-c",execute)` in `internal/runner/spawn_linux.go` | PASS (green) | exit 0 (neither forbidigo nor G204) |
| control o | CODE | W | `exec.Command(path, args...)` in `internal/capread/serve_linux.go` | PASS (green) | exit 0 |
| control p | CODE | W | `*exec.Cmd` in `internal/inventory/command_linux.go` | PASS (green) | exit 0 (the M4 exemption the lead accepted) |
| CHK-M10-302 | CODE | W | G9: cold `GOMODCACHE`, one character changed in the `golang.org/x/sys v0.49.0 h1:` line | PASS (red) | `go mod download` exit 1 "checksum mismatch"; clean cold run exit 0. Recorded: `go mod verify` stays green on a warm or cold cache once the module is present (it checks the cache, not `go.sum`), so the red step is `go mod download`, which `agent.yml` runs first |
| CHK-M10-300 | CODE | W | G7 `gofmt -l .` | PASS | nothing printed |
| CHK-M10-303 | CODE | W | G10 `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...` | PASS | `bitscan-agent`, `bitscan-runner`, `bitscan-capread`: ELF 64-bit LSB executable, statically linked. (The `import "C"` plant runs at the gate on the runner code) |
| PD-41 | CODE | W | `go.mod`, `go.sum`, `go list -deps` | PASS | `golang.org/x/sys v0.49.0` is a direct require with the PD-41 comment; 2 `go.sum` lines; the only module importer so far is `internal/runner`; `go list -deps ./cmd/bitscan-agent` holds only the standard library's `vendor/golang.org/x/sys/cpu`, not the module |

### Acceptance (TASK-211: "On Linux G8 and G9 are green, each REQ-256 (1) plant in a throwaway copy turns G8 red, and `go mod verify` fails on an altered `go.sum` line")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| G8 green on Linux | CHK-M10-301 | PASS |
| REQ-256 (1): each forbidden call planted elsewhere turns G8 red (including `exec.Command` in `compliance.go` and `net.FileListener` in `internal/runner/serve.go`) | CHK-M10-378, -379, TP-M10-04 a–l, q, r | PASS (18/18 red, 4/4 controls green) |
| REQ-256 (2): no `//nolint` in non-test agent code | CHK-M10-304 | PASS |
| REQ-256 (3) / G9: altered `go.sum` fails | CHK-M10-302 (cold cache, per the lead's note) | PASS |
| PD-41 pinned | PD-41 row | PASS |

### Notes (no finding)

1. As the lead ruled, the exemption reaches past REQ-256's literal list to `internal/inventory/command_linux.go`, and the exempt pattern is exact (`command(_linux)?\.go`): `command_extra.go` and `command_windows.go` are both red.
2. `_test.go` files may use `os/exec` and listeners (exclusion rules). That is needed for the oracles and the fd-3 child process tests.

## TASK-212


Tester: tester-m10, 2026-10-30. Full rigor (spool, TS §8.2 second approval). REQ-247; TS §3.3 L222, L224, L226, §3.5 L248, §4.4 L577–L578; #4, #57, #78 (d), #131 (d), #139. Tested in two parts, each with its own checks and plants, per the lead's ruling (decisions row "TASK-212 (spool) accepted as built at 489 code lines"):
- part 1: persistence;
- part 2: the API and in-flight state.

Code under test (impl-agent-m10b, `work/reports/TASK-212-impl.md`): `agent/internal/spool/spool.go` (sha256 `3e9e668de2723114…`, which includes TASK-219's `Put` call site) and `manifest.go` (`365adae8231f4eb8…`). TASK-219's `overflow.go` (`b40f234e8fecaadf…`) is in the tree; no row below relies on `Put` answering `ErrFull`.

Test files (new):
- `agent/internal/spool/spool_test.go` (internal package `spool`, so the crash hook can be set; `bc923c0dd9d340b2…`)
- `agent/internal/spool/spool_linux_test.go` (`8807d88dbebb51b9…`)

Plan rows: CHK-M10-025 to -034, plus mutation rows CHK-M10-356, -359 and -366.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v ./internal/spool/` | **21/21 passed** (the 2 Linux-only tests are not built there), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/spool/` | **23/23 passed**, 0 failed, 0 errors, 0 skipped |
| static | gofmt; `golangci-lint run --uniq-by-line=false ./internal/spool/` (Windows and `GOOS=linux`) | clean |
| plants | 14 runs, each in its own `/root/bstest-m10-mut-<id>` | **13/13 real plants red**. One plant (`212h`, open mode 0644) stayed green because the code also `Chmod`s to 0600. That's a correct second guard; its companion `212h2` (the `Chmod` at 0644) is red |

### Part 1: persistence (manifest, items, reload, expiry, crash, modes, symlinks)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-025, -026, -029 | CODE | L, W | `TestP1ReopenOrderAndInterrupted` | PASS | REQ-247 (1), (3). `Size()` equals the bytes on disk after every write. Two jobs: job 2 received first, job 1 a second later with the lower id. After reopen nothing is dropped and the order is: job 2 start, job 2 `[001 002 003]` with `final`, then job 1 start, job 1 `[001 002]` with **no** final (it was running, so now interrupted, #131 (d); CHK-M10-359). `Put` to the interrupted job → `ErrJobEnded`. The spool is empty (0 bytes, no directories) once everything is answered |
| CHK-M10-028 | CODE | L, W | `TestP1CrashBetweenSteps` (8 subtests) | PASS | REQ-247 (2), CHK-M10-366. The crash hook fires at each of `created`, `written`, `synced` and `renamed`, for an item and for the manifest. Reopen leaves no `.tmp` and `Size()` = disk. A crashed item is absent for the three pre-rename steps and complete after `renamed`. A crashed manifest write keeps the old manifest (interrupted, no final) before the rename and the new one (final) after it |
| CHK-M10-028 | CODE | L, W | `TestP1PlantedPartialFiles` | PASS | Planted on disk: a truncated item, an item with 65,537 bytes of stdout (fails `proto.NewResult`), a partial `.tmp` item, a partial `job.json.tmp`, and a truncated `job.json` in a second job. `Open` reports `Dropped{job1, 2, unreadable}` and `Dropped{job2, 0, unreadable}`, removes job 2's directory, keeps `Size()` = disk, and delivers only plugin 1 of job 1 |
| CHK-M10-030 | CODE | L, W | `TestP1Expiry` | PASS | REQ-247 (4): received 7 d − 1 s and exactly 7 d ago → kept; 7 d + 1 s → `Dropped{job, 2, expired}`, size 0, nothing offered |
| CHK-M10-031 | CODE | L, W | `TestP1OnlyResultsAndNoCommand` | PASS | REQ-247 (5), CHK-M10-356, and "only redacted output can be written". Every exported method of `*Spool` takes only `wire.UUID`, `[]wire.UUID`, `proto.Result`, `spool.Batch`, `int` or `time.Duration`: no string, bytes, reader or `wire.ResultItem` write path. The manifest's keys are exactly `job_id, received_at, plugins, start_acked, finished, interrupted, final_acked`. No spool file holds an `execute` or `redaction_patterns` key. Together with `TestP1PlantedPartialFiles`, this shows that only items passing `proto.NewResult` are ever read back. (The spool cannot tell redacted text from raw; the guarantee is that its only input type is the runner's `proto.Result`, and the runner redacts, TASK-214) |
| CHK-M10-032 | CODE | W | `TestP1ModesLinux` | PASS | REQ-247 (6): the spool directory, the job directory and every file: dirs 0700, files 0600 |
| CHK-M10-033 | CODE | W | `TestP1SymlinksLinux` | PASS | REQ-247 (7). A symlinked spool directory is refused by `Open`. Symlinks to an outside file planted as the next item, the next item's `.tmp` and `job.json.tmp` are replaced, never followed: `Put`, `Put` and `Finish` succeed, and the outside file is unchanged with nothing created beside it. A symlinked `job.json` and a symlinked job directory at `Open` are not followed. **Recorded:** that job is dropped `unreadable`; a later `StartJob` of the symlinked id fails; the outside file is still unchanged |

| Plant (part 1) | Result | Evidence |
| --- | --- | --- |
| CHK-M10-366: no temporary file (write straight to the item name) | PASS (red) | `TestP1CrashBetweenSteps` failed |
| CHK-M10-359: a running job reopened as finished | PASS (red) | `TestP1ReopenOrderAndInterrupted` failed (a final was posted) |
| CHK-M10-356: an `execute` field added to the manifest | PASS (red) | `TestP1OnlyResultsAndNoCommand` failed |
| 212a: expiry window 7 d + 1 s | PASS (red) | `TestP1Expiry` failed |
| 212b: an item failing `NewResult` is read back as an unavailable item | PASS (red) | `TestP1PlantedPartialFiles` failed |
| 212e: size not reduced when items are removed | PASS (red) | `TestP1ReopenOrderAndInterrupted`, `TestP2InFlightAndFinal` failed |
| 212g: `os.Stat` instead of `os.Lstat` on the spool path | PASS (red) | `TestP1SymlinksLinux` failed |
| 212h2: files chmodded 0644 | PASS (red) | `TestP1ModesLinux` failed |
| 212h: `O_CREATE` at 0644 (with the `Chmod` 0600 kept) | green: not a fault | the explicit `Chmod` keeps 0600, a correct second guard |

### Part 2: the API and in-flight state

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-034 | CODE | L, W | `TestP2StartJobRules` | PASS | An uppercase job id is stored lowercase, and its lowercase plugin is accepted. Refused: a duplicate job, 0 plugins, 5,001 plugins, a bad job uuid, a bad plugin uuid. 5,000 is accepted. **`ErrFull` when the manifest doesn't fit** (100-byte spool), with 0 bytes and no directory left |
| CHK-M10-034 | CODE | L, W | `TestP2PutRules` | PASS | Unknown job → `ErrUnknownJob`. **A plugin not in the job → `ErrUnknownPlugin`** (CHK-M10-392 defence). A zero `Result` is refused. An uppercase plugin is accepted. After `Finish`: `Put` and a second `Finish` → `ErrJobEnded`. `Finish` of an unknown job → `ErrUnknownJob` |
| CHK-M10-026, -027 | CODE | L, W | `TestP2NextHoldAndBounds` | PASS | The start notice comes first. **Hold (#141):** 3 items of a running job are held at 29 s and go at 30 s. 50 ready items go at once. Size bound: ~40 KiB items under a 100,000-byte bound → 2 per batch, and the encoded body ≤ the bound. A single item over the bound still goes, alone |
| CHK-M10-026, -027 | CODE | L, W | `TestP2InFlightAndFinal` | PASS | **In flight:** with job 1's notice out, `Next` offers job 2's notice, then nothing. A batch that was never handed out can't be settled, and the same batch can't be settled twice. A **dropped** notice still lets the items go (#139 (e)). A finished job with nothing left → an empty `final`; nothing after it; the directory is removed. The last items batch carries `final` itself. Size is 0 at the end |
| CHK-M10-034 | CODE | L, W | `TestP2ConcurrentPutAndDrain` (-race on W) | PASS | 8 jobs × 40 items put from 8 goroutines while one drainer does `Next`/`Ack`: 320 distinct items, each handed out exactly once, 8 finals, size = disk, no race report |

| Plant (part 2) | Result | Evidence |
| --- | --- | --- |
| 212c: the in-flight check removed | PASS (red) | `TestP2InFlightAndFinal` failed |
| 212d: the hold rule removed | PASS (red) | `TestP2NextHoldAndBounds` failed |
| 212f: the `ErrUnknownPlugin` check removed | PASS (red) | `TestP2PutRules` failed |
| 212i: the `StartJob` `ErrFull` bound ×1000 | PASS (red) | `TestP2StartJobRules` failed |

### Acceptance (TASK-212: "in a temporary directory with a fake clock, REQ-247 (1)–(7) hold")

| REQ-247 | Rows | Verdict |
| --- | --- | --- |
| (1) put, list in order, ack; size = bytes on disk | CHK-M10-025, -026, `checkSize` after every step | PASS |
| (2) crash between any two steps | CHK-M10-028 (8 hook points + planted partial files), plant 366 | PASS |
| (3) reopen order; running job interrupted | CHK-M10-029, plant 359 | PASS |
| (4) 7 d + 1 s dropped | CHK-M10-030, plant 212a | PASS |
| (5) no `execute` or pattern in the spool; only results | CHK-M10-031, plant 356 | PASS |
| (6) 0600 / 0700 | CHK-M10-032, plant 212h2 | PASS |
| (7) a planted symlink is never written through | CHK-M10-033, plant 212g | PASS |

No finding against the product. The `Put`/overflow behaviour is TASK-219's.

### r1 delta: `Spool.Release` (tester-m10c, 2026-11-01)

Decisions "#140 reading: in-flight protection covers only an outstanding HTTP attempt". Only the new method is under test. File: `agent/internal/spool/release_test.go`, new and portable.

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test ./internal/spool/` | **32/32 passed** (the 29 earlier plus 3 new) |
| W (WSL, -race) | `go test -race ./internal/spool/ ./internal/agent/loops/` | **158/158 passed** |
| plants | 3 in `spool.go` (throwaway copies) | **3/3 red** |

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| R1-1 Release only clears the in-flight mark | CODE | L, W | `TestReleaseOnlyClearsInFlight` | PASS | Releasing the start notice and then an items-with-final batch leaves `Size()`, every file and the manifest bytes unchanged (sha256 per file). The next `Next` hands out the start notice again (StartAcked stays false), then the same items with `final` (FinalAcked stays false) |
| R1-2 a batch never handed out is an error | CODE | L, W | `TestReleaseOfABatchNeverHandedOut`, plus the acked case | PASS | Release errors for an unknown job, for a start notice never handed out, for the same batch twice, and for an acked batch. The refusals change nothing on disk |
| R1-3 released items are convertible; the retry is fresh | CODE | L, W | `TestReleasedItemsConvertible` | PASS | 4 × 64 KiB are handed out, then released. A `Put` that needs room converts the oldest released item, and the next batch carries its marker first and the newest result whole, within the 300,000 bound |
| plant: Release does nothing | CODE | W | `relnoop` | PASS (red) | `TestReleaseOnlyClearsInFlight` failed (nothing handed out again) |
| plant: Release clears the job's mark only | CODE | W | `reljobonly` | PASS (red) | "the oldest released item was not converted: the retry would resend the old body" |
| plant: Release of a batch not in flight accepted | CODE | W | `relany` | PASS (red) | "Release of an acked batch: no error"; "Release of an unknown job's batch: no error" |

Binary level: the overflow walk (`e2e/agent_binary_m10.sh overflow`, TASK-220 report) shows that a released batch's items become markers.

## TASK-213


Tester: tester-m10, 2026-10-30. Full rigor (runner job checks, TS §8.2 second approval). REQ-236, REQ-244 (the runner-check half); TS §3.3 L212, §3.7 L282, L285, §8.1 L1239, §8.3 L1283; #130 (d), #132. The lead's Q2 ruling applies: a job refused `seen_full` is not recorded.

Code under test (impl-agent-m10, `work/reports/TASK-213-impl.md`): `agent/internal/runner/checks.go` (sha256 `26dd331c071f8a56…`). Test files (new):
- `agent/internal/runner/checks_test.go` (internal package `runner`, so the 100,000-id bound can be reached by filling the set directly; `b1cb67f30551d34e…`)
- `agent/internal/runner/checks_linux_test.go` (the FIFO row; `18d1e50f1a1c79a2…`)

Plan rows: CHK-M10-035 to -043, plus mutation rows CHK-M10-324 to -328, -351, -352 and -393.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v -run TestChecks ./internal/runner/` | **58/58 passed** (subtests included; the FIFO row is Linux only), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v -run TestChecks ./internal/runner/` | **59/59 passed**, 0 failed, 0 errors, 0 skipped |
| static | gofmt; `golangci-lint run --uniq-by-line=false ./internal/runner/` (Windows and `GOOS=linux`) | clean |
| plants | 16, each in its own `/root/bstest-m10-mut-<id>` | **16/16 red**, each a test failure for the planted reason |

One test bug was fixed before the verdict: the case-variant duplicate row used all-digit UUIDs, so the case change was a no-op (plant 213a stayed green). The UUIDs now hold hex letters, and the plant is red.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-035 | CODE | L, W | `TestChecksRefusals` (30 subtests) | PASS | REQ-236 (1), each with its #130 word: foreign `agent_id` → `foreign_agent`; `pickup_by` now and now − 1 s → `pickup_passed`; now + 25 h + 1 s → `pickup_too_far`; inventory → `not_compliance`; 0 and 5,001 plugins, a duplicate `plugin_uuid` (also differing only in case), `timeout_s` 0 and 601 → `bad_plugins`; `max_parallel_plugins` 0 and 9 → `bad_parallel`. `agent_id` file missing, empty, non-UUID, two LFs, CRLF, leading space, 32-hex, a directory, over 64 bytes, two ids, trailing tab, NUL, braced, urn, hyphens moved, only LF, LF + space → `agent_id_unreadable` |
| CHK-M10-036 | CODE | L, W | `TestChecksAccepts` | PASS | Accepted: now + 25 h exactly; now + 1 ns; an uppercase `agent_id` in the job; a file without LF; an uppercase file; `[]` patterns; 5,000 plugins with `timeout_s` 1 and 600; parallel 1 and 8; the five TS defaults |
| CHK-M10-037 | CODE | L, W | `TestChecksOrder` | PASS | #132 (e) order: inventory + bad parallel → `not_compliance`; bad plugins + bad patterns → `bad_plugins`; bad plugins + bad parallel → `bad_plugins`; bad parallel + bad patterns → `bad_parallel`; bad patterns + foreign → `bad_patterns`; bad patterns + unreadable file → `bad_patterns`; unreadable + expired → `agent_id_unreadable`; foreign + expired and foreign + too far → `foreign_agent`; an expired replay → `pickup_passed` (seen is last) |
| CHK-M10-038 | CODE | L, W | `TestChecksRefusedIDRecorded` | PASS | REQ-236 (3): ids refused as foreign, bad parallel, bad patterns and too far are recorded, so the corrected resend is `replayed`. A plain replay → `replayed`. An uppercase replay → `replayed` |
| CHK-M10-039 | CODE | L, W | `TestChecksSeenBound` | PASS | REQ-236 (4): an id is still held at `pickup_by` + 1 min − 1 ns and forgotten at `pickup_by` + 1 min. Filled to 99,999: the 100,000th is accepted, and the next is `seen_full`. **Q2:** the `seen_full` job is not recorded, so the set stays at 100,000. At the bound, a foreign job keeps its own word. Once the filled ids expire, the job refused `seen_full` is accepted as a first run. `MaxSeen` = 100,000 |
| CHK-M10-040 | CODE | L, W | `TestChecksPatterns` | PASS | REQ-244 (1), (2) through the checks: 51 patterns, `(`, `a{1001}`, `\C`, `x*`, `(?:)`, `a?`, `\b`, `^` and `["ok","x*"]` → `bad_patterns`. 50 valid, the five defaults and `[]` → accepted. (REQ-244 (3), the manager-RE2-yes/Go-no case, is end to end: TASK-223's `refused_bad_patterns` row) |
| CHK-M10-041 | CODE | L, W | `TestChecksReadsAgentIDPerJob` | PASS | CHK-M10-393: after the file changes to another id, the next job for the old id is `foreign_agent` and one for the new id is accepted. A deleted file → `agent_id_unreadable` |
| CHK-M10-042 | CODE | L, W | `TestChecksStatic` | PASS | `checks.go` imports no `os/exec`, `log`, `log/slog`, `net` or `x/sys`, and calls no `time.Now`/`Since`/`Until`: the injected `now` is its only clock. It logs nothing (the `job_id` + word log line is the serve loop's, TASK-225, CHK-M10-167) |
| CHK-M10-043 | CODE | L, W | `TestChecksConcurrentSameID` (-race on W) | PASS | 16 goroutines at a barrier, one new id: exactly 1 accepted and 15 `replayed`; no race report |
| (extra) | CODE | W | `TestChecksAgentIDFIFOLinux` | PASS | A FIFO at the `agent_id` path → `agent_id_unreadable` at once (well under the 5 s bound); the check never blocks |
| CHK-M10-324 | CODE | W | plant: the kind check removed | PASS (red) | `TestChecksRefusals`, `TestChecksOrder` failed |
| CHK-M10-325 | CODE | W | plant: the `agent_id` comparison removed | PASS (red) | 5 tests failed (`Refusals`, `Order`, `RefusedIDRecorded`, `SeenBound`, `ReadsAgentIDPerJob`). The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-326 | CODE | W | plant: the window 26 h | PASS (red) | `TestChecksRefusals`, `TestChecksRefusedIDRecorded` failed |
| CHK-M10-327 | CODE | W | plant: the seen check removed | PASS (red) | `TestChecksRefusedIDRecorded`, `TestChecksConcurrentSameID` failed. The VM half is NOT RUN |
| CHK-M10-328 | CODE | W | plant: `pickup_by` = now accepted | PASS (red) | `TestChecksRefusals`, `TestChecksOrder` failed |
| CHK-M10-351 | CODE | W | plant: 51 patterns accepted (in `redact`) | PASS (red) | `TestChecksPatterns` failed (the G72 half; the G71 half is in TASK-210) |
| CHK-M10-352 | CODE | W | plant: a bad pattern skipped (in `redact`) | PASS (red) | `TestChecksPatterns` failed |
| CHK-M10-393 | CODE | W | plant: `agent_id` read once (`sync.Once` cache) | PASS (red) | `TestChecksReadsAgentIDPerJob` failed |
| extra 213a | CODE | W | plant: duplicates compared case-sensitively | PASS (red) | `TestChecksRefusals/duplicate_plugin_uuid_in_another_case` failed |
| extra 213b | CODE | W | plant: `timeout_s` 601 accepted | PASS (red) | `TestChecksRefusals` failed |
| extra 213c | CODE | W | plant: a `seen_full` job recorded (against Q2) | PASS (red) | `TestChecksSeenBound` failed |
| extra 213d | CODE | W | plant: refused ids not recorded | PASS (red) | `TestChecksRefusedIDRecorded` failed |
| extra 213e | CODE | W | plant: forgotten 1 ns after `pickup_by` + 1 min | PASS (red) | `TestChecksSeenBound` failed |
| extra 213f | CODE | W | plant: no type check and a blocking open | PASS (red) | `TestChecksAgentIDFIFOLinux` failed (blocked past 5 s) |
| extra 213g | CODE | W | plant: `max_parallel_plugins` 0 accepted | PASS (red) | `TestChecksRefusals` failed |

### Acceptance (TASK-213: "with a fake clock and a temporary agent_id file, REQ-236 (1)–(4) and REQ-244 (1), (2) hold, and the exec counter stays 0 for every refused request")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-236 (1) refusal table and accepted cases | CHK-M10-035, -036, -037 | PASS |
| REQ-236 (2) exec counter 0 for every refused request | `Checks` holds no executor and imports nothing that can start a process (CHK-M10-042). The counter through the socket is TASK-225's CHK-M10-165/-167 | PASS at this level |
| REQ-236 (3) refused id recorded | CHK-M10-038 | PASS |
| REQ-236 (4) expiry and the 100,000 bound | CHK-M10-039 | PASS |
| REQ-236 (5) through the driver on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-035 to -039 here and CHK-M10-167 (TASK-225) |
| REQ-244 (1), (2) through the checks | CHK-M10-040 | PASS |

### Notes (no finding)

1. On every call, `Check` walks the whole seen map to expire ids (up to 100,000 entries), so a job check is O(n) with n up to 100,000. That's a performance observation, not a correctness one: at one job per connection, a check costs about a millisecond. It is why the bound row fills the set directly instead of through 100,000 calls.

## TASK-214


Tester: tester-m10, 2026-10-30. Full rigor (capture and result, TS §8.2 second approval). REQ-241, REQ-242 (through the capture path); TS §3.5 L251–L252, §6.5 L1184, §4.5 L593; #113, #114, #134 (b), #136 (e).

Code under test (impl-agent-m10, `work/reports/TASK-214-impl.md`): `agent/internal/runner/capture.go` (sha256 `d4356a39ef64f116…`) and `result.go` (`af62b47cf72642ba…`). Test files (new):
- `agent/internal/runner/capture_test.go` (`1e8b8b1be03e16d7…`)
- `agent/internal/runner/capture_linux_test.go` (`9946f2954ac7d17f…`; real processes, harmless payloads only)

Plan rows: CHK-M10-044 to -050, plus mutation rows CHK-M10-346, -355 and -357.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -run 'Capture\|ExitCode\|Build\|Unavailable' -v ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | same, with `-race` | **10/10 passed** (the 2 Linux process rows included), 0 failed, 0 errors, 0 skipped |
| static | gofmt; golangci-lint (Windows and `GOOS=linux`) | clean |
| plants | 7 | **7/7 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-044 | CODE | L, W | `TestCaptureLimitAndDrain`, `TestCaptureReadError` | PASS | Over an `os.Pipe`, writers of 0, 1, 1,048,576, 1,048,577 and 3 MiB all finish (the rest is drained, never blocked). The kept data is exactly the first `min(n, 1 MiB)` bytes, and `Overflow` is false at exactly 1 MiB and true at 1 MiB + 1. On a read error the bytes kept so far come back with the error (10 bytes, and 1 MiB with `Overflow`) |
| CHK-M10-045 | APP | W | `TestCaptureRealProcessBothPipesLinux`, `TestCaptureTwoStreamsConcurrently` | PASS | `sh -c 'head -c 3145728 /dev/zero >&2; head -c 3145728 /dev/zero'` with both pipes captured concurrently exits cleanly. Each stream keeps 1 MiB with `Overflow`. A silent stream beside a 3 MiB one doesn't deadlock. (TASK-214 acceptance: "a writer producing 3 MiB is never blocked") |
| CHK-M10-046 | CODE | L, W | `TestExitCodeMapping`, `TestExitCodeRealProcessesLinux` | PASS | REQ-241 (1): 0, 1, 126, 127, 255 → themselves; signals 9 → 137, 15 → 143, 11 → 139, 1 → 129, 6 → 134; never negative. Real wait statuses on Linux: `exit 3` → 3, `exit 126` → 126, `exit 255` → 255, `kill -9 $$` → 137, `kill -15 $$` → 143, `kill -11 $$` → 139, an unknown command → 127 (REQ-241 (3) at unit level) |
| CHK-M10-047 | CODE | L, W | `TestBuildItem` | PASS | REQ-241 (2), (4). A +01:00 start with nanoseconds → `started_at` and `finished_at` both end in `Z`, start ≤ end, the same instant kept. A clock step back gives `finished_at` = `started_at`, never earlier. `exit_code` 137 with `timed_out` true. stdout `bsa_` and stderr `password=` → `[REDACTED]`. `truncated` comes from stdout overflow; a 20,000-byte stderr is cut to 16,384 with `truncated` false. Every item passes `proto.NewResult` |
| CHK-M10-048 | CODE | L, W | `TestBuildFallbackNeverRaw` | PASS | CHK-M10-357: an outcome that `NewResult` refuses (bad plugin uuid) → `runner_unavailable`, null exit, empty streams. The raw canary is in neither the item JSON nor any log record (default slog captured) |
| CHK-M10-049 | CODE | L, W | `TestCaptureThenBuildOverflow` | PASS | REQ-242 (6) through capture: 1 MiB + 1 byte of `a` through a pipe, with pattern `a+` → `[REDACTED]`, `truncated` true |
| CHK-M10-050 | CODE | L, W | `TestUnavailableShape` | PASS | REQ-241 (5) item shape: null exit, empty streams, flags false, `runner_unavailable`. (Forcing exec or cgroup failure for one plugin is the executor's row, TASK-224 CHK-M10-153) |
| CHK-M10-346 | CODE | W | plant (a): the drain removed | PASS (red) | 5 tests failed, including `TestCaptureTwoStreamsConcurrently` and `TestCaptureRealProcessBothPipesLinux`, both blocked to the 30 s bound |
| CHK-M10-346 | CODE | W | plant (b): the read limit removed | PASS (red) | 4 tests failed (3 MiB kept) |
| CHK-M10-355 | CODE | W | plant: a signal death reported as −1 | PASS (red) | `TestExitCodeMapping`, `TestExitCodeRealProcessesLinux` failed |
| CHK-M10-357 | CODE | W | plant (a): raw stdout instead of redacted | PASS (red) | `TestCaptureThenBuildOverflow` (and the redaction asserts) failed |
| CHK-M10-357 | CODE | W | plant (b): a refused item returned as is (a zero Result) instead of `runner_unavailable` | PASS (red) | `TestBuildFallbackNeverRaw` failed |
| extra 214b | CODE | W | plant: the clock-step clamp removed | PASS (red) | `TestBuildItem` failed |
| extra 214c | CODE | W | plant: `Overflow` only above 1 MiB + 1 | PASS (red) | `TestCaptureLimitAndDrain`, `TestCaptureThenBuildOverflow` failed |

### Acceptance (TASK-214: "REQ-241 (1), (2), (4) hold, a writer producing 3 MiB is never blocked, and REQ-242 (6) holds through the capture path")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-241 (1) exit statuses and signals | CHK-M10-046, plant 355 | PASS |
| REQ-241 (2) times | CHK-M10-047, plant 214b | PASS |
| REQ-241 (4) every item passes NewResult (or becomes runner_unavailable) | CHK-M10-047, -048, plants 357a/b | PASS |
| a 3 MiB writer never blocked | CHK-M10-044, -045, plant 346a | PASS |
| REQ-242 (6) through capture | CHK-M10-049, plant 214c | PASS |
| REQ-241 (3) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-046 (real processes in WSL) and TASK-224's CHK-M10-154 |

No finding.

## TASK-215


Tester: tester-m10, 2026-10-30. Full rigor (cgroups, TS §8.2 second approval). REQ-238, REQ-240 (the sweep), REQ-237 (the cgroup part of the start-up refusals); TS §3.5 L249–L250, §3.7 L284, L322–L323, L365, §8.1 L1245; #136 (a), #137, #138. The wider sweep (strays in the service-cgroup root are pid-killed too, and `supervisor/supervisor` is caught) was accepted by the lead under TS §3.7 L284 and is asserted as built.

Code under test (impl-agent-m10, `work/reports/TASK-215-impl.md`; split per the lead into three files): `agent/internal/runner/cgroup.go` (sha256 `6d919f5ba0131888…`), `sweep.go` (`07070fed83849316…`), `cgroup_linux.go` (`48bf11ae1634d528…`).

Test files (new):
- `agent/internal/runner/cgroup_test.go` (`2c89efd356a08173…`): portable fake-tree tests. The fake models the kernel rules the code relies on: one cgroup per pid, `cgroup.procs` moves a whole process, `cgroup.kill` kills the whole subtree (the runner too, if it's there), `rmdir` only when the cgroup is empty and has no children, and symlink entries.
- `agent/internal/runner/cgroup_delegated_linux_test.go` (`9dace1cae4f84145…`, build tag `delegated`): the real code in a delegated cgroup.

Plan rows: CHK-M10-100 to -106, plus mutation rows CHK-M10-336 to -339 (the G72 half).

### Where the delegated rows ran

In WSL Ubuntu 24.04: cgroup2fs, systemd 255, with `systemd-run --wait --pipe --collect -p Delegate=yes <race-built test binary> -test.run Delegated` (the script `deleg.sh`, kept outside the repo). The transient unit's cgroup was `/system.slice/run-uNN.service`. So the delegated rows ran locally, not only in CI. They need `-tags delegated` and `systemd-run`, so a plain `go test ./...` does not run them. **For the lead / impl-deploy:** G72's delegated half needs a CI step that runs them the same way (see the note at the end).

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -run TestCgroup ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -run TestCgroup -v ./internal/runner/` | **8/8 passed**, 0 failed, 0 errors, 0 skipped |
| WD (delegated, -race) | `deleg.sh base ./internal/runner/ Delegated` | **5/5 passed** (1 test, 4 subtests), unit exit 0 |
| static | gofmt; golangci-lint (Windows; `GOOS=linux --build-tags delegated`) | clean |
| plants | 14 runs (10 fake tree, 4 delegated) | **14/14 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-100 | CODE | L, W | `TestCgroupExactOperations` | PASS | REQ-238 (1). The exact operation log is: `mkdir supervisor`, `write supervisor/cgroup.procs <self>`, `mkdir p-1`, `write p-1/cgroup.procs <self>`, `write supervisor/cgroup.procs <self>`, `write p-1/cgroup.kill 1`, `rmdir p-1`. Nothing else is written. The child is born in `p-1`, dies at `cgroup.kill`, and the runner ends in `supervisor`. Names are `p-1`, `p-2`, `p-3`, from a counter |
| CHK-M10-101 | CODE | L, W | `TestCgroupSetupRefusals`, `TestCgroupSweepKillsEveryStray` (symlink entry) | PASS | `/proc/self/cgroup` refused when empty, two `0::` lines, a v1 line beside `0::`, a v1-only line, a relative path, `0:/x`, `0::`. `Setup` refused with no `cgroup.kill`, when `supervisor` can't be made (not delegated), and when the move into `supervisor` fails; an existing `supervisor` is fine. A symlink entry `p-9` is never touched by the sweep |
| CHK-M10-102 | APP | WD | `TestDelegatedCgroups` (setup + "plugin born in its own cgroup") | PASS | REQ-238 (2), (3). After `Open`, the runner's `/proc/self/cgroup` ends in `/supervisor`. The plugin's first action `cat /proc/self/cgroup` and its first fork (`sleep 30 &`) are both in `<service>/p-1`. The runner is back in `supervisor` straight after `StartIn` |
| CHK-M10-103 | APP | L, W, WD | `TestCgroupSweepKillsEveryStray`; delegated "sweep kills strays everywhere" | PASS | Strays in `supervisor`, `supervisor/x/y`, `p-3`, `p-3/child`, `q/r`, `supervisor/supervisor` and the service root are all killed. Only `supervisor` is left (REQ-238 (4)) and the runner is alive in it. Real kernel: 6 `sleep 300` strays (supervisor, supervisor/x, p-77, p-77/child, q/r, the service root) all die within 3 s, the subtree holds only `supervisor`, there's no cgroup under `supervisor`, and the runner is alive. **Recorded:** a write into the service root's `cgroup.procs` was accepted (subtree_control empty) |
| CHK-M10-104 | APP | L, W, WD | `TestCgroupRunnerMovedBack`; delegated "runner moved by a plugin" | PASS | #138 (b). Moved into the plugin's cgroup, the runner is moved back before `Kill`, so it doesn't kill itself, and before the sweep. Real kernel: the runner moved into `p-88` → after `Sweep` it's in `supervisor`, and the `sleep` beside it is dead |
| CHK-M10-105 | APP | L, W, WD | `TestCgroupWaitEmptyBound`; delegated "kill a forked tree" | PASS | `WaitEmpty` honours the caller's deadline (100 ms, not 5 s), `emptyWait` = 5 s, and a populated cgroup can't be removed. Real kernel: `sh -c 'sleep 300 & sleep 300 & (sleep 300 &); wait'` → `cgroup.kill` → `populated 0` after 11 ms (recorded), then rmdir |
| (extra) | CODE | L, W | `TestCgroupStartInFailsClosed` | PASS | The hop fails closed. A refused write to `p-n/cgroup.procs` → `start` not called. `/proc/self/cgroup` not showing `p-n` after the write → `start` not called. `start`'s own error is returned. In every case the runner is back in `supervisor` |
| (extra) | CODE | L, W | `TestCgroupSweepRepeatsAndFailsClosed` | PASS | A stray that moves to a new cgroup just before each of 3 kills is caught by a later pass. An unkillable stray makes `Sweep` return an error after about 5 s (so the runner exits) |
| CHK-M10-106 | CODE | L, W | `TestCgroupSpawnLock` (-race on W) | PASS | While a hop is open, a concurrent `Sweep`, another `StartIn` and a `Kill` make no operation at all; they run after the hop closes |
| CHK-M10-338 | CODE | W, WD | plant: `killPids` dropped | PASS (red) | Fake: `SweepKillsEveryStray`, `SweepRepeatsAndFailsClosed` failed. Delegated: the strays in `supervisor` and the service root survived. The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-339 | CODE | W, WD | plant: `supervisor`'s children skipped | PASS (red) | Fake: `SweepKillsEveryStray` failed. Delegated: the stray in `supervisor/x` survived and `x` was left. VM half NOT RUN |
| CHK-M10-336 (G72 half) | CODE | W | plant: the `p-n/cgroup.procs` write and the post-hop check removed (child born in `supervisor`) | PASS (red) | `ExactOperations`, `StartInFailsClosed` failed. (With only the write removed, the post-hop check still refuses the start, which is fail closed.) VM half NOT RUN |
| CHK-M10-337 (G72 half) | CODE | W, WD | plant: `kill` writes nothing | PASS (red) | Fake: 4 tests failed. Delegated: `cgroup not empty: context deadline exceeded` in every subtest. VM half NOT RUN |
| extra 215a | CODE | W, WD | plant: the service root left out of the pid kill | PASS (red) | Fake and delegated (stray 6 in the service root survived) |
| extra 215b | CODE | W | plant: one sweep pass only | PASS (red) | `SweepRepeatsAndFailsClosed` failed (the escaping stray survived) |
| extra 215c | CODE | W | plant: the post-hop `here()` check weakened | PASS (red) | `StartInFailsClosed` failed |
| extra 215d | CODE | W | plant: no `ensureSupervisor` before `cgroup.kill` | PASS (red) | `RunnerMovedBack` failed (the runner killed itself) |
| extra 215e | CODE | W | plant: no `cgroup.kill` presence check | PASS (red) | `SetupRefusals` failed |
| extra 215f | CODE | W | plant: multi-line `/proc/self/cgroup` accepted | PASS (red) | `SetupRefusals` failed |

### Acceptance (TASK-215: "on a fake cgroup tree REQ-238 (1) holds; under `systemd-run -p Delegate=yes` a planted stray in supervisor, in a nested cgroup and in a plugin cgroup are all gone after Sweep, and the runner stays alive in supervisor")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-238 (1) on a fake tree, including `..`/`/`/symlink refusal | CHK-M10-100, -101 | PASS |
| strays in supervisor, nested and in a plugin cgroup gone after `Sweep` (delegated) | CHK-M10-103 (WD) | PASS |
| the runner alive in supervisor | CHK-M10-103, -104 (WD) | PASS |
| REQ-238 (2)–(4) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-102, -103 (WD, the real kernel in WSL) |

### Note for the lead (not a finding against TASK-215)

The delegated tests are behind `//go:build linux && delegated` and need root plus `systemd-run -p Delegate=yes`, so `go test ./...` in CI doesn't run them. For G72's "delegated parts under `systemd-run -p Delegate=yes` (CI)", `agent.yml` (impl-deploy) needs a step such as:

```sh
go test -c -race -tags delegated -o runner.test ./internal/runner/
sudo systemd-run --wait --pipe --collect -p Delegate=yes ./runner.test -test.run Delegated -test.v
```

I'll add the TASK-221 and TASK-224 delegated tests to the same binary.

### r1 evidence: delegated rows as the unit's user (reviewer-m10 finding 1; decisions row "Delegated real-kernel rows must run as the unit user")

The same delegated binary and plants 338/339 were re-run unprivileged, as the runner unit's user. The command (via `deleg.sh` with `M10_AS_RUNNER=1`; binary copied to `/opt/m10test`, mode 0755):

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p WorkingDirectory=/opt/m10test /opt/m10test/base-__internal_runner_.test -test.run Delegated -test.v`

Setup in WSL: `useradd --system --no-create-home --shell /usr/sbin/nologin bitscan-runner` → `uid=999(bitscan-runner) gid=988(bitscan-runner)`. No test step needed root. The test file now logs its identity (`recordIdentity`); delegated test sha256 is `23dbd0b0d1e2e055…`.

| Run | Identity (recorded by the test) | Count / result |
| --- | --- | --- |
| `TestDelegatedCgroups` | uid 999, euid 999, gid 988; CapEff, CapPrm, CapBnd and CapAmb 0x4; NoNewPrivs 1 | **5/5 passed**, unit exit 0. Same evidence as root: plugin and first fork in `p-1`; 6 strays killed, including the service root (the write into the service root's `cgroup.procs` was accepted for the delegated user); runner moved back from `p-88`; forked tree emptied |
| plant CHK-M10-338 (`killPids` dropped), as bitscan-runner | same | **red**: strays 1 (supervisor) and 6 (service root) survived |
| plant CHK-M10-339 (`supervisor` children skipped), as bitscan-runner | same | **red**: stray 2 in `supervisor/x` survived and `x` was left |

So the cgroup and pidfd paths work with only `CAP_DAC_READ_SEARCH` and `NoNewPrivileges`, as the unit's user, and the plants still go red there. No product finding. The TASK-221 and TASK-224 delegated rows will use the same mode.

## TASK-216


Tester: tester-m10, 2026-10-30. Full rigor (runner hygiene, TS §8.2 second approval). REQ-237 (1) and the hygiene half of REQ-237; TS §3 L152, §3.7 L276, L283, §8.1 L1245; #137.

Code under test (impl-agent-m10, `work/reports/TASK-216-impl.md`): `agent/internal/runner/hygiene_linux.go` (sha256 `701fc72157d46ecc…`). Test file (new): `agent/internal/runner/hygiene_linux_test.go` (`ca9d4745b8d3aa9d…`; Linux only, like the code). Plan rows: CHK-M10-110 to -112, plus mutation rows CHK-M10-329, -340, -385 and -386 (the G72 halves).

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -run 'TestCheckStartup\|TestSystemProbeLinux\|TestHardenLinux' -v ./internal/runner/` | **18/18 passed** (3 tests, 15 subtests), 0 failed, 0 errors, 0 skipped |
| static | `GOOS=linux go vet`, `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/runner/` | clean |
| plants | 7 | **7/7 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-110 | CODE | W | `TestCheckStartup` (15 subtests) | PASS | REQ-237 (1) with injected probes. Passing set: euid 998, `CapEff`/`CapBnd` 0x4, cgroup2 magic, one `0::` line; `CapEff` 0 also passes (a subset). Each failing input refuses with a one-line message naming its check: euid 0 (CHK-M10-385); `CapBnd` 0x1ffffffffff; `CapEff` with `CAP_SYS_ADMIN` (0x200004, CHK-M10-386 unit part); `CapEff` `CAP_NET_ADMIN` only; `CapBnd` with `CAP_DAC_OVERRIDE`; tmpfs magic 0x01021994 and cgroup v1 magic 0x27e0eb at `/sys/fs/cgroup` (CHK-M10-340); a statfs error; hybrid and v1 `/proc/self/cgroup`. At least 6 distinct messages. With euid 0 and every capability, the euid line wins (that check comes first) |
| CHK-M10-112 | CODE | W | `TestCheckStartup` | PASS | Fail closed: no `CapEff` line, two `CapEff` lines, non-hex `CapEff`, `/proc/self/status` unreadable, `/proc/self/cgroup` unreadable → each refused |
| (extra) | CODE | W | `TestSystemProbeLinux` | PASS | The real probe on WSL as root refuses with "effective uid is 0" (recorded). On this cgroup2 host, with good capabilities injected and a non-root euid, the real statfs and `/proc/self/cgroup` pass |
| CHK-M10-111 | APP | W | `TestHardenLinux` | PASS | In a child process, `Harden()` → `PR_GET_DUMPABLE` = 0. The parent test process is still dumpable (1). REQ-237 (2) on a sandbox host (`/proc/<runner>/mem`, `environ` → EACCES) is NOT RUN (safety-classifier refusal (VM sandbox)); this row is its cover |
| CHK-M10-329 | CODE | W | plant: `PR_SET_DUMPABLE` not set | PASS (red) | `TestHardenLinux` failed (Harden's own post-check also refuses). VM half NOT RUN |
| CHK-M10-340 | CODE | W | plant: the statfs magic check removed | PASS (red) | `TestCheckStartup` failed. The VM half (the u2204 cgroup v1 boot) is NOT RUN |
| CHK-M10-385 | CODE | W | plant: euid 0 accepted | PASS (red) | `TestCheckStartup`, `TestSystemProbeLinux` failed |
| CHK-M10-386 | CODE | W | plant: the capability check made ineffective | PASS (red) | `TestCheckStartup`, `TestSystemProbeLinux` failed. The planted-unit VM half is NOT RUN |
| extra 216a | CODE | W | plant: only `CapEff` checked (`CapBnd` ignored) | PASS (red) | `TestCheckStartup` failed |
| extra 216b | CODE | W | plant: a repeated `CapEff` line accepted | PASS (red) | `TestCheckStartup` failed |
| extra 216c | CODE | W | plant: the `/proc/self/cgroup` parse ignored | PASS (red) | `TestCheckStartup` failed |

### Acceptance (TASK-216: "unit with injected readers: REQ-237 (1) holds; on Linux PR_GET_DUMPABLE returns 0 after Harden()")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-237 (1) each failing input refuses with its own line; the passing set starts | CHK-M10-110, -112 | PASS |
| `PR_GET_DUMPABLE` 0 after `Harden()` | CHK-M10-111 | PASS |
| REQ-237 (2)–(4) on a sandbox host | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-110, -111 and TASK-228's binary rows |

No finding.

## TASK-217


Tester: tester-m10, 2026-10-30. Full rigor (socket activation and peer check, TS §8.2 second approval). REQ-235 (1), (2), (5), (6); TS §2.2 L111, §3.7 L281–L283, L289–L302, L486–L493; #130 (j). Lead's ruling "TASK-217 fd 3 handling": fd 3 is kept open, and REQ-235 (5) is asserted as written (`/proc/<pid>/fdinfo/3` carries `O_CLOEXEC`), along with "no fd above 2 lacks `O_CLOEXEC`".

Code under test (impl-agent-m10, `work/reports/TASK-217-impl.md`): `agent/internal/sdsock/listen_linux.go` (sha256 `63d1c4e7d2e80ea6…`) and `peer_linux.go` (`1b4e694f2d027e4f…`). Test file (new): `agent/internal/sdsock/sdsock_linux_test.go` (`4ab05c3b8eed1ff0…`). Plan rows: CHK-M10-117 to -122, plus mutation rows CHK-M10-320, -321 and -330 (the G72 halves).

How it runs: the listening socket is passed to a child copy of the test binary as fd 3 (`ExtraFiles`), with `LISTEN_PID` set to the child's own pid by an exec wrapper (`/bin/sh -c 'LISTEN_PID=$$ exec "$0" …'`), as systemd does. Peers with other uids connect through `setpriv --reuid/--regid --clear-groups python3`. The run is as root in WSL.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race, root) | `go test -race -count=1 -v ./internal/sdsock/` | **20/20 passed** (6 tests, 14 subtests), 0 failed, 0 errors, 0 skipped |
| static | `GOOS=linux go vet`, `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/sdsock/` | clean |
| plants | 7 | **7/7 red** |

The first run found a data race in the test harness (reading the child's output buffer while `exec` wrote it); it was fixed with a locked buffer. That was a test bug, not a product one.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-117 | APP | W | `TestPeerCheck/expected_uid_served` | PASS | Expected uid 64999. A client running as 64999:64999 gets `ok`, and the child serves it and exits 0 |
| CHK-M10-118 | APP | W | `TestPeerCheck/root_and_other_uids_refused,_then_the_right_one_served` | PASS | REQ-235 (1). Peers uid 0, uid 64998, and uid 64998 with the **expected uid number as gid** are each closed before any reply (the client's canary write is never answered; it reads EOF). The right peer is served afterwards. stderr has exactly 3 log lines, naming `uid=0`, `uid=64998`, `uid=64998`, and no payload (no canary) |
| CHK-M10-118 | APP | W | `TestPeerCheck/expected_uid_0_serves_root_only` | PASS | Expected uid 0: uid 64999 with gid 0 is refused (CHK-M10-321, the gid is not compared). Root is served |
| CHK-M10-119 | APP | W | `TestFromSystemdRefusals` (11 subtests) | PASS | REQ-235 (2). Each case is refused with its own one-line error naming the check, and nothing accepted. `LISTEN_PID` missing, 1, or the parent's pid; `LISTEN_FDS` 0, 2, or unset; fd 3 a regular file, a datagram Unix socket, a non-listening stream socket, a TCP listener; no fd 3 at all. (Exit 1 for the binaries is TASK-228/226's row) |
| CHK-M10-120 | APP | W | `TestCloexecLinux` | PASS | REQ-235 (5), CHK-M10-330. After `FromSystemd`, `/proc/self/fdinfo/3`, `/4` and `/5` (the socket and two extra inherited files) have `O_CLOEXEC`. A scan of every fd above 2 finds none without `FD_CLOEXEC`. A shell exec'd afterwards has exactly fds `0,1,2` (`ls /proc/$$/fd`) |
| CHK-M10-121 | CODE | W | `TestLookupUID` | PASS | `root` → 0; an unknown user → error. Recorded: `bitscan-runner` → 999 (the WSL system user). The test build is pure Go |
| CHK-M10-122 | CODE | W | `TestNoOtherListenerStatic` | PASS | REQ-235 (6), an AST scan of all non-test agent code. The only `net.FileListener` is in `internal/sdsock/listen_linux.go`. No `net.Listen*`, `syscall.Socket`/`Bind`/`Listen` or `unix.Socket`/`Bind`/`Listen` anywhere. (The G8 half is in TASK-211) |
| CHK-M10-320 | CODE | W | plant: the peer check removed | PASS (red) | `TestPeerCheck` (2 subtests) failed. The VM half (G76) is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-321 | CODE | W | plant: the gid compared instead of the uid | PASS (red) | `TestPeerCheck` (2 subtests) failed |
| CHK-M10-330 | CODE | W | plant: fd 3 left without close-on-exec | PASS (red) | `TestCloexecLinux` failed. VM half NOT RUN |
| extra 217a | CODE | W | plant: no `LISTEN_PID` check | PASS (red) | 3 `LISTEN_PID` subtests failed (served instead of refused) |
| extra 217b | CODE | W | plant: no `LISTEN_FDS` check | PASS (red) | 3 `LISTEN_FDS` subtests failed |
| extra 217c | CODE | W | plant: no `SO_ACCEPTCONN` check | PASS (red) | the non-listening stream socket subtest failed |
| extra 217e | CODE | W | plant: only fd 3 marked close-on-exec | PASS (red) | `TestCloexecLinux` failed (fds 4 and 5 inheritable) |

### Acceptance (TASK-217: "a Unix socket passed as fd 3 to a child test process: REQ-235 (1), (2) and (5) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-235 (1) expected uid accepted; any other (0 included) closed before a byte is read; one log line with the uid only | CHK-M10-117, -118 | PASS |
| REQ-235 (2) bad `LISTEN_*` or fd 3 refused | CHK-M10-119 | PASS |
| REQ-235 (5) fd 3 `O_CLOEXEC`; a plugin sees only 0, 1, 2 | CHK-M10-120 | PASS |
| REQ-235 (6) static | CHK-M10-122 (+ G8, TASK-211) | PASS |
| REQ-235 (3) on a sandbox host (group member closed; non-member EACCES) | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-118 |
| REQ-235 (4) busy | TASK-225 (CHK-M10-164) | — |

No finding.

## TASK-218


Tester: tester-m10, 2026-10-30. Full rigor (runner client, TS §8.2 second approval). REQ-245 (the client half), REQ-234; TS §3.5 L249, §3.7 L282; #130 (f), (g), (j), #131 (a), (c).

Code under test (impl-agent-m10b, `work/reports/TASK-218-impl.md`): `agent/internal/agent/runnerclient/client.go` (sha256 `d41cbab0c072b17e…`). Test file (new): `agent/internal/agent/runnerclient/client_test.go` (`bc6405b7353cdb50…`). Plan rows: CHK-M10-051 to -058, plus mutation row CHK-M10-392 (the client half).

The fake runner is a Unix socket in a temporary directory that plays a #130 frame script per connection and records each request. The fake clock fires its timers only when the test moves it, and moves only when the client's own timer of the expected length is armed, so the tests use no sleeps for ordering. The busy row runs on Linux (impl note: an AF_UNIX reset on Windows drops the buffered reply).

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/agent/runnerclient/`, run 3 times | **35/35 passed** each time, 0 failed, 0 errors, 0 skipped |
| static | `go vet` (Windows); `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/agent/runnerclient/` | clean |
| plants | 7 | **7/7 red** |

Two test bugs were fixed before the verdict:
- the deadline rows armed the clock against the dial's stale timer;
- the busy rows moved the clock while a request was in flight.

Both now wait for the exact timer, and three back-to-back runs were green.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-051 | CODE | W | `TestNormalRun` | PASS | Exactly one request on one connection: `v` 1, `max_parallel_plugins` the value passed (5), `job` equal to the job given (id and plugins deep-equal). Results 2, 1, 3 are delivered once each, in the order received. Returns nil after `done` |
| CHK-M10-052 | CODE | W | `TestFailureWords` (26 subtests) | PASS | #131 (c) words. No socket → `connect`. A bound socket with no listener (ECONNREFUSED) → `connect`. `refused <w>` → `refused_<w>` for all 12 words other than busy. EOF after 2 of 5 → `broken` with 2 delivered. EOF before any reply → `broken`. A frame cut inside its body → `broken`. An oversize reply header, a malformed reply, `done` as the first reply → `protocol`. A result for a plugin not in the job, and a repeated result → `protocol`, with the bad item **not** delivered (CHK-M10-392 client half). A second `accepted`, or `refused` after `accepted` → `protocol`. Every failure used exactly one connection (never resent). **Recorded:** `done` after 1 of 3 results → `protocol`. **Not run:** EACCES on the socket (the test runs as root, which bypasses the mode); `connect` is covered by the two rows above |
| CHK-M10-052 (timeout), CHK-M10-054 | CODE | W | `TestDeadlines` | PASS | No first reply: no return at 29 s, `timeout` at 30 s. After `accepted` with `timeout_s` 30/31/32: no return at 61 s, `timeout` at 62 s (max + 30 s) |
| CHK-M10-053 | CODE | W | `TestBusy` | PASS | Always busy: redialled every 2 s, `refused_busy` after 30 s, 15 connections in total (recorded). Busy 3 times then accepted → a normal run with its result |
| CHK-M10-055 | CODE | W | `TestCancel` | PASS | `ctx` cancelled mid-run → `context.Canceled`, not a `*Failure`. The fake runner sees the connection close |
| CHK-M10-057 | CODE | W | `TestOnResultError` | PASS | An `onResult` error stops the run after the first result, with a non-`Failure` error |
| CHK-M10-056, -058 | CODE | W | `TestClientStatic` | PASS | `client.go` imports no log, slog, `os/exec` or `internal/runner/*` other than `proto`. It calls no `time.Now`/`Sleep`/`After`/`NewTimer` (only the injected clock) and prints nothing. `Socket` = `/run/bitscan/runner.sock` |
| plant 218a | CODE | W | the busy retry removed | PASS (red) | `TestBusy` failed (both subtests) |
| plant 218b | CODE | W | busy retried for 60 s | PASS (red) | `TestBusy/always_busy` failed |
| CHK-M10-392 | CODE | W | a result for a plugin not in the job (or repeated) delivered | PASS (red) | `TestFailureWords` (2 subtests) failed. The handler half is in TASK-223 |
| plant 218d | CODE | W | first reply limit 31 s | PASS (red) | `TestDeadlines/no_first_reply_in_30_s` failed |
| plant 218e | CODE | W | EOF before `done` reported as `protocol` | PASS (red) | `TestFailureWords` (2 EOF subtests) failed |
| plant 218f | CODE | W | the gap ignores `timeout_s` | PASS (red) | `TestDeadlines/gap_after_accepted` failed |
| plant 218g | CODE | W | `refused` without the reason word | PASS (red) | 11 `refused_*` subtests failed |

### Acceptance (TASK-218: "against a fake runner on a Unix socket with a fake clock, every #131 (a) failure kind yields its word, busy is retried every 2 s for 30 s, and a normal run delivers each result once, in order received")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| every #131 (a) kind → its word | CHK-M10-052, -054 | PASS (EACCES not run as root; covered by the connect rows) |
| busy every 2 s for 30 s | CHK-M10-053 | PASS |
| a normal run delivers each result once, in order | CHK-M10-051 | PASS |

No finding.

### r1 (reviewer-m10 finding 1; the lead's two r1 rows)

Test files only; no product change. `client_test.go` is now `6513d8585d9d99e7…`, and there's a new `client_linux_test.go` (`a322a5e9abb05021…`).
- The "socket with no listener" subtest (`syscall.Bind` of AF_UNIX, which fails with "invalid argument" on Windows) moved to `client_linux_test.go` as `TestConnectRefusedLinux`. It isn't built on Windows, so nothing is skipped.
- New portable row `TestConnectAfterListenerGone`: a runner socket whose listener closed and whose file was removed → `connect`, on Windows and Linux.
- New row `TestConnectPermissionDeniedLinux` (builder checklist 21). A root-owned 0660 socket. A copy of the test binary runs the client as uid 65534 (`setpriv --reuid=65534 --regid=65534 --clear-groups`), so the connect gets EACCES. Asserted: word `connect`, a `*Failure` (not a ctx stop), 0 results, 0 connections reaching the runner, and a return in under 5 s with the real clock (a busy retry would take 30 s). **Recorded:** `WORD=connect FAILURE=true CTX=false RESULTS=0 UID=65534 SECONDS=0.0`.

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 -v ./internal/agent/runnerclient/` | **35/35 passed**, 0 failed, 0 errors, 0 skipped |
| W (WSL, -race, root; the EACCES child runs as nobody) | `go test -race -count=1 -v ./internal/agent/runnerclient/` | **38/38 passed**, 0 failed, 0 errors, 0 skipped |
| plant 218h | EACCES mapped to `refused_busy` (so it is retried as busy) | **red**: `TestConnectPermissionDeniedLinux` failed after 28 s (the busy retry) |
| static | golangci-lint, Windows and `GOOS=linux` | clean |

The acceptance table is unchanged; the "EACCES not run" note above is now **run** (W, as uid 65534).

## TASK-219


Tester: tester-m10, 2026-10-30. Full rigor (spool overflow, TS §8.2 second approval). REQ-248; TS §3.3 L226, §6.5 L1184, §4.5 L593; #140.

Code under test (impl-agent-m10b, `work/reports/TASK-219-impl.md`): `agent/internal/spool/overflow.go` (sha256 `b40f234e8fecaadf…`) and the `Put` call site in `spool.go` (`3e9e668de2723114…`). Test file (new): `agent/internal/spool/overflow_test.go` (`9dcb385ff311e2af…`, internal package, for the crash hook). Plan rows: CHK-M10-059 to -064, plus mutation rows CHK-M10-364 and -365.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=1 ./internal/spool/` (whole package, TASK-212 rows included) | ok: **29/29 passed** (L builds no Linux file), 0 failed, 0 errors, 0 skipped |
| W (WSL, -race) | `go test -race -count=1 -v ./internal/spool/` | **31/31 passed** (8 of them overflow tests and subtests), 0 failed, 0 errors, 0 skipped |
| static | golangci-lint (Windows) | clean |
| plants | 5 | **5/5 red** |

One test bug was fixed before the verdict: the across-jobs row drained without finishing the jobs, so the held batches never came out and the asserts held vacuously. It now finishes both jobs and checks the item counts first.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-059 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (1): a 1 MiB spool and 30 results of 64 KiB stdout. After every `Put`, both `Size()` and the disk bytes are ≤ 1,048,576, and `Size()` = disk. The oldest results are markers and the newest are whole, with no whole result before a marker. **Recorded:** 15 markers, 15 whole. The conversion is logged and no output is in the log |
| CHK-M10-060 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (2): once drained, every one of the 30 plugins is posted exactly once, in seq order. Each marker keeps its own `plugin_uuid`, `started_at` and `finished_at` (CHK-M10-365: no result vanishes) |
| CHK-M10-061 | CODE | L, W | `TestOverflowOldestFirst` | PASS | REQ-248 (3): each marker passes `proto.NewResult` and the strict `ResultItem` decode. `error` = `spool_overflow`, `exit_code` null, empty streams, flags false (the #140 shape) |
| CHK-M10-062 | CODE | L, W | `TestOverflowSparesInFlight` | PASS | REQ-248 (4): with 4 results handed out by `Next` and not answered, a `Put` that needs room converts none of them; the new item is stored as a marker instead. After the `Ack`, later items that aren't in flight are converted first |
| CHK-M10-063 | CODE | L, W | `TestOverflowAcrossJobs`, `TestOverflowNewItemAndMarkerDrop` | PASS | Across jobs, the older job's results convert first: job 1 `[marker × 3]`, job 2 whole. A result bigger than the whole spool is stored as a marker, not refused. With 39 more markers into a 3,000-byte spool, the oldest markers are dropped with a log line, the size stays ≤ the bound with `Size()` = disk, everything left is a marker, and the newest marker survives |
| CHK-M10-064 | CODE | L, W | `TestOverflowConversionAtomic` (3 subtests) | PASS | A crash at `created`, `written` or `synced` while a result is rewritten as a marker → after reopen the item is still the whole, complete result under its seq, nothing is dropped, and size = disk |
| CHK-M10-364 | CODE | W | plant: newest converted first (reverse order) | PASS (red) | `TestOverflowOldestFirst`, `AcrossJobs`, `SparesInFlight` failed |
| CHK-M10-365 | CODE | W | plant: a dropped result becomes `runner_unavailable` (no `spool_overflow` marker) | PASS (red) | the overflow tests failed |
| extra 219a | CODE | W | plant: in-flight items converted | PASS (red) | `TestOverflowSparesInFlight` failed |
| extra 219b | CODE | W | plant: no new-item marker (`ErrFull` instead) | PASS (red) | `NewItemAndMarkerDrop`, `SparesInFlight` failed |
| extra 219c | CODE | W | plant: whole results dropped instead of markers | PASS (red) | `TestOverflowNewItemAndMarkerDrop` failed |

### Acceptance (TASK-219: "REQ-248 (1), (2) and (4) hold and the size never exceeds the bound after any Put")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| (1) oldest → markers, newest whole, ≤ 1 MiB | CHK-M10-059, plant 364 | PASS |
| (2) each converted result posted exactly once as its own marker | CHK-M10-060, plant 365 | PASS |
| (3) markers valid; M9 intake stores them ERROR `spool_overflow` | CHK-M10-061 (the M9 intake half is M9's REQ-215 (3), unchanged) | PASS |
| (4) an in-flight batch not converted | CHK-M10-062, plant 219a | PASS |
| size never over the bound after any `Put` | every `Put` in CHK-M10-059, -063 | PASS |

No finding.

## TASK-220


Tester: tester-m10c, 2026-11-01. Full rigor (agent, TS §8.2 second approval). REQ-246 (1)–(6), REQ-248 (1), (2) at binary level; TS §3.3 L222–L226, §3.5 L253; #139 (d), (e), #141. Decisions: "#140 reading: in-flight protection covers only an outstanding HTTP attempt" (r1: release before the back-off, rebuild with `Next`).

Code under test: `agent/internal/agent/loops/results.go` at r1, using `Spool.Release` (TASK-212 r1). Impl report: `work/reports/TASK-220-impl.md`.

Test files:
- `agent/internal/agent/loops/results_test.go` (new, portable, 10 tests and 13 subtests). It runs the real `Sender` over a real spool in a temporary directory. Only `clock.After` waiters move time, and the earliest is fired once the sender has been quiet for 30 ms. Plus a fake manager.
- Binary level: `e2e/agent_binary_m10.sh` scenario `overflow` (TASK-227 report). It runs the built agent with `spool_max_mb: 1`. The fake runner sends 5 results of 64 KiB, pauses 32 s, then sends 25 more. The fake manager answers 503 to every batch holding items until the runner is done, and 200 afterwards.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| L (Windows) | `go test -count=5 -run TestSender ./internal/agent/loops/` | **115/115 passed** (23 × 5) |
| W (WSL, -race) | `-count=3 -run 'TestSender\|TestRelease'`; then the whole of `./internal/spool/ ./internal/agent/loops/` | ok ×3; **158/158 passed** |
| W, binary | overflow walk | **18/18 passed** |
| plants | 7 in `results.go`/`jobs.go` (unit), plus plant (d) through the binary walk | **8/8 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-065 | CODE | L, W | `TestSenderBatches` | PASS | A finished job of 120 gives posts `0,50,50,20F`. The start notice body is exactly `{"results":[],"final":false}`. Items go once, in seq order, and nothing follows the final |
| CHK-M10-066 | CODE | L, W | `TestSenderByteBound` (2) | PASS | Every body is ≤ 1,572,864 bytes of uncompressed JSON. 50 items of 32 KiB that escape (`"\`, U+0001, `é`) went as `0,30,20F`. Maximal items (65,536 × U+0001 stdout and 16,384 × U+0002 stderr, 6 bytes each escaped) went 3 per batch (recorded) |
| CHK-M10-067 | CODE | L, W | every test (`posts`) | PASS | Every body is gzip (`Gzip` set, decompresses) and decodes strictly as `ResultsRequest` |
| CHK-M10-068 | CODE | L, W | `TestSenderAnswerClasses` (11) | PASS | REQ-246 (4):<br>• 503 ×3 then 200: retry gaps exactly `[10s 20s 40s]`, stored once;<br>• 429: kept, the same body 10 s later (CHK-M10-363);<br>• 409, 400, 404, 413, 422, 403 `rate_limited` and 403 `forbidden` on batch 2: `0,50,50,50F`, batch 2 sent once, batch 3 still posted, never retried, the "not retried" line with `results <status> <type>` (last_error), spool empty (CHK-M10-362);<br>• 403 `pending_approval`: kept, the same body after 10 + 20 s;<br>• 401: the sender stops after 1 post;<br>• cap: gaps `[10s 20s 40s 1m20s 2m40s 5m0s 5m0s 5m0s]` |
| CHK-M10-069 | CODE | L, W | `TestSenderThirtySeconds` | PASS | REQ-246 (5). Three results of a running job, then silence. The sender waits exactly 30 s, nothing is posted at 29 s, and the batch is posted 30 s after the first result (3 items, not final) |
| TASK-220 documented late-post limit | CODE | L, W | `TestSenderLatePostLimit` | PASS | A Wake with nothing new arms the timer early, and a result spooled 20 s later is posted **40 s** after it was spooled (recorded). That's within the stated "at most 30 s later than the rule" (bound 30–60 s) |
| CHK-M10-070 | CODE | L, W | `TestSenderFinalWaitsForEarlier` | PASS | REQ-246 (6). Batch 2 is answered 503 twice: posts `0,50,50,50,50,50F`. Posts 2–4 are all batch 2, and the final waits until batch 2 is answered; posts are strictly ordered |
| CHK-M10-071 | CODE | L, W | `TestSenderWake` | PASS | A finished job goes out on `Wake` with no clock movement. 100 concurrent Wakes give `0,3F`, posted once |
| CHK-M10-072 | CODE | L, W | `TestSenderLogsNoOutput` | PASS | With a 409 drop, the log holds no `M10SENDCANARY` stdout and no token |
| r1: the retry is a fresh body; a converted item goes as its marker | CODE | L, W | `TestSenderRetryIsFresh` | PASS | Driven as TASK-223 drives it: a wake after StartJob and after each Put. The running job's 4 × 64 KiB batch is answered 503, released, and its 10 s back-off begins. A 5th result Put during the back-off converts the oldest released item. The retry body differs from the first. Recorded: `[001:spool_overflow 002:whole 003:whole 004:whole 005:whole]` |
| (a) binary: oldest become markers, including the in-flight batch; newest stay whole | APP | W | overflow walk | PASS | The first 503'd batch held plugins 001–005. At the end, markers are plugins 1–15 (001–005 among them) and 16–30 are whole. The spool's file bytes never exceeded the bound (max 991,038 of 1,048,576 over 165 samples) |
| (b) binary: every plugin eventually posted | APP | W | overflow walk | PASS | Once the manager returns, all 30 plugins are posted exactly once (as a result or a marker, in the marker shape) and the final is posted |
| (d) plant: no Release before the back-off | CODE | W | `results.go` Release skipped: overflow walk; and unit | PASS (red) | Walk 13/18. After the 503 the batch stayed in flight, nothing more was posted, 0 markers and 0 whole items arrived, and the wait timed out. Unit: `TestSenderRetryIsFresh` and the pending_approval row never got their retry |
| CHK-M10-360 | CODE | W | `maxBatch = 51` | PASS (red) | `TestSenderBatches` "posts 0,18F, want 0,50,50,20F", and the 409 row was red |
| CHK-M10-361 | CODE | W | `maxBatchBody = 3_000_000` | PASS (red) | "a body of 2955597 bytes uncompressed (bound 1,572,864)" |
| CHK-M10-362 | CODE | W | a drop answer retried | PASS (red) | "posts 0,50,50,50,50F, want 0,50,50,50F with batch 2 sent once" |
| CHK-M10-363 | CODE | W | a 429/503 dropped | PASS (red) | The 503 ×3 and 429 rows never got their retry |
| CHK-M10-368 | CODE | W | the start notice acked without posting | PASS (red) | "posts 50,50,20F, want 0,50,50,20F" |
| extra 220a | CODE | W | `holdYoung = 29 s` | PASS (red) | "the sender waits 29s, want 30 s" |

### Acceptance (TASK-220: "fake clock and fake manager: REQ-246 (1)–(6) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-246 (1)–(6) | CHK-M10-065 to -071 | PASS |
| r1 release and rebuild | r1 row, (a), (b), plant (d) | PASS |

## TASK-221


Tester: tester-m10c (replacing tester-m10), 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-239 (1)–(5), (7), REQ-241 (5) (spawn half), REQ-238 (3); TS §3.5 L249, §3.7 L276, L283; #31, #135 (a), #136 (a)–(c), (f); decisions rows "TASK-221 r1: confined temp-dir chmod" and "TASK-221 r2: keep the main OS thread out of Spawn"; builder checklist items 21 and 22.

Code under test: `agent/internal/runner/spawn_linux.go` (r1: `RemoveTempDir` chmods through `os.Root`; r2: comment only) and `agent/cmd/bitscan-runner/main.go` (r2: `func init() { runtime.LockOSThread() }`). Impl report: `work/reports/TASK-221-impl.md` (r1, r2).

Test file: `agent/internal/runner/spawn_delegated_linux_test.go` (build tag `linux && delegated`; written by tester-m10, extended here). Changes by tester-m10c:
- a `TestMain` that locks m0 to the main goroutine, mirroring the r2 `init`;
- `threadNiceness`: every thread's niceness (stat field 19) and I/O class (`ioprio_get`);
- the CHK-M10-128 part 2 row now runs 20 spawns from 4 goroutines;
- the symlink-swap race runs 1,000 rounds instead of 300 (the r0 plant once survived to round 216);
- `os.Chmod` → `unix.Chmod` and an unused `nolint` dropped, so the file is lint-clean with `--build-tags delegated`.

### Where and how

All rows ran delegated and unprivileged, as the unit's user (checklist item 21), in WSL Ubuntu 24.04 (cgroup2fs, systemd 255):

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p WorkingDirectory=/opt/m10c <go test -c -race -tags delegated binary> -test.run Delegated -test.v`

The test logged its identity: `uid 999 euid 999 gid 988; CapInh/CapPrm/CapEff/CapBnd/CapAmb 0000000000000004; NoNewPrivs 1`. These files are Linux-only, so there is no Windows row. Plants ran in throwaway copies (`/root/m10c/w-mut-<plant>`); the worktree holds none.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| WD r1 (before r2) | delegated binary, `-test.run Delegated` | 14/15 passed, 1 failed (CHK-M10-128 part 2, below), 0 skipped |
| WD r2 ×3 | same, after the r2 product change and the TestMain lock | **15/15 passed** each time (TestDelegatedCgroups 5, TestDelegatedSpawn 7, TestDelegatedRemoveTempDir 3), unit exit 0 |
| static | `gofmt -l`; `go vet` and `golangci-lint run` on Linux, with and without `--build-tags delegated`, `./internal/runner/... ./internal/agent/...` | clean, 0 issues |
| plants | 14 plants, each in its own copy, delegated as bitscan-runner | **14/14 red** |

### Round 1 failure and fix (r2)

| Check | Expected | Actual on r1 | Diagnosis |
| --- | --- | --- | --- |
| CHK-M10-128 part 2 | every runner thread at niceness 0 after the spawns | one thread at niceness 10: tid == pid (m0), state S, `wchan futex_do_wait`; the other 6 threads were at 0 | Spawn's locked goroutine sometimes ran on m0. When a locked goroutine exits on m0, the Go runtime parks that thread forever instead of ending it, so m0 stayed at nice 10 and I/O idle. Reported to `main`. Ruled option (a), a product fix: TASK-221 r2 adds the `init` lock in `cmd/bitscan-runner`, and the test binary gets the same lock in `TestMain`. **1/1 passed at r2** (×3 runs) |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-127 | APP | WD | `TestDelegatedSpawn/environment,_descriptors,…` | PASS | REQ-239 (1), (2), (4), (5), (7). Values:<br>• `/proc/$$/environ` is exactly `PATH=/usr/sbin:/usr/bin:/sbin:/bin`;<br>• `readlink /proc/$$/fd/0` is `/dev/null`;<br>• the shell's fds are `0,1,2`;<br>• cmdline is `/bin/sh\|-c\|<execute>`;<br>• `pwd` is the `Spawned.TempDir` under `/tmp/bitscan-p-`, mode 700, `ls -A` empty;<br>• `id -u` is 999, not 0;<br>• the temp dir is gone after `RemoveTempDir` |
| CHK-M10-128 | APP | WD | `TestDelegatedSpawn/niceness_10_and_I/O_class_idle` | PASS (r2) | Part 1: the plugin's stat field 19 is 10 and `ionice -p $$` is `idle`. Part 2: after 20 concurrent spawns, every runner thread, m0 included, is at niceness 0 and not I/O idle (r1 FAIL above) |
| CHK-M10-129 | APP | WD | `…/born_in_its_own_cgroup,_with_its_first_fork` | PASS | The plugin's own `/proc/$$/cgroup` and its first fork's are the same `…/p-<n>`, never `supervisor` (#136 (a), REQ-238 (3)) |
| CHK-M10-130 | APP | WD | `…/no_Pdeathsig` | PASS | `sleep 2; echo done` exits 0 with `done`: it isn't killed when the start thread is discarded (#136 (c)) |
| CHK-M10-131 | APP | WD | `TestDelegatedRemoveTempDir/static` | PASS | A tree with a `0000` subdirectory chain and a symlink `sub` → an outside directory (mode 0500, holding `keep`). After `RemoveTempDir`, the tree is gone (Lstat ENOENT), the outside mode is still 0500 and `keep` is still there |
| CHK-M10-131 r1 (decisions row; checklist 22) | APP | WD | `TestDelegatedRemoveTempDir/race` | PASS | 1,000 rounds. A goroutine (the "parallel plugin") keeps swapping the locked subdir `x` for a symlink to the runner-owned 0500 outside directory and back, while `RemoveTempDir` runs. The outside mode stayed 0500 in every round |
| CHK-M10-132 | APP | WD | `…/a_cgroup_that_can't_be_entered` | PASS | The cgroup is removed before `Spawn`. Result: `ErrCgroup` (`openat p-N/cgroup.procs: no such file or directory`), `Spawned` nil, the marker file is never touched, and 0 temp dirs are left |
| (extra) | APP | WD | `…/each_plugin_its_own_temp_dir_and_cgroup` | PASS | Two plugins get a different `pwd` and cgroup |
| CHK-M10-331 (G72 half) | CODE | WD | plant `Env: os.Environ()` | PASS (red) | ENV showed `LANG…PATH=/usr/local/sbin…USER=bitscan-runner…INVOCATION_ID…`. VM half NOT RUN (VM hold, the named gate exception, decisions 2026-11-01 (1)) |
| CHK-M10-332 | CODE | WD | plants `TMPDIR=<dir>` added; `PATH` with `/usr/local/bin` | PASS (red ×2) | ENV mismatch in each |
| CHK-M10-333 (G72 half) | CODE | WD | plant `Stdin: os.Stdin` | PASS (red) | `FD0 = "pipe:[17196]"`. VM half NOT RUN |
| CHK-M10-334 (G72 half) | CODE | WD | plant: `setpriority` skipped | PASS (red) | `NICE "0" IO "idle"`. VM half NOT RUN |
| CHK-M10-335 (G72 half) | CODE | WD | plant: `ioprio_set` skipped | PASS (red) | `NICE "10" IO "none: prio 0"`. VM half NOT RUN |
| CHK-M10-336 (G72 half) | CODE | WD | plant: `cmd.Start()` outside `StartIn` | PASS (red) | SELF and KID were both `…/supervisor`, and a spawn into a removed cgroup started a process. VM half NOT RUN |
| CHK-M10-341 (spawn half) | CODE | WD | plant: `RemoveTempDir` does nothing | PASS (red) | "the temp dir is still there", "the temp tree is still there", 7 temp dirs left |
| extra 221a | CODE | WD | plant: the r0 path-based `filepath.WalkDir` + `unix.Chmod(path, 0o700)` | PASS (red ×5) | Red at rounds 22, 11, 12, 216 and 16 at 300 rounds, then at rounds 161 and 6 at 1,000 rounds: "outside dir mode 700: a chmod left the temp tree" |
| extra 221b | CODE | WD | plant: no chmod retry | PASS (red) | `unlinkat …/locked/deep/f: permission denied` (REQ-240 (9) cleanup) |
| extra 221c | CODE | WD | plant: `SysProcAttr{Pdeathsig: SIGKILL}` | PASS (red) | The plugins were killed when the start thread ended (exit 137, empty output) |
| extra 221d | CODE | WD | plant: `defer runtime.UnlockOSThread()` in the start goroutine | PASS (red) | 6 non-m0 threads at niceness 10 and I/O idle |
| extra 221e | CODE | WD | plant: the m0 lock removed (TestMain's lock dropped, mirroring the r2 `init`) | PASS (red) | "runner thread 1424 (m0, the main thread) state S niceness 10 ioprio-idle true". The same plant against the built runner binary (main.go `init` removed) is a TASK-228 row |
| extra 221f | CODE | WD | plant: temp dir re-moded 0755 | PASS (red) | `MODE = "755"` |

### Acceptance (TASK-221: "under `systemd-run -p Delegate=yes`, REQ-239 (1)–(5) and (7) hold for a test command and the child appears in its own cgroup from its first instruction")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-239 (1), (2), (4), (5), (7) | CHK-M10-127 | PASS |
| REQ-239 (3) | CHK-M10-128 | PASS (r2) |
| born in its own cgroup, first instruction and first fork | CHK-M10-129 | PASS |
| r1: the chmod never leaves the temp tree; the tree is still removed | CHK-M10-131, -131 r1, plant 221a | PASS |
| r2: no runner thread is left lowered | CHK-M10-128 part 2, plants 221d, 221e | PASS |
| REQ-239 (1)–(5) on a sandbox host | — | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the WD rows above, on the real kernel as bitscan-runner |

Every TASK-221 delegated test is in the binary that TASK-229 r1's CI step runs (`-test.run Delegated`).

## TASK-222


Tester: tester-m10, 2026-10-30. Full rigor (capread server, TS §8.2 second approval). REQ-252 (1)–(4); TS §3.7 L277, L437–L484, L493, L500–L501; #142. The lead added two rows: (a) a client that never reads its reply is cut off after about 10 s and the next client is served; (b) a missing binary answers `not_installed` and a non-executable one answers `error failed 126`. Plus a plant that removes the write deadline.

Code under test (impl-agent-m10b, `work/reports/TASK-222-impl.md`): `agent/internal/capread/capread.go` (sha256 `09b1683a77054ad8…`) and `serve_linux.go` (`7b55e70f1776b81f…`). Test file (new): `agent/internal/capread/capread_linux_test.go` (`9a18cf104ab55b8f…`). It's an internal package test: the two-name table is swapped for harmless `/bin/sh` scripts and `/usr/bin/env`. Plan rows: CHK-M10-137 to -142, plus mutation rows CHK-M10-371 to -377 (the G74 halves).

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race, root) | `go test -race -count=1 -v ./internal/capread/` | **9/9 passed**, 0 failed, 0 errors, 0 skipped |
| L (Windows) | the server is Linux only (`serve_linux.go`); the package's portable `client.go` is TASK-226's | n/a for this task |
| static | `GOOS=linux golangci-lint run --uniq-by-line=false ./internal/capread/` | clean |
| plants | 10 | **10/10 red** |

Two test bugs were fixed before the verdict:
- an environment probe through `/bin/sh` saw the shell's own `PWD`; it now uses `/usr/bin/env` with no shell;
- the peer-check client didn't catch the reset of a refused connection.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-137 | APP | W | `TestNamesRunFixedArgvEmptyEnv`, `TestRealTableIsTheSpecs` | PASS | REQ-252 (1). `nft_ruleset\n` → `ok\nNFT-OUT\n`: stdout only, the command's stderr is never sent. The command's argv is exactly its table entry (no request text). `audit_rules\n` runs in `/`. **`/usr/bin/env` as the command prints nothing**: the environment is empty (CHK-M10-373). No output or environment value appears in the log. The real table is exactly `nft_ruleset` → `/usr/sbin/nft -j list ruleset` and `audit_rules` → `/usr/sbin/auditctl -l`, and `Known` accepts only those two names. `Socket` = `/run/bitscan/capread.sock` |
| CHK-M10-138 | APP | W | `TestRefusedRequests` | PASS | REQ-252 (1). Each of these answers exactly `error unknown_request` and runs nothing (a marker file is never created): `nft_ruleset x`, `NFT_RULESET`, `../nft`, `/usr/sbin/nft`, an empty line, 33 bytes without LF, 32 bytes + LF, `nft_ruleset` without LF then EOF, `nft_ruleset\r\n`, two names, a third name, a NUL in the name, a leading or trailing space, and an empty request (CHK-M10-371, -372) |
| CHK-M10-139 | APP | W | `TestPeerCheckThroughSdsock` | PASS | REQ-252 (2), through the real `sdsock`. A child copy of the test binary gets the socket as fd 3 with `LISTEN_PID=$$`, expecting uid 64990. Peers uid 0, 64991 and 998 (through `setpriv`) are closed with no reply. Uid 64990 gets `ok\nserved` (CHK-M10-374) |
| CHK-M10-140 | APP | W | `TestOutcomes` | PASS | REQ-252 (3). Exactly 1 MiB of output → `ok` + 1,048,576 bytes. 1 MiB + 1 → exactly `error too_large`, with **none** of the output sent (CHK-M10-376). `exit 3` → `error failed 3`; `kill -9 $$` → `error failed 137`. Lead's (b): a missing binary → `error not_installed`, and a non-executable file → `error failed 126`. `sleep 60` → `error timeout`, answered in 9–12 s (the 10 s spec timeout, wall time; CHK-M10-375). Constants: 10 s, 1 MiB, 32 bytes, 5 s |
| CHK-M10-141 | APP | W | `TestSequential` | PASS | REQ-252 (4): two clients at once. The second command starts after the first ends (timestamps written by the commands) (CHK-M10-377) |
| CHK-M10-142 | APP | W | `TestRequestDeadline` | PASS | A client that connects and sends nothing doesn't hold the helper: the next client is answered within 8 s (the 5 s request deadline), and the idle client gets nothing |
| lead (a) | APP | W | `TestStalledReaderCutOff` | PASS | A client sends `big\n` (1,000,000 bytes of output) and never reads. The next client is served after **9.85 s** (recorded; the bound is 8–15 s) |
| CHK-M10-371 | CODE | W | plant: an unknown name runs a command | PASS (red) | `TestRefusedRequests` failed. The VM half is NOT RUN (safety-classifier refusal (VM sandbox)) |
| CHK-M10-372 | CODE | W | plant: the request name added as an argument | PASS (red) | `TestNamesRunFixedArgvEmptyEnv` failed |
| CHK-M10-373 | CODE | W | plant: `cmd.Env = os.Environ()` | PASS (red) | `TestNamesRunFixedArgvEmptyEnv` failed (the env probe printed the environment). VM half NOT RUN |
| CHK-M10-374 | CODE | W | plant: the peer check removed (in `sdsock`) | PASS (red) | `TestPeerCheckThroughSdsock` failed. VM half NOT RUN |
| CHK-M10-375 | CODE | W | plant: timeout 60 s | PASS (red) | `TestOutcomes` failed |
| CHK-M10-376 | CODE | W | plants: (a) the cap removed; (b) the cut output sent as `ok` | PASS (red) | `TestOutcomes` failed for each |
| CHK-M10-377 | CODE | W | plant: requests served concurrently | PASS (red) | `TestSequential` failed |
| lead (a) plant | CODE | W | plant: the write deadline removed (read deadline only, no reply deadline) | PASS (red) | `TestStalledReaderCutOff` failed: the stalled reader held the helper past 25 s |
| extra 222b | CODE | W | plant: no `not_installed` check | PASS (red) | `TestOutcomes` failed |

### Acceptance (TASK-222: "unit with the in-package command table swapped and a Unix socket: REQ-252 (1)–(4) hold")

| REQ-252 | Rows | Verdict |
| --- | --- | --- |
| (1) the two names, fixed argv, empty env; every other request `unknown_request` and nothing run | CHK-M10-137, -138 | PASS |
| (2) peer uid 0, `bitscan` or any other: closed without a reply | CHK-M10-139 (uid 998 stands in for `bitscan`) | PASS |
| (3) 10 s timeout; over 1 MiB → `too_large` with nothing sent | CHK-M10-140 | PASS |
| (4) one at a time | CHK-M10-141, -142, lead (a) | PASS |
| (5), (6) on a sandbox host (real `nft`, `auditctl`, CapEff 0x40001000) | — | NOT RUN (safety-classifier refusal (VM sandbox)); cover CHK-M10-137 to -141 |

No finding.

## TASK-223


Tester: tester-m10c, 2026-11-01. tester-m10 wrote the PD-45 rewrite (`compliance_linux_test.go`, `pull_test.go`) earlier; tester-m10c added the r1 rows, the remaining handler rows and the CHK-M4-223 rewrite. Full rigor (agent, TS §8.2 second approval). REQ-245, REQ-249 (2)–(4), REQ-250 (1)–(3); #28, #78, #131. Decisions rows:
- "TASK-223 (compliance loop) nil-handler choice accepted";
- "PD-45 rewrite of the M4 loops tests accepted";
- "#140 reading …" (TASK-223 r1);
- "The PD-45 compliance tests are Linux-only";
- "User decisions before the M10 merge" (2), the CHK-M4-223 rewrite.

Code under test: `agent/internal/agent/loops/compliance.go` (r1 `fill`), `jobs.go`, `pull.go`, `run.go`, `heartbeat.go`. Impl report: `work/reports/TASK-223-impl.md`.

Test files (Linux-only where they record a job: M4's state store can't fsync a directory on Windows):
- `agent/internal/agent/loops/compliance_linux_test.go`: the PD-45 rows and the nil handler. It was renamed from `compliance_test.go` at main's ruling. tester-m10c fixed one timing assumption (below).
- `agent/internal/agent/loops/compliance_r1_linux_test.go` (new): r1 and the handler rows.
- `agent/internal/agent/loops/pull_test.go`: CHK-M4-223 rewritten, plus a fail-fast in `TestJobPickupRecheckedAtStart`.
- Binary level: `e2e/agent_binary_m10.sh` (TASK-227 report).

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race ./internal/spool/ ./internal/agent/loops/` | **158/158 passed**, 0 failed, 0 skipped |
| W, repeats | `-count=5 -run 'TestR1\|TestNilCompliance'`; `-count=3 -run 'TestHandler\|TestR1'` | ok, 0 failed |
| L (Windows) | `go test ./internal/agent/loops/` | see the gate report: the Linux-only files don't build there. The 5 failing M4 rows are pre-existing (Seen.Add → syncDir) |
| plants | 10 (r1 ×3, nil handler ×2, -367, -369, -384) plus CHK-M10-271 ×9 | **19/19 red** |

### PD-45 old → new (decisions "PD-45 rewrite … accepted")

| Old (M4) | New (M10) |
| --- | --- |
| CHK-M4-220 (#74 single runner_unavailable batch, no runner contact) | `TestPD45ComplianceThroughRunner`, `TestPD45RunnerUnavailableFill`, `TestPD45Results409Dropped` (CHK-M10-073, -074) |
| CHK-M4-221 (#74 batches) | `TestPD45Batches` (CHK-M10-065 at handler level, up to 5,000 plugins) |
| CHK-M4-223 (no `runner.sock`/`"unix"` anywhere in `internal/agent/**`) | **CHK-M10-271** `TestNoOtherJobSourceStatic`, rewritten per the user's decision (2026-11-01 (2)): `runner.sock` and AF_UNIX are allowed only in `internal/agent/runnerclient`; dialling only in runnerclient and transport; listening nowhere. The exec and RunJob/Handle caller assertions are kept |
| CHK-M4-101, CHK-M4-185 | unchanged (sync point per the PD-45 row; REQ-250 (1) has its own row) |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-073 | CODE | W | `TestPD45ComplianceThroughRunner` | PASS | REQ-245 (1), (5), (6): the start notice first, each plugin once, the final last. One runner request with the pulled job and the heartbeat's `max_parallel_plugins` 2. The canary `execute` is never run, logged or stored, and the state dir holds only `seen_jobs.json` and `spool/` |
| CHK-M10-074 | CODE | W | `TestPD45RunnerUnavailableFill`; `TestHandlerFailureWords` (8 words) | PASS | For `connect`, `timeout`, `broken`, `protocol`, `refused_busy`, `refused_foreign_agent`, `refused_replayed` and `refused_malformed`:<br>• the received result is kept;<br>• plugins 2 and 3 are `runner_unavailable`, with the final;<br>• exactly one runner request (CHK-M10-358);<br>• `last_error` = `runner_unavailable: <word>`, then null on the next heartbeat (the `broken` row).<br>**Test fix (mine):** the old row also required the fill items to be *inside* the final batch. #131 (b)/#141 allow an empty final after they're posted, and it was red once in WSL. It now asserts both fill items are posted and the final is the last post. main accepted the fix; reviewer-m10c is to confirm it isn't a loosening |
| CHK-M10-076, -359 (binary) | APP | W | walk `sigterm` | PASS | A cancel mid-job keeps the spooled result and sends no final and no fill; after a restart the result is posted, still with no final, and nothing is resent |
| CHK-M10-077 | CODE | W | `TestPD45ComplianceThroughRunner`; walk (all scenarios) | PASS | No command or pattern canary in any state file; agent output carries no canary |
| CHK-M10-078 | CODE / APP | W | `TestHandlerOneJobAtATime`; `TestJobPickupRecheckedAtStart` (M4); walk `invheld` | PASS | CHK-M10-369: while job 1 is held, the runner gets 1 call; after release both run, at most 1 at once over 2 calls. REQ-249 (2): a job whose `pickup_by` passes while an earlier one runs is never started and is logged. CHK-M10-370 (binary): inventory is uploaded while the runner holds the compliance job |
| CHK-M10-079 | CODE | W | `TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`; `TestHeartbeatRunStateValues` (M4) | PASS | REQ-250 (1): while results wait (503), the heartbeat's `spool_bytes` equals `Spool.Size()` (over 180,000; CHK-M10-367). REQ-250 (3): 3 more heartbeats make no runner call (CHK-M10-384). `current_job_id` comes from the run state (M4 row) |
| Nil handler (decisions row; REQ-249 (4)) | CODE | W | `TestNilComplianceHandlerRefusesButInventoryRuns` | PASS | 4 compliance jobs are refused ("no compliance handler", ≥ 4 lines), both inventory jobs run, `last_error` is set, there are 0 results posts, and the pull loop keeps running |
| r1 (c): a forced Put error, markers fit | CODE | W | `TestR1PutErrorFillsMarkers` | PASS | Result 1 is stored. The runner's 2nd result names a plugin not in the job, so `Put` fails. The final posts carry result 1 whole plus `spool_overflow` markers for 2 and 3 (exit null, empty streams). The foreign result is never posted (CHK-M10-392). There's a Warn line and no `last_error` |
| r1 (c): markers can't be stored | CODE | W | `TestR1MarkersCannotBeStored` | PASS | The bound is manifest + result 1 + 100 bytes. Result 1 is in an outstanding post, so it can't be converted, and the 2nd result fails. One ERROR line holds `job_id` and `"count":2`, with no output. The next heartbeat carries `spool: results not kept`. Plugins 2 and 3 are never posted (the manager shows them not run); result 1 is posted; the spool stays within its bound |
| CHK-M10-271 (was CHK-M4-223) | CODE | L, W | `TestNoOtherJobSourceStatic` | PASS | See above; 9 plants (below) |
| plant r1 `nofill` | CODE | W | the fill after a Put error removed | PASS (red) | "1 plugins posted, want 3"; the lost-line row is red too |
| plant r1 `unavailfill` | CODE | W | the fill uses `runner_unavailable` | PASS (red) | "plugin 2: … want a spool_overflow marker" |
| plant r1 `nolost` | CODE | W | no log or `last_error` for lost plugins | PASS (red) | "no lost-results line" |
| plant nil handler: panic | CODE | W | `panic` in place of the refusal | PASS (red) | The package panics |
| plant nil handler: early return | CODE | W | the pull loop returns without a handler | PASS (red) | "0 inventory jobs run, want 1" |
| CHK-M10-367 | CODE | W | `spoolBytes()` returns 0 | PASS (red) | The spool_bytes condition was never reached (120 s) |
| CHK-M10-369 | CODE | W | `go run(job)` in the worker | PASS (red) | "2 runner calls while the first job is held, want 1" |
| CHK-M10-384 | CODE | W | the heartbeat dials `runner.sock` | PASS (red) | CHK-M10-271: "loops/heartbeat.go reaches the runner socket or AF_UNIX"; "opens a socket ([net.Dial])" |
| CHK-M10-271 plants (9) | CODE | W | a `"unix"` dial in loops; `runner.sock` in state and in transport; `net.UnixAddr`/`"unixpacket"`; `x/sys/unix` in enrol; `net.Listen` in transport; `net.Dial` in loops; `os/exec` in loops; a `Handle` caller outside pull/jobs | PASS (red ×9) | Each failed for its reason; base green |

### Acceptance (TASK-223: "fake manager, fake runner, fake clock: REQ-245 (1)–(6), REQ-249 (2)–(4) and REQ-250 (1)–(3) hold, and the M4 pull and heartbeat suites pass except the PD-45 rows")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-245 (1)–(6) | CHK-M10-073, -074, -076, -077; walk | PASS |
| REQ-249 (2)–(4) | CHK-M10-078, nil handler | PASS |
| REQ-250 (1)–(3) | CHK-M10-079, -074 | PASS |
| r1 | the two r1 rows and 3 plants | PASS |
| M4 pull and heartbeat suites pass except the PD-45 rows | WSL 158/158 (CHK-M4-223 rewritten as CHK-M10-271 per the user) | PASS |

## TASK-224


Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-239 (6), REQ-240 (1)–(10), REQ-241 (3), (5); TS §3.5 L249–L250, §3.7 L284; #135 (c), #136 (f), #138. Decisions rows covered:
- "TASK-224 (job) and TASK-225 (serve) design points accepted" (2): the only error `Run` returns is a failed sweep or temp cleanup, and it is fatal;
- the same row (3): `TmpDirs` has no default;
- "TASK-224 r1: always kill the shell when a plugin is stopped";
- "Delegated real-kernel rows must run as the unit user".

Code under test: `agent/internal/runner/job.go` at r1. The `stop` closure now always runs `cg.Kill()` then `s.proc.Kill()`. Impl report: `work/reports/TASK-224-impl.md` (r0, r1).

Test file (new): `agent/internal/runner/job_delegated_linux_test.go`, build tag `linux && delegated`, 10 tests and 6 subtests. It uses the real `Open`, `Sweep` and `Spawn`, a counting `Spawn` wrapper (the exec counter), and the TS-extracted default patterns. It shares the `jobLog` sink with `serve_linux_test.go`.

### Where and how

WSL Ubuntu 24.04 (cgroup2fs, systemd 255). The whole delegated binary runs unprivileged, as the unit's user:

`systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p StateDirectory=m10c-job -p WorkingDirectory=<tree>/agent/internal/runner <race-built binary> -test.run Delegated -test.v`

The tree holds `docs/spec/Technical_Specification.md`, so the TS extraction resolves. The test logged its identity: `uid 999 euid 999 gid 988; CapEff/CapPrm/CapBnd/CapAmb 0x4; NoNewPrivs 1`.

The `/tmp` row refuses to run unless `/tmp` and `/var/tmp` are mount points of the test's own namespace (`/proc/self/mountinfo`). So it can never empty a host's `/tmp`. Plants ran in throwaway copies, never in the worktree.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| WD, whole delegated binary ×3 | as above | **31/31 passed** each run (cgroup 5, spawn 7, remove-temp 3, job 16), 0 failed, 0 skipped, unit exit 0 |
| static | `gofmt -l`; `go vet` (plain and `-tags delegated`); `golangci-lint run` on Linux, plain and `--build-tags delegated` | clean, 0 issues |
| plants | 13 plants (12 in job.go, 1 spawn plant against the job rows), each in its own copy, delegated as bitscan-runner | **13/13 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-147 | APP | WD | `TestDelegatedJobNoSurvivors` | PASS | REQ-240 (1)–(6), with `max_parallel_plugins` 1. Five plugins keep their processes in their own cgroup:<br>• `sleep … &`;<br>• `setsid nohup sleep … &`;<br>• a double fork;<br>• `trap '' TERM; sleep …` with `timeout_s` 2 (timed_out, 137);<br>• a child moved into `p-<n>/nest`.<br>For each, the subtree holds no process except the runner when its result is emitted. Three plugins move a child out: into `supervisor`, into `supervisor/evil`, and into the service root. After `Run`, for all eight:<br>• no process other than the runner is in the subtree;<br>• no process of uid 999 is running `sleep 300.147`;<br>• the only cgroup is `supervisor`, with nothing under it;<br>• the runner is in `supervisor`.<br>All 8 results arrived once; exit 0, except the timed-out one |
| CHK-M10-148 | APP | WD | `TestDelegatedJobTimeout` | PASS | REQ-240 (7). `sleep 100` with `timeout_s` 2: the result came between 2 and 3 s after the start, `timed_out` true, exit 137, nothing left |
| r1 row (reviewer-m10c, impl-agent-m10r) | APP | WD | `TestDelegatedJobMovedShellTimeout` | PASS | `echo $$ > <base>/supervisor/cgroup.procs; exec sleep 100000` with `timeout_s` 2: `timed_out` true, exit 137. `Run` returned after 2.01–2.02 s (bound 10 s); no `sleep 100000` survived, and the subtree holds only the runner |
| CHK-M10-149 | APP | WD | `TestDelegatedJobRunnerMoved` | PASS | REQ-240 (8), #138 (b). The plugin writes `$PPID` (the runner) into its own `cgroup.procs`. The runner survives, is back in `supervisor`, and the next job runs (`echo ok` gives exit 0, `ok\n`). Recorded: the moving plugin's own result was exit 0, `moved\n` |
| CHK-M10-150 | APP | WD | `TestDelegatedJobTmpEmptied/the_private_/tmp_and_/var/tmp_are_emptied` | PASS | REQ-240 (9), #135 (c). With `TmpDirs` = `/tmp`, `/var/tmp` (the private mounts), the plugin leaves:<br>• `/tmp/x/deep/f` and `/tmp/.h`;<br>• `/var/tmp/y`;<br>• a `/var/tmp/locked` of mode 000 holding a file;<br>• a symlink `/tmp/link` to `/var/lib/m10c-job/outside`.<br>After `Run`, both directories are empty, and the symlink target and its `keep` file are unchanged (no symlink followed) |
| TmpDirs no default (design point 3) | APP | WD | `…/no_default:_TmpDirs_nil_leaves_/tmp_alone` | PASS | With `TmpDirs` nil, a plugin's `/tmp/m10c-nodefault-marker` survives the job |
| Executor errors are fatal (design point 2) | APP | WD | `…/a_failed_cleanup_is_Run's_error_(fatal),_after_every_result` | PASS | With `TmpDirs` = `/nonexistent-m10c`, `Run` emits the 1 result, then returns an error and logs "after-job cleanup failed". The serve half (no `done`, `Serve` returns the error) is TASK-225's `TestServeFatalExecutorError` |
| CHK-M10-151 | APP | WD | `TestDelegatedJobCancel` | PASS | REQ-240 (10). Two `sleep 300.151` plugins run at `max_parallel_plugins` 2 and a third waits. `ctx` is cancelled once both run. `Run` returns, 0 results are emitted (none after the cancel, and the queued third is not reported), and 1 s later no plugin process exists |
| CHK-M10-152 | APP | WD | `TestDelegatedJobParallelCap` | PASS | REQ-239 (6). Eight `date; sleep 2; date` at 3 at once: the maximum overlap from the plugins' own timestamps is exactly 3, done in three rounds (6–8 s). At 1 at once, 3 plugins never overlap |
| CHK-M10-153 | APP | WD | `TestDelegatedJobStartFailures` | PASS | REQ-241 (5), #136 (f). An `ErrExec` at spawn 2: plugin 2 is `runner_unavailable` (exit null, empty streams, flags false), and plugins 1 and 3 ran (`one`, `three`); 3 spawn calls. An `ErrCgroup` at spawn 2: plugins 2–4 are `runner_unavailable`, and there are exactly 2 spawn calls (no further start) |
| CHK-M10-154 | APP | WD | `TestDelegatedJobExitCodesAndOrder` | PASS | REQ-241 (3) at unit level: `exit 3` → 3, `kill -9 $$` → 137, an unknown command → 127, `echo fast` → 0. Emitted in completion order 4, 2, 3, 1, not payload order |
| CHK-M10-155 | APP | WD | `TestDelegatedJobRedaction` | PASS | With the TS-extracted defaults, a `bsa_M10CANARY…` token plus 3 MiB of filler gives stdout `start [REDACTED] end\n…`: ≤ 65,536 bytes, `truncated` true, no `M10CANARY`. The token on stderr gives `[REDACTED]`. The runner log has a per-plugin line (ids, exit, duration) and no canary or filler |
| CHK-M10-156 | APP | WD | `TestDelegatedJobCleanupBeforeEmit` | PASS | At each emit (with `max_parallel_plugins` 1), the plugin's `/tmp/bitscan-p-*` is gone (Lstat ENOENT) and there is no `p-*` cgroup |
| r1 plant: pre-r1 `stop` (shell killed only if `cg.Kill` fails) | CODE | WD | plant `r0stop` | PASS (red) | "Run did not return within 10s: plugins in the subtree [1052]"; "Run blocked on the moved shell" |
| CHK-M10-337 (G72 half) | CODE | WD | plant: `release` without `cg.Kill` | PASS (red) | "plugin 1: processes [1524] still alive when its result is emitted" (and plugins 2–5). VM half NOT RUN (VM hold, the named gate exception) |
| CHK-M10-338 (job half) | CODE | WD | plant: after-job `Sweep` removed | PASS (red) | 3 `sleep 300.147` alive after the job; `p-5` and `supervisor/evil` left |
| CHK-M10-336 (executor half) | CODE | WD | spawn plant 336 (start outside `StartIn`) against the job rows | PASS (red) | Background children alive at every emit; the timeout result came at 3.0035 s (its sleep, in `supervisor`, held the pipes until captureGrace) |
| CHK-M10-341 (executor half) | CODE | WD | plant: `RemoveTempDir` dropped from `plugin()` | PASS (red) | "temp dir /tmp/bitscan-p-… still there when its result is emitted" ×3 |
| CHK-M10-342 | CODE | WD | plant: `TmpDirs` not walked | PASS (red) | `/tmp` held `[.h link x]`, `/var/tmp` held `[locked y]`, and the bad-dir cleanup returned nil |
| CHK-M10-343 | CODE | WD | plant: timer in hours | PASS (red) | The timeout row hung to 15 s (killed by the test); no-survivors hung to 60 s. VM half NOT RUN |
| CHK-M10-391 (executor half) | CODE | WD | plant: the plugin's `ctx.Done()` case removed | PASS (red) | "Run did not return within 20s: plugins in the subtree [4303 4304 4307 4308]". VM half NOT RUN |
| CHK-M10-382 (executor half) | CODE | WD | plant: `out.Data` logged | PASS (red) | "plugin output or command in the runner log" |
| extra 224a | CODE | WD | plant: semaphore of `len(plugins)` | PASS (red) | "at most 8 plugins ran at once, want exactly 3"; 2.01 s instead of three rounds |
| extra 224b | CODE | WD | plant: a cgroup failure doesn't set `stopped` | PASS (red) | "4 spawn calls after a cgroup failure at the 2nd, want 2" |
| extra 224c | CODE | WD | plant: results emitted after the cancel | PASS (red) | "3 results emitted after the cancel" |
| extra 224d | CODE | WD | plant: `p-<n>` not removed in `release` | PASS (red) | "cgroup p-39 still there when the result is emitted" ×3 |

### Acceptance (TASK-224: "under `systemd-run -p Delegate=yes`, REQ-240 (1)–(7), (9), (10) and REQ-239 (6) hold through `Executor.Run`, and REQ-241 (5) holds with injected failures")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-240 (1)–(6) | CHK-M10-147 | PASS |
| REQ-240 (7) | CHK-M10-148; r1 moved-shell row | PASS |
| REQ-240 (8) (beyond the acceptance) | CHK-M10-149 | PASS |
| REQ-240 (9) | CHK-M10-150 | PASS |
| REQ-240 (10) | CHK-M10-151 | PASS |
| REQ-239 (6) | CHK-M10-152 | PASS |
| REQ-241 (5) | CHK-M10-153 | PASS |
| r1: the timeout holds for a shell that left its cgroup | r1 row and its plant | PASS |
| REQ-240 on a sandbox host | — | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the WD rows above, on the real kernel as bitscan-runner |

### Note for TASK-229 (impl-deploy-m10; sent to `main`)

The delegated binary now also holds the job rows. They need four things the `agent.yml` delegated step doesn't give them today:
- `-p PrivateTmp=yes`. The `/tmp` row refuses to run without private mounts, and a private `/tmp` hides any binary placed under `/tmp`.
- `-p StateDirectory=m10c-job`.
- the test binary outside `/tmp` and outside `$HOME`, which bitscan-runner can't read on hosted runners. For example, `/opt/delegated`.
- a `WorkingDirectory` whose `../../../docs/spec/Technical_Specification.md` exists (the TS-extracted patterns).

Without them, the CI step goes red on `TestDelegatedJobTmpEmptied` and `TestDelegatedJobRedaction`.

### Revision 2 (2026-11-01): capture errors set `truncated`; cleanup logs carry no path

Code: `job.go` r2 keeps both `Capture` errors and sets `out.Overflow` when either stream errors (decisions row "TASK-224 r2: a stderr-only read error also sets truncated"). `cmd/bitscan-runner/main.go` r2 adds `pathless()`, which logs sweep and cleanup errors as the operation and errno only. Impl report: "Revision 2 (2026-11-01)".

New tests:
- `TestDelegatedJobCaptureErrorTruncated` (job file, 1 test and 5 subtests);
- `agent/cmd/bitscan-runner/main_test.go` (new, `//go:build linux`, package `main`, `TestPathlessDropsPaths`, 1 test and 7 subtests).

| Run | Command | Count |
| --- | --- | --- |
| WD, whole delegated binary ×2 | as above | **37/37 passed** each run (the 31 above plus 6), unit exit 0 |
| W | `go test -race ./cmd/bitscan-runner/` | **8/8 passed** |
| static | gofmt, vet, `golangci-lint run ./...` on Linux, plain and `--build-tags delegated` | 0 issues |
| plants | 3 | **3/3 red** |

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| r2 (1), stdout | APP | WD | `TestDelegatedJobCaptureErrorTruncated/stdout_held_open_by_a_child_that_left_the_cgroup` | PASS | A child moves itself to `supervisor` and keeps stdout open. The plugin waits until the move shows in `/proc/$!/cgroup`, then prints `ok` and exits. After captureGrace (the row took 1.22 s), the read end is closed and `Capture` errors. Result: exit 0, stdout `ok
`, `truncated` true. Nothing left after the job |
| r2 (1), stderr only | APP | WD | `…/stderr_only_held_open` | PASS | The same with only stderr held: `truncated` true |
| r2 control | APP | WD | `…/control:_no_read_error,_truncated_false` | PASS | `echo ok; echo e >&2` gives `truncated` false |
| r2 (1), unit | APP | WD | `…/unit:_a_{stdout,stderr}_read_that_fails_(EISDIR)` | PASS | A `Spawn` wrapper swaps the stream for an opened directory, so every read is EISDIR. `truncated` is true for each stream |
| r2 (1), manager verdict | CODE | — | existing `manager/tests/test_evaluate.py` L155–L165, L194, L213 (M8, unchanged) | PASS (by reference) | `evaluate.py` `_run_error`: `truncated` → ERROR `STDOUT_TRUNCATED` for every operator, including a PASS input. So a cut stream can never be PASS |
| r2 (2), unit | CODE | W | `TestPathlessDropsPaths` (7 cases) | PASS | `*fs.PathError{unlinkat, /tmp/M10PATHCANARY-x/f, EACCES}` gives `unlinkat: permission denied`, wrapped or joined behind canary text. `*os.LinkError{rename, EXDEV}` gives `invalid cross-device link`. A PathError without an errno gives `readdir`, a bare errno `device or resource busy`, no errno `no errno`. No output holds the canary or `/tmp`. The end-to-end half (the built runner under systemd-run, its stderr grepped) is a TASK-228 row |
| plant r2a | CODE | WD | `Capture` errors dropped again (the pre-r2 code) | PASS (red) | All four error rows red: "truncated false … want true" |
| plant r2b | CODE | WD | only a stdout error sets `truncated` | PASS (red) | Exactly the two stderr rows red |
| plant r2c | CODE | W | `pathless` returns `err.Error()` | PASS (red) | "pathless kept a path: \"unlinkat /tmp/M10PATHCANARY-x/f: permission denied\"" |

## TASK-225


Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-234, REQ-235 (4), REQ-236 (2), REQ-261; TS §3.7 L281–L285; #130 (b)–(g); Q1 (decisions "tester-m10's M10 plan questions"); decisions "TASK-224 (job) and TASK-225 (serve) design points" (1), (2).

Code under test: `agent/internal/runner/serve.go` (unchanged since its IMPL; `work/reports/TASK-225-impl.md`).

Test file (new): `agent/internal/runner/serve_linux_test.go`, package `runner`, 10 tests and 16 subtests. It runs a real Unix socket (`net.ListenUnix` behind the `Listener` interface), the real `Checks` with a temporary `agent_id` file, and a fake executor (`fakeExec`, the exec counter, CHK-M10-H02). Canaries go in every `execute`, in a pattern and in every result's stdout. Each harness's cleanup fails the test if a canary reaches the runner log (CHK-M10-171).

### Where

The file is Linux-only. On Windows AF_UNIX, a refusal sent without reading the request can arrive as a reset (impl-agent-m10b's TASK-218 note), so the `busy` row only means something in WSL. Its Linux behaviour is recorded: the queued `refused busy` frame is read, then `ECONNRESET`, which the test treats as end of stream, and the busy client's write may get `EPIPE`. `serve.go` itself has no build tag; `GOOS=windows go vet ./internal/runner/` is clean.

The two deadline rows wait out the #130 (f) values in wall time (30 s and 60 s). These are spec times, the only ones this file waits for. Every other row is driven by channels.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race -count=1 -run TestServe ./internal/runner/` | **26/26 passed**, 0 failed, 0 skipped |
| W, flake check | the eight fast tests, `-count=5 -race` | ok, 0 failed |
| static | gofmt; `go vet` (linux and windows); `golangci-lint run` (Linux) | clean, 0 issues |
| plants | 9 plants in throwaway copies | **9/9 red** |

### Test fix during this round (mine)

At first, `TestServeCloseCancels/close` stayed green with the connection watcher's `cancel()` removed. The fake executor's write after the close failed, and that cancelled the job instead. The row now reads `accepted` and the result before closing, so only the watcher can cancel. After the fix, base passed 3/3 and the 391serve plant was red in both modes.

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-163 | CODE | W | `TestServeGoodJob` | PASS | Replies `accepted,result,result,result,done`, then EOF. The results came in emit order with the plugin uuids. The executor ran once with a request JSON-equal to what was sent. Log: `job_id` and "runner: job done" |
| CHK-M10-164 | CODE | W | `TestServeBusy` | PASS | REQ-235 (4). While job 1641 is held, a second connection gets `refused busy` within 1 s, and its request is never run (executor calls 1). Job 1641 then finishes `accepted,result,done`, and a third job runs (the slot is freed) |
| CHK-M10-165 | CODE | W | `TestServeMalformed` (12 subtests) | PASS | REQ-261, Q1. Each case gets exactly one `refused malformed`, then EOF:<br>• a bare JSON string;<br>• plugins without a job;<br>• `"command"` beside `job` (CHK-M10-323);<br>• an unknown key inside `job`;<br>• `v` 2;<br>• `max_parallel_plugins` 9;<br>• 0 plugins;<br>• a zero-length frame;<br>• an oversize header (33,554,433);<br>• garbage bytes;<br>• two JSON values.<br>An inventory job gets `refused not_compliance` (CHK-M10-324). Exec counter 0. 12 "request refused" log lines, none with request text |
| CHK-M10-166 | CODE | W | `TestServeSecondFrame` | PASS | CHK-M10-322. A second request frame on a running job's connection is never decoded or run: executor calls 1, one `accepted`, and job 1662 never reached the executor. **Recorded:** the second frame's first byte cancels the running job (the watcher's "any read return", which fails closed). After a `refused foreign_agent`, a second frame gets nothing and nothing runs |
| CHK-M10-167 | CODE | W | `TestServeJobChecks` | PASS | REQ-236 (2) through the socket: foreign → `foreign_agent`, `pickup_by` = now → `pickup_passed`, now + 25 h + 1 s → `pickup_too_far`, a resent id → `replayed` (CHK-M10-327 unit half). Exec counter 0. Exactly one log line each: `{"msg":"runner: job refused","job_id":…,"reason":…}` |
| CHK-M10-168 | CODE | W | `TestServeRequestDeadline/{silent,half_header}` | PASS | `requestWait` = 30 s (#130 (f)). A silent connection, or one that sent 2 header bytes, is closed after 30.02 s, with one `refused malformed` frame (recorded). While it waits it holds the one slot, so another connection gets `refused busy` (recorded, #130 (g)). The next connection then runs normally |
| CHK-M10-169 | CODE | W | `TestServeCloseCancels/{close,half-close}` | PASS | TASK-225 acceptance. After `accepted` and the result have been read, closing the client cancels the executor's context within 1 s. A half-close (EOF) cancels too, and no `done` follows |
| CHK-M10-170 | CODE | W | `TestServeWriteDeadline` | PASS | `replyWait` = 60 s. The client stops reading while the executor emits 100 maximal results (65,536 + 16,384 bytes each). The job ended 60.05 s later, with fewer than 101 replies queued and no `done`. The next connection is served (executor calls 2) |
| CHK-M10-171 | CODE | W | every TestServe harness cleanup | PASS | No `M10SRVCANARY` (execute, pattern, stdout) in any runner log record |
| Fatal executor error (design point 2) | CODE | W | `TestServeFatalExecutorError` | PASS | Run returns an error: replies `accepted,result`, no `done`. `Serve` returns that same error (`errors.Is`), the listener refuses new connections, and the log has "job ended, cleanup failed" |
| Shutdown mid-job | CODE | W | `TestServeShutdownMidJob` | PASS | Cancelling `Serve`'s context mid-job cancels the job, `Serve` returns nil after it ends, and there is no `done` |
| CHK-M10-322 | CODE | W | plant: the watcher decodes and runs a second frame | PASS (red) | "executor ran 2 times … want 1 run" |
| CHK-M10-391 (serve half) | CODE | W | plant: the watcher's `cancel()` removed | PASS (red) | "closing the client did not cancel the executor" in both modes. VM half NOT RUN (VM hold, the named gate exception) |
| CHK-M10-382 (serve half) | CODE | W | plant: `execute` logged at accept | PASS (red) | "a canary is in the runner log (CHK-M10-171)" |
| extra 225a | CODE | W | plant: the busy flag never refuses | PASS (red) | The second connection got `accepted,result` (two jobs at once) |
| extra 225b | CODE | W | plant: a refused job still reaches `Exec.Run` | PASS (red) | "executor ran 4 times for refused jobs" |
| extra 225c | CODE | W | plant: `done` written after a cancelled job | PASS (red) | "done after a cancelled job: accepted,result,done" |
| extra 225d | CODE | W | plant: a fatal `Run` error ignored | PASS (red) | "Serve kept running after a fatal executor error" |
| extra 225e | CODE | W | plant: no 30 s request deadline | PASS (red) | Still open at the test's 45 s bound; the next connection got `refused busy` |
| extra 225f | CODE | W | plant: no 60 s write deadline | PASS (red) | "the job is still running 90 s after the client stopped reading" |

### Acceptance (TASK-225: "with a fake executor and a Unix socket, REQ-235 (4), REQ-236 (2) and the REQ-261 malformed-request cases hold, and closing the client cancels the executor's context within 1 s")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-235 (4) busy | CHK-M10-164 | PASS (WSL) |
| REQ-236 (2) refusals through the loop | CHK-M10-167 | PASS |
| REQ-261 malformed and non-job requests | CHK-M10-165, -166 | PASS |
| close → cancel within 1 s | CHK-M10-169 | PASS |
| #130 (f) deadlines | CHK-M10-168, -170 | PASS |
| REQ-261 host part (G78 through the driver) | CHK-M10-280 to -289 | NOT RUN: VM hold (the named gate exception, decisions 2026-11-01 (1)). Cover: the rows above, plus TASK-213's checks |

## TASK-226


Tester: tester-m10c, 2026-11-01. Full rigor (capread, TS §8.2 second approval). REQ-253 (1), (2), REQ-252 (the helper wiring); TS §3.7 L437–L484; #142 (f), (g). Decisions rows:
- "TASK-226 (capread client and main) accepted as built": main is linux-only; the answer is buffered and printed after a clean end; an error word must match `[a-z0-9_ ]{1,40}`; only the name is forwarded;
- "TASK-222 … additions";
- the TASK-222 approval row, which asks for a helper-unit row in WSL.

Code under test: `agent/internal/capread/client.go` and `agent/cmd/bitscan-capread/main.go` (`work/reports/TASK-226-impl.md`). The server half is TASK-222 (PASS).

Test files (new):
- `agent/internal/capread/client_test.go`: portable, 6 tests (+2 subtests);
- `agent/internal/capread/client_linux_test.go`: the cut-off and refused-socket rows;
- `agent/cmd/bitscan-capread/main_test.go`: linux, builds the binary with `CGO_ENABLED=0` and runs it.

The fake helper listens on a Unix socket in a short temporary directory and records every byte each client sends.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W (WSL, -race) | `go test -race ./internal/capread/... ./cmd/bitscan-capread/` | **20/20 passed** (TASK-222's 11 included), 0 failed, 0 skipped |
| L (Windows, no -race: there is no C compiler here, and -race needs cgo) | `go test ./internal/capread/ ./cmd/...` | **8/8 passed** (the portable client rows; the linux files don't build here) |
| build | `GOOS=linux go list ./cmd/...` lists `cmd/bitscan-capread`; `GOOS=windows go list ./cmd/...` lists only `cmd/bitscan-agent` (recorded, as built). `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/bitscan-capread` gives an ELF x86-64, statically linked | as expected |
| static | gofmt; vet (linux and windows); `golangci-lint run ./...` on Linux | clean, 0 issues |
| plants | 6 in `client.go` | **6/6 red** |
| WSL helper unit row | `capread_unit.sh` (outside the repo) | see CHK-M10-217w; one half NOT RUN |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-176a | CODE | L, W | `TestClientSendsOnlyTheName` | PASS | Only the request name is sent. The helper received exactly `audit_rules\n`, and after the request line nothing more, for both names |
| CHK-M10-176b | CODE | L, W | `TestClientCopiesOutput` | PASS | A 1 MiB binary answer (every byte value) is printed byte for byte, exit 0, stderr empty. 1 MiB + 1 gives `bitscan-capread: too_large`, exit 1, stdout empty. An empty `ok` answer gives exit 0 |
| CHK-M10-176c | CODE | L, W | `TestClientErrorWords` (23 answers) | PASS | `error timeout` gives exactly the line `bitscan-capread: timeout` on stderr, exit 1. The same holds for `not_installed`, `unknown_request`, `too_large`, `failed 126` and 40×`a`. These are printed as `bad answer` (words outside `[a-z0-9_ ]{1,40}`, and bad first lines):<br>• 41×`a`, an empty word, `Timeout`, `a-b`, `a;b`, a tab, `ESC[2J`, `CR`, `é`;<br>• a bare `error`, `oops`, `OK`, `ok `, an 80-byte first line.<br>No answer, `ok` with no newline, or `error timeout` with no newline gives `no answer`. stdout is empty in every case |
| CHK-M10-176d | CODE | L, W | `TestClientNoAnswerTimeout/{silent,stalls_mid-stream}` | PASS | `clientTimeout` = 30 s (#142 (f)). A silent helper, or one that sends `ok` plus about 64 KiB and then stalls, gives `bitscan-capread: timeout`, exit 1, after 29–35 s, with **nothing printed** |
| CHK-M10-176e (lead's row) | CODE | W | `TestClientCutOffAnswer` (20 rounds) | PASS | An answer cut off mid-stream prints nothing and exits non-zero. The helper sends `ok` plus about 88 KB, then closes with the request unread, so the client's read ends in ECONNRESET after partial data. Every round: exit 1, 0 bytes printed, `bitscan-capread: no answer`. **Recorded:** a helper that closes *cleanly* after partial output can't be told apart from a complete answer: #142 has no length field |
| CHK-M10-176f | CODE | L, W | `TestClientNotEnabled`; `TestClientRefusedSocket` (W) | PASS | REQ-253 (3) at unit level: a missing socket, or a bound socket nobody listens on (ECONNREFUSED), gives `bitscan-capread: not enabled`, exit 1. `Socket` is `/run/bitscan/capread.sock` |
| CHK-M10-177a (lead's row) | CODE | L, W | `TestClientArgsRefusedLocally` (15 argument lists) | PASS | An unknown name is refused locally, before any connection. Each of these exits 2 with the usage line, stdout empty, and the listening fake saw **0 connections**: none, `""`, `nft_ruleset extra`, `audit_rules nft_ruleset`, `/bin/sh`, `NFT_RULESET`, `nft_ruleset\n`, `nft_ruleset `, `--serve`, `--serve x`, `../nft_ruleset`, `/usr/sbin/nft`, `unknown_request`, `nft_ruleset;id` |
| CHK-M10-177b | APP | W | `TestCapreadBinary` (the built static binary) | PASS | These exit 2 with the usage line: no argument, `""`, `nft_ruleset extra`, `/bin/sh`, `audit_rules nft_ruleset`, `--serve x`, `NFT_RULESET`. `--serve` with no `LISTEN_*`, with `LISTEN_PID=1`, or with only `LISTEN_FDS` exits 1 with exactly one stderr line. With no helper, `nft_ruleset` gives `bitscan-capread: not enabled`, exit 1 |
| CHK-M10-217w (TASK-222 approval row; REQ-252 (5), (6) in WSL) | APP | W | `capread_unit.sh` | PASS (nft) / **NOT RUN** (audit, below) | Setup: a transient `systemd-run --unit=m10c-capread` with all 23 `[Service]` directives of `deploy/systemd/bitscan-capread.service` (read from the file, verbatim) and all 5 `[Socket]` directives of `bitscan-capread.socket` as `--socket-property`. **systemd-run accepted every one; none rejected.** ExecStart is `/opt/m10c/bin/bitscan-capread --serve`, the built static binary (the only change). The real units are not installed (0 unit files) and were never enabled.<br>Socket: `root:bitscan-runner 0660` in `/run/bitscan` (`root:root 0755`).<br>A bitscan-runner client (uid 999) running `nft_ruleset` gets exit 0 and 13,432 bytes, **byte-equal to root's `nft -j list ruleset`** (valid JSON, 65 `nftables` entries).<br>Helper process: Uid/Gid 64884 (DynamicUser), **CapInh/CapPrm/CapEff/CapBnd/CapAmb all `0000000040001000`**, NoNewPrivs 1, Seccomp 2.<br>Another uid is refused: `m10c-peer` (uid 997, in group bitscan-runner) and root (uid 0) connect and are closed without a reply (`bitscan-capread: no answer`, exit 1). The journal shows `sdsock: peer refused uid=997` and `uid=0`. `nobody` (not in the group) gets EACCES from the 0660 socket (`not enabled`).<br>The journal has `request answered command=/usr/sbin/nft result=ok` and 0 lines with ruleset text. After the stop, the socket file is removed |
| CHK-M10-217w audit half | APP | W | same | **NOT RUN** (not possible in WSL) | `auditctl -l` fails for **root itself** in this WSL distro: exit 255, "Error sending rule list data request (Operation not permitted)". The WSL kernel refuses audit netlink requests from the distro, which runs outside the initial PID namespace. So real `auditctl -l` output can't be shown here. Recorded: through the helper, a bitscan-runner client gets `bitscan-capread: failed 255`, the same exit status root gets, and nothing on stdout. Setup note: `auditctl` was installed from the Ubuntu archive's `auditd` package (binary only, no daemon) plus `libauparse0`. Cover: TASK-222's rows with a swapped table (fixed argv, empty env, `failed <code>`) and the VM row (held) |
| plant "print as it streams" (lead's row) | CODE | W | `io.Copy(stdout, …)` in place of the buffered read | PASS (red) | `TestClientCutOffAnswer`: "88000 bytes printed"; `TestClientCopiesOutput`: 1 MiB + 1 printed |
| plant: error word unchecked | CODE | W | `wordRe` skipped | PASS (red) | `TestClientErrorWords`: 41×`a` printed as a word |
| plant: unknown names connect | CODE | W | the `Known` check removed | PASS (red) | `TestClientArgsRefusedLocally`: `""`, `/bin/sh`, `NFT_RULESET` and others connected and printed `X` |
| plant: more than the name sent | CODE | W | the socket path appended to the request | PASS (red) | "request bytes \"audit_rules /tmp/cr…/c.sock\\n\"" |
| plant: timeout 60 s | CODE | W | `clientTimeout = 60 * time.Second` | PASS (red) | `TestClientNoAnswerTimeout` refuses the constant (30 s, #142 (f)) |
| plant: 1 MiB cap removed | CODE | W | `too_large` branch dropped | PASS (red) | 1 MiB + 1 printed, exit 0 |

### Acceptance (TASK-226: "unit with a fake server and the built binary run by hand: REQ-253 (1), (2) hold")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| REQ-253 (1): name only, output copied, exit codes, the error line | CHK-M10-176a–f | PASS |
| REQ-253 (2): other argument lists exit 2 without connecting | CHK-M10-177a, b | PASS |
| `--serve` wiring through sdsock and TASK-222 | CHK-M10-177b, CHK-M10-217w | PASS |
| REQ-252 (5), (6) with real `nft`, CapEff 0x40001000, other uids refused | CHK-M10-217w | PASS for nft in WSL; audit NOT RUN in WSL (kernel refuses audit netlink to the distro); VM row NOT RUN (VM hold, the named gate exception) |

## TASK-227


Tester: tester-m10c, 2026-11-01. Full rigor (agent, TS §8.2 second approval). REQ-245, REQ-246, REQ-247, REQ-249, REQ-251 (1); TS §1.1 G2, §2.2 L111, §3.3 L222, L226, §3.5. Decisions rows: "TASK-227 (agent main) spool-open failure accepted (safer option)" and the reviewer's confirmation row.

Code under test: `agent/cmd/bitscan-agent/main.go` (`work/reports/TASK-227-impl.md`).

### Test files (new, tester-owned)

- `e2e/agent_binary_m10.sh`: the binary walk. It follows the M4 `e2e/agent_binary.sh` pattern: root in WSL, each scenario in a private mount namespace with overlayfs on `/etc` and `/var/lib` and tmpfs on `/tmp` and `/run`, so nothing on the host changes. The agent's paths are fixed (`/etc/bitscan/agent.yaml`, `/var/lib/bitscan-agent`, `/run/bitscan/runner.sock`), so this walk was used instead of a `cmd/bitscan-agent/main_test.go`.
- `e2e/agent_binary_m10_analyse.py`: the per-scenario checks.
- `e2e/fake_manager_m10.py`: TS §6.5 over TLS on 127.0.0.1. It hands out compliance and inventory jobs, accepts batches, and can answer 503 to non-empty batches while a file exists. The M4 `e2e/fake_manager.py` is unchanged.
- `e2e/fake_runner_m10.py`: the #130 protocol on `/run/bitscan/runner.sock`, with modes `normal`, `hold:N`, `slow:N:S` and `refuse:W`.
- `agent/internal/boundary_test.go`: REQ-251 (1), G75, `go list -deps` for linux/amd64.

The built binary is `CGO_ENABLED=0 GOOS=linux`, `-X main.version=0.2.0~pre1-1`.

Canaries:
- `touch /tmp/EXECCANARY-n; cat /etc/shadow` in every `execute`;
- `PATTERNCANARY[0-9]+` as the pattern;
- `M10RUNNERCANARY` in the runner's stdout;
- `bsa_CANARY…` and `bse_CANARY…` as the tokens.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W, walk (7 scenarios) | `e2e/agent_binary_m10.sh <worktree> /root/m10c/abw3` | **120/120 passed**, 0 failed, 0 errors, 0 skipped |
| L and W | `go test ./internal/` (`TestImportBoundary`) | 1/1 passed on Windows; 1/1 passed in WSL |
| plants | 7 (exit on spool error; 4 × CHK-M10-380; 2 × CHK-M10-381) | **7/7 red** |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-182 | APP | W | walk `e2e` | PASS | A 3-plugin compliance job end to end:<br>• the first post is `{"results": [], "final": false}`;<br>• the final is last and the only one;<br>• each plugin is posted once, as the runner's result;<br>• every body is gzip;<br>• the fake runner got exactly one request, `v` 1, whose `job` equals the pulled job (all fields but `pickup_by`, which the manager fills), and `max_parallel_plugins` 2, the heartbeat's value.<br>Nothing executed (no `EXECCANARY` file), no command or pattern in any state file, no canary in the agent's stdout or stderr. `/etc` changed only by the test; `/var/lib` only under `bitscan-agent`. No listening socket. SIGTERM: exit 0 within 5 s |
| CHK-M10-183 | APP | W | walk `sigterm` | PASS | The runner holds after 1 result, and SIGTERM goes in mid-job. Phase 1 exits 0 in 0.02 s. The fake runner saw the agent close. The spool kept `job.json` with `finished: false` and the 1 item. After a restart, the item is posted, **no final batch ever follows**, there is no `runner_unavailable` fill, and the job is **not resent** to the restarted runner (CHK-M10-358 at binary level; #131 (d)) |
| CHK-M10-184 | APP | W | walk `overflow` (`spool_max_mb: 1`) and `dropped` | PASS | The bound is 1,048,576 bytes; 165 samples of the spool's file bytes, max 991,038 (detail in TASK-212 r1 / 220 r1 / 223 r1). `dropped`: an unreadable `spool/<id>/job.json` at start gives first-heartbeat `last_error` = `spool: results dropped at start (unreadable)`, one log line naming the job, and the entry removed; compliance still runs |
| CHK-M10-185 | APP | W | walks `invheld`, `absent` | PASS | REQ-249 (3), (5), CHK-M10-370 at binary level. With the runner holding the compliance job, the inventory job of the same pull is uploaded (`PUT …/inventory?job_id=…`) **while the runner still holds**. With no runner at all:<br>• every plugin is posted `runner_unavailable` in a final batch (exit null, empty streams);<br>• inventory still uploads;<br>• the log says the runner is unavailable |
| Spool can't be opened (lead's row; decisions "TASK-227 … accepted") | APP | W | walk `nospool` (a regular file at `/var/lib/bitscan-agent/spool`) | PASS | The agent starts and enrols. The first heartbeat carries `last_error` = `spool: not opened; compliance jobs refused`. The inventory job is uploaded (G2). The compliance job is refused ("no compliance handler", job id logged), the runner is **never contacted**, and there is **no results post**. The `spool` file is unchanged and nothing is written under `/var/lib` outside `bitscan-agent`. "Writes no result anywhere": no results post, and no result in any state file |
| plant "exit on spool error" (lead's row) | CODE | W | `main` returns `refuse()` when `spool.Open` fails | PASS (red) | `nospool` 12/18: inventory not uploaded, no heartbeat, no refusal line, the wait timed out, exit 1 (not 0 on SIGTERM). Inventory is lost, the G2 breach the choice avoids |
| CHK-M10-196 | CODE | L, W | `TestImportBoundary` | PASS | linux/amd64 `go list -deps`. `cmd/bitscan-agent` links `internal/runner/proto`, `runnerclient` and `spool`, and no other `internal/runner*`, no `internal/redact`, `capread` or `sdsock`, and no `golang.org/x/sys` (PD-41). `cmd/bitscan-runner` and `cmd/bitscan-capread` link no `net/http*`, `crypto/tls`, `internal/agent/transport`, `enrol` or `loops`. The test fails if its own walk lists too few packages |
| CHK-M10-380 | CODE | W | plants: `cmd/bitscan-agent` imports `internal/redact`, `internal/runner`, `internal/capread`, `golang.org/x/sys/unix` | PASS (red ×4) | Each named, e.g. "bitscan-agent links bitscan.local/agent/internal/redact (REQ-251 (1), CHK-M10-380)"; the runner plant also shows `x/sys` (PD-41) |
| CHK-M10-381 | CODE | W | plants: `net/http` into `cmd/bitscan-runner`, `crypto/tls` into `cmd/bitscan-capread` | PASS (red ×2) | "./cmd/bitscan-runner links net/http (CHK-M10-381)" and the others |

### Acceptance (TASK-227: "against a fake manager and a fake runner the binary runs a compliance job end to end, SIGTERM mid-job exits 0 within 5 s with the spool intact, and REQ-251 (1) holds for `cmd/bitscan-agent`")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| end to end | CHK-M10-182 | PASS |
| SIGTERM mid-job, exit 0 < 5 s, spool intact, no final after restart | CHK-M10-183 | PASS |
| REQ-251 (1) | CHK-M10-196, -380 | PASS |
| G2 kept when the spool can't open | nospool row and its plant | PASS |
| The same against the real manager (G79) | — | NOT RUN: VM hold (the named gate exception). Cover: the walk above, plus G41 (inventory chain against the real manager) at the gate |

## TASK-228


Tester: tester-m10c, 2026-11-01. Full rigor (runner, TS §8.2 second approval). REQ-237 (2), REQ-238, REQ-240, REQ-251 (1), (3); TS §3 L152, §3.5, §3.7 L276–L285, L289–L359. Decisions rows covered:
- TASK-215 approval: "unproven: ProtectSystem=strict on the cgroup tree, TasksMax and MemoryMax with 8 plugins, SystemCallFilter including pidfd, RestrictNamespaces";
- TASK-216 approval: "(c) moved to WSL: CapEff/CapBnd = 4, also CapPrm and CapAmb";
- TASK-213 approval: "unproven: the runner reads `agent_id` through the 0700 state dir";
- TASK-217 approval: "socket root:bitscan 0660 in a root 0755 dir; a non-member gets EACCES";
- TASK-221 r2 at binary level;
- TASK-224 r2 end to end.

Code under test: `agent/cmd/bitscan-runner/main.go`. Its r2 changes are the m0 `init` lock (TASK-221 r2) and `pathless` (TASK-224 r2). Impl report: `work/reports/TASK-228-impl.md`.

### How (WSL Ubuntu 24.04, cgroup2fs, systemd 255; root runs the harness only)

Test files (new, tester-owned):
- `e2e/runner_unit_m10.sh`;
- `e2e/runner_client_m10.py`, the agent's half of #130, run as user `bitscan`.

The harness runs the built static runner under a **transient** `systemd-run --unit=m10c-runner` carrying:
- **all 37 `[Service]` directives of `deploy/systemd/bitscan-runner.service`**, read from the file verbatim: User/Group, both capability lines, NoNewPrivileges, Delegate, ProtectSystem=strict, PrivateTmp, NoExecPaths/ExecPaths, ProtectHome=read-only, UMask, PrivateDevices, PrivateIPC, RemoveIPC, the Protect*, Restrict*, LockPersonality, both SystemCallFilter lines, SystemCallErrorNumber, RestrictAddressFamilies, IPAddressDeny, both InaccessiblePaths lines, MemoryMax=256M, TasksMax=64, CPUQuota=25%, Restart=always, RestartSec=10;
- the 5 `[Socket]` directives of `bitscan-runner.socket` as `--socket-property`.

**systemd-run accepted every directive; none was rejected, so there is no NOT RUN property.** Differences from the shipped unit:
- ExecStart is `/usr/local/lib/m10c/bitscan-runner` (under `/usr`, so `ExecPaths=` allows it);
- `[Unit]`/`[Install]` don't apply to a transient unit.

The shipped units were never installed or enabled.

WSL set-up:
- user `bitscan` created (missing before);
- `/var/lib/bitscan-agent` created `bitscan:bitscan 0700`, with `agent_id` (0644). It was removed afterwards, as were the marker files and the binary dir.

### Runs

| Run | Command | Count |
| --- | --- | --- |
| W, unit row | `e2e/runner_unit_m10.sh <worktree> /opt/m10c/ru-base base` | **34/34 passed**, 0 failed, 0 errors, 0 skipped |
| W | `go test -race ./cmd/bitscan-runner/` (TASK-224 r2 `pathless`) | 8/8 passed |
| plants | 3 binary-level variants of the same walk, plus 1 below | 2/3 red; 1 NOT REPRODUCED at binary level (recorded below) |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-188a (REQ-237 (2); TASK-216 (c)) | APP | W | unit row | PASS | The runner's `/proc/<pid>/status`: Uid/Gid 999/988; **CapInh, CapPrm, CapEff, CapBnd and CapAmb each `0000000000000004`**; NoNewPrivs 1; Seccomp 2 |
| CHK-M10-188b (start-up checks) | APP | W | unit row | PASS | `Harden`, `CheckStartup`, `FromSystemd`, `Open` and `Sweep` all pass under the verbatim unit. The journal has "bitscan-runner started", and the socket is `root:bitscan 660` in `/run/bitscan` `root:root 755` |
| CHK-M10-188c (8 parallel plugins) | APP | W | job 1 (8 plugins, `max_parallel_plugins` 8) | PASS | `accepted`, 8 `result`, `done`, EOF. The plugins' own timestamps show 8 running at once, under TasksMax=64 and MemoryMax=256M. Each plugin: exit 0, its own `…/p-<n>` (8 distinct, never `supervisor`), niceness 10, uid 999. With CAP_DAC_READ_SEARCH a plugin reads `/etc/shadow` through ProtectSystem=strict. Then 10 more jobs of 8 plugins each ended `done` (88 spawns in all) |
| CHK-M10-188d (cgroup moves and kills; TASK-215's unproven items) | APP | W | job 1 | PASS | Each plugin backgrounded `sleep 300.228`. After the job:<br>• no such process is left (the kill and the after-job sweep with pidfd ran under `SystemCallFilter=@system-service ~@debug…`);<br>• the service subtree holds only `supervisor`;<br>• the runner's `/proc/<pid>/cgroup` ends in `/supervisor`.<br>The delegated writes worked under ProtectSystem=strict, and plugin start worked under RestrictNamespaces=yes |
| CHK-M10-188e (cleanup only on the PrivateTmp mounts) | APP | W | job 1 | PASS | Each plugin wrote `/tmp/p<n>` and `/var/tmp/q<n>`. After the job, `nsenter -t <runner> -m ls -A /tmp /var/tmp` lists nothing. The host's `/tmp/m10c-host-marker` and `/var/tmp/m10c-host-marker` are untouched |
| TASK-213 unproven item | APP | W | job 1 accepted | PASS | Under the verbatim unit, the runner (bitscan-runner, only CAP_DAC_READ_SEARCH) read `/var/lib/bitscan-agent/agent_id` through the `bitscan:bitscan 0700` directory: the job's `agent_id` check passed. The agent state dir is unchanged |
| TASK-217 unproven items (REQ-235 (3) in WSL) | APP | W | unit row | PASS | `nobody` (not in group `bitscan`) gets EACCES from `runner.sock` (0660). Root connects and is closed without any frame (the peer uid check); the journal has `peer refused … uid=0` |
| CHK-M10-189 (dumpable) | APP | W | unit row | PASS | `/proc/<runner>/environ` is owned by root, not bitscan-runner: `PR_SET_DUMPABLE` 0. The outside-systemd refusals (exit 1, one line) are TASK-229's step, run locally there |
| TASK-221 r2 at binary level | APP | W | unit row | PASS | After 88 spawns, every runner thread (7–15 seen) is at niceness 0 |
| CHK-M10-190 (REQ-251 (3)) | APP | W | journals of jobs 1–3 | PASS | No `CANARY` (execute and stdout canaries) and no `SHADOW` output in the journal. Job lines carry `job_id` |
| CHK-M10-191 (SIGTERM mid-job) | APP | W | job 2 | PASS | Two `sleep 300.191` plugins run. `systemctl kill -s TERM --kill-whom=main` reaches only the runner, so systemd killed nothing itself. The runner exited with status 0 ("bitscan-runner stopped"), and 1 s later no plugin process exists. The client saw no `done` |
| TASK-224 r2 end to end (pathless) | APP | W | job 3 with `-p BindReadOnlyPaths=/opt/m10c/ro-canary:/var/tmp/M10PATHCANARY-ro` | PASS | The after-job `/var/tmp` emptying fails on the read-only bind mount. No `done`. The journal gives "after-job cleanup failed", "job ended, cleanup failed" and `bitscan-runner stopping: cleanup cannot be guaranteed reason="unlinkat: read-only file system"`, with **no `M10PATHCANARY`** anywhere; the runner exited 1 |
| plant: `TmpDirs` nil in main | CODE | W | variant `notmp` | PASS (red) | 29/31: the private `/tmp` held `p0…p7` and `/var/tmp` held `q0…q7` after the job, and job 3's cleanup "failure" never happened (`done` sent) |
| plant: `Harden` skipped | CODE | W | variant `noharden` | PASS (red) | 30/31: "runner not dumpable" red (`environ` owned by bitscan-runner) |
| plant: the m0 `init` lock removed (TASK-221 r2) | CODE | W | variant `nolock` | **NOT REPRODUCED** at binary level (recorded) | 32/32 green twice. After 88 spawns, no runner thread was at nice 10. The real runner's main goroutine sits in `Serve`, and in these runs m0 never picked up a start goroutine, so this binary-level row can't tell lock from no lock. The lock's effect is proven at unit level: the delegated binary's plant `notestmainlock` is red, with m0 at nice 10. The `init` is present in main.go L31–36 (read) |
| CHK-M10-381 | CODE | L, W | `TestImportBoundary` (TASK-227 report) | PASS | `cmd/bitscan-runner` links no `net/http*`, `crypto/tls` or agent transport; the plant is red |

### Acceptance (TASK-228: "under `systemd-run` with the verbatim runner unit's properties and a socket unit (WSL with cgroup2, or CI), the driver's job runs and REQ-237 (2) and REQ-251 (1), (3) hold for `cmd/bitscan-runner`")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| A job runs under the verbatim unit (the harness client in place of the held driver) | CHK-M10-188c–e | PASS |
| REQ-237 (2) | CHK-M10-188a | PASS |
| REQ-251 (1) | CHK-M10-381 / TestImportBoundary | PASS |
| REQ-251 (3) | CHK-M10-190 | PASS |
| On a sandbox VM through the driver | — | NOT RUN: VM hold (the named gate exception). Cover: this WSL row with all 37 verbatim directives |

## TASK-229


Tester: tester-m10c, 2026-11-01. One approval (TS §8.2; PD-43). REQ-257, REQ-260; decisions rows:
- "The delegated runner tests in CI are a TASK-229 r1";
- "Delegated real-kernel rows must run as the unit user";
- "TASK-229 r2: the CI delegated step matches the TASK-224 job rows".

Under test: `.github/workflows/agent.yml` (impl-deploy-m10 r0/r1, impl-deploy-m10c r2; `work/reports/TASK-229-impl.md`):
- the gates job's "Runner and capread start-up refusals" step (r0), which replaces the M0 stub step;
- the go-test-ubuntu job's "Runner delegated cgroup tests" step (r1, r2), on `ubuntu-22.04` and `ubuntu-24.04`.

### How (local only; no push, so no hosted run)

`ci229.py` (outside the repo) parses the workflow and writes every `run:` block to a file. Each step's own shell was then run in WSL, from a copy:
- **Refusal step:** run as written by root, except two things. The "self" cases run as a non-root user `m10c-ci`, because the CI job user is non-root with a full bounding set. And the two `apt-get` lines are dropped (strace is installed).
- **Delegated step:** run as written, with `GITHUB_WORKSPACE=/opt/m10c/ws-<plant>` (a copy) and `RUNNER_TEMP=/root/m10c/rt`. Its `sudo systemd-run … -p User=bitscan-runner …` ran as is; root's sudo is a no-op. No step was refused by a safety check.
- Plants were made in each copy's files or in the extracted step script, never in the worktree.

### Runs

| Run | Command | Result |
| --- | --- | --- |
| YAML parse | `python3 -I ci229.py agent.yml` (PyYAML 6.0.1) | parses. `permissions: contents: read`. Every `uses:` is pinned to a 40-hex SHA. Jobs: gates on `ubuntu-24.04`; go-test-ubuntu with matrix `[ubuntu-22.04, ubuntu-24.04]` |
| `bash -n` | all 12 `run:` blocks | 12/12 OK |
| refusal step, M10 binaries | built by the step before it (static linux/amd64) | step exit **0** (6/6 cases) |
| delegated step, M10 tree | as written (r2) | step exit **0**: 37 `--- PASS`, 0 `--- FAIL` |
| plants | 3 refusal, 5 delegated | **8/8 red** |
| actionlint, shellcheck | — | NOT RUN: not installed on this host. Cover: the YAML parse, `bash -n`, and the step scripts run end to end |
| hosted PR run on both runners | — | NOT RUN: no push in this session (lead's brief). The local runs above are the same commands |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-313a (refusal step green on M10) | CODE | W | refusal step on the M10 build | PASS | All 6 cases: the exact stderr line (`time=` stripped), the exit code, empty stdout, and no socket call after the binary's execve. The cases:<br>• runner, full bounding set: `CapBnd holds capabilities beyond CAP_DAC_READ_SEARCH`, 1;<br>• runner as bitscan-runner with only dac_read_search: `sdsock: LISTEN_PID is not this process`, 1;<br>• `capread --serve`: the no-usable-socket line, 1;<br>• capread with no argument and with `/bin/sh`: the usage line, 2;<br>• `nft_ruleset` with the helper off: `not enabled`, 1 |
| CHK-M10-313b (red on the M0 stubs) | CODE | W | runner stub (`328b097`) | PASS (red) | Step exit 1. Both runner cases: "stderr is not the one expected line … got: bitscan-runner: not implemented" |
| CHK-M10-313c | CODE | W | capread stub (`328b097`) | PASS (red) | Step exit 1. All four capread cases red (exit 1 where 2 was wanted, and the stub line) |
| CHK-M10-313d | CODE | W | plant: the runner calls `net.Listen("unix", …)` before `run()` | PASS (red) | Step exit 1. strace shows `socket`/`bind`/`listen` after the execve, in both runner cases |
| CHK-M10-313e (r1/r2 delegated step green) | CODE | W | delegated step | PASS | It runs as bitscan-runner, ambient/bounding CAP_DAC_READ_SEARCH, NoNewPrivileges, PrivateTmp, StateDirectory and the r2 WorkingDirectory. The binary is in `/opt/delegated`, and the chmod loop gives o+x down the tree and o+r on the TS. Result: 37 PASS, unit exit 0 |
| plant A (r1) | CODE | W | a failing `TestDelegatedPlantedFailure` added | PASS (red) | Step exit 1 ("a test failed") |
| plant B (r1) | CODE | W | `-tags delegated` dropped from the build | PASS (red) | "no TestDelegated test passed; want at least one" |
| plant C (r2) | CODE | W | `-p PrivateTmp=yes` dropped | PASS (red) | `TestDelegatedJobTmpEmptied`: "refusing to empty /tmp and /var/tmp: they are not private mounts" |
| plant D (r2) | CODE | W | `-p WorkingDirectory=` dropped | PASS (red) | `TestDelegatedJobRedaction` fails: the TS isn't found from `/` |
| plant E | CODE | W | `-test.run NoSuchTestM10c` (zero tests run) | PASS (red) | "no TestDelegated test passed; want at least one" |
| CHK-M10-313f `go test ./...` on both hosts | CODE | — | `go-test-ubuntu` matrix | PASS (static) | The step `GOOS=linux GOARCH=amd64 go test ./...` sits in the matrix job on `ubuntu-22.04` and `ubuntu-24.04`. Its WSL equivalent is in the gate report |
| REQ-257 (2) | CODE | L | `grep -n 'arm64\|debian:12' .github/workflows/agent.yml` | PASS | nothing found |

### Acceptance (TASK-229: "the new step passes on the M10 binaries and turns red when the M0 stub runner is put back, and `go test ./...` runs on both runners")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| passes on M10 | CHK-M10-313a, e | PASS (local) |
| red with the M0 stubs | CHK-M10-313b, c | PASS (local) |
| `go test ./...` on both runners | CHK-M10-313f | PASS (static); hosted run NOT RUN (no push) |

## TASK-231


Tester: tester-m10c, 2026-11-01. Low risk (docs), one approval. REQ-258, REQ-255 (version); PD-42; decisions "PD-42 against check_debian_meta.py" (old-to-new rule) and "User decisions before the M10 merge" (1), the VM rows as a named exception.

Under test (`work/reports/TASK-231-impl.md`): `deploy/runbooks/agent-install.md` (sections 9–11 and the cgroup v2 prerequisite), `README.md` (the compliance paragraph) and `deploy/debian/changelog` (the `0.2.0~pre1-1` entry).

Test-side changes:
- `deploy/tests/check_debian_meta.py`: the first-entry rule is rewritten per the decisions row, and a release-guard check is added. All other assertions are unchanged.
- `check231.sh` (outside the repo): the doc checks below.

### Old → new check ids (`check_debian_meta.py`)

| Old | New | Change |
| --- | --- | --- |
| CHK-M6-100 (`VERSION_RE` `^\d+\.\d+\.\d+-[1-9]\d*$`: a release, no `~`; #90) | **CHK-M10-318** | `VERSION_RE` `^\d+\.\d+\.\d+(?:~pre[1-9]\d*)?-[1-9]\d*$`: `X.Y.Z-R` or `X.Y.Z~preN-R` with N ≥ 1 and R ≥ 1 (PD-42). The RFC 2822 trailer date, the weekday and strictly-decreasing dates are all kept |
| (#90's protection, now held in `release.yml`) | **CHK-M10-319** (new) | `release.yml` must keep a `case "$deb" in` arm `*"~"*) … exit 1 ;;` on the `dpkg-parsechangelog -l deploy/debian/changelog -S Version` value, so a `~preN` build is never released. The release gate is unchanged and now has a check of its own |
| every other assertion | unchanged | rules, control, copyright, install, source/format, no arm64 |

### Runs

| Run | Command | Count |
| --- | --- | --- |
| meta check on the tree | `python -I deploy/tests/check_debian_meta.py --root .` | **OK 81/81** (78 before, plus CHK-M10-319's 2 checks and the rule's own line) |
| meta plants | `plantmeta.sh` (throwaway copies) | **8/8 red**, plus 2 green controls |
| doc checks (W) | `check231.sh` | **33/33 passed** |
| links | `python -I deploy/tests/check_md_links.py README.md deploy/runbooks/agent-install.md` | OK, 28 links, 0 findings |
| runbook text | `python -I deploy/tests/check_runbook_text.py deploy/runbooks/agent-install.md README.md` | 2 findings, both **pre-existing** on HEAD (M6 lines 76/120, the placeholder `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`). None in the M10 additions. This check is not a CI gate for this file |
| units verbatim (G17 part) | `python -I deploy/tests/check_units_verbatim.py` | OK, 10 files, 0 problems |

### Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-315a version | CODE | W | `dpkg-parsechangelog -l deploy/debian/changelog -S Version` | PASS | `0.2.0~pre1-1` (PD-42). `dpkg --compare-versions`: 0.1.0-1 < 0.2.0~pre1-1 (the runbook's upgrade claim), 0.1.0~pre1-1 < 0.1.0-1, and 0.2.0~pre1-1 < 0.2.0-1 |
| CHK-M10-315b no secret or process note | CODE | W | greps over the 112 added lines of the three files | PASS | No token-shaped text (`bs[aeku]_…`); no `TASK-`, `REQ-`, `CHK-`, `PD-n`, tester, reviewer, `impl-`, "decisions" or `#NNN`; no `password=`/`token:` values |
| CHK-M10-315c quoted lines match the built code | CODE | W | `check231.sh`: each quoted string grepped in the source of the binary that prints it | PASS | 23/23 found, for example:<br>• `bitscan-runner started`;<br>• the `runner_unavailable` log line and `runner_unavailable: <reason>`;<br>• `start-up refused` and the four `runner: refusing to start: …` reasons;<br>• `bitscan-capread: not enabled`, `not_installed`;<br>• `agent.yaml: spool_max_mb: must be 1 to 50`;<br>• `spool full: …`;<br>• `spooled results dropped at start` and its `last_error`;<br>• `the result spool could not be opened; compliance jobs are refused`;<br>• `spool: not opened; compliance jobs refused`;<br>• `job refused; not run` / `no compliance handler` / `job refused: `;<br>• the manager's `agent last_error` log and the `runner_helper_changed` alert.<br>"The manager fails it 24 hours after it was handed out" matches M9's never-started sweep (`sweep.py`: "dispatched strictly more than 24 h ago"). Several lines were also seen live: `bitscan-runner started`, `start-up refused …`, the socket mode `srw-rw---- root bitscan-runner` and `not enabled` (TASK-226/228 WSL rows) |
| CHK-M10-315d commands | CODE | W | the new `sh` blocks | PASS | `findmnt --task 1 -n -o OPTIONS --mountpoint /tmp` and `du -sb` parse with the host's util-linux and coreutils. `systemctl is-active/enable --now/disable --now`, `journalctl -u`, `ls -l /run/bitscan/capread.sock` and `sudo -u bitscan-runner /usr/sbin/bitscan-capread nft_ruleset` match the unit and file names (the capread row ran the same client as bitscan-runner) |
| CHK-M10-315e README | CODE | L | read and `check_md_links.py` | PASS | It says hosts on this build run compliance jobs, that the results views come later ([Scans](#scans) resolves), and links the runbook sections 9–11 |
| CHK-M10-318 | CODE | L | meta check on the tree | PASS | `PASS changelog: version 0.2.0~pre1-1 is X.Y.Z-R or X.Y.Z~preN-R (N, R >= 1)` |
| CHK-M10-319 | CODE | L | meta check on the tree | PASS | `PASS release.yml: refuses a changelog version holding "~"` and `PASS release.yml: the guard reads the changelog version` |
| plant: `0.2.0~rc1-1` (decisions row) | CODE | L | first entry rewritten | PASS (red) | 80/81, the version check red |
| plant: `0.2.0~pre0-1` (decisions row) | CODE | L | first entry rewritten | PASS (red) | 80/81 |
| plants: `0.2.0~pre1`, `0.2.0~pre1-0`, `0.2.0~1-1`, `0.2.0~pre1a-1` | CODE | L | first entry rewritten | PASS (red ×4) | 80/81 each |
| plant: release.yml's `~` refusal removed (decisions row) | CODE | L | `*"~"*)` arm deleted | PASS (red) | `FAIL release.yml: refuses a changelog version holding "~"` |
| plant: release.yml's `~` arm made harmless (`true` in place of `exit 1`) | CODE | L | arm edited | PASS (red) | the same check red |
| controls | CODE | L | `0.2.0-1`, `0.2.0~pre12-3` | PASS (green) | 81/81 each |
| CHK-M10-315f VM runbook walk (REQ-258 (1)) | APP | VM | — | **NOT RUN** | VM hold: the user's named gate exception (decisions 2026-11-01 (1)); it must run before any M11 code or release. Cover: CHK-M10-315c and d, plus the TASK-226 and TASK-228 WSL rows that ran the same commands and saw the same lines |

## M10-gate


Tester: tester-m10c, 2026-11-01. Tree: worktree `Bitscan-m10`, branch `m10-runner`, which is main `328b097` plus the uncommitted M10 files.

Environments:
- **L:** Windows 11, Go 1.27.2. No `-race`: it needs cgo, and this host has no C compiler.
- **W:** WSL Ubuntu 24.04, cgroup2fs, systemd 255, Go `/opt/go1.27.2`, with my own GOCACHE and GOMODCACHE (`/root/m10c`) and my own venv (`/root/m10c/venv`, `pip install --require-hashes -r manager/requirements-dev.txt`, then `-e` of the copy). Every Go unit run used `-race`.
- **WD:** W, delegated, as `bitscan-runner`: `systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p StateDirectory=m10c-job`.

Plants were made only in throwaway copies; the worktree holds none.

**The named exception** (user, decisions 2026-11-01 (1)): G76, the VM half of G78, G79, the VM-planted CHK-M10 rows, TASK-230 (sandbox CI, G77) and TASK-231's runbook walk are NOT RUN, reason "VM hold (safety check)". They must run before any M11 code and before any release, and no tag is made. Each row below names its lower-level cover.

### Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| Agent suite, W | `go test -race -count=1 ./...` from `agent/` (fresh copy with `manager/tests/contract/` incl. `loader.py`) | **PASS** | **1333/1341 passed, 2 failed, 6 skipped**. The 2 were `TestBuildBodyLargeLists/50000` and its parent, an M4 timing bound: "50,000 rows built in 6.27 s, want < 5 s" under full-suite `-race` load. Re-run alone: **3/3 passed** (0.94 s). Final: **1335/1341 passed, 0 failed, 6 skipped** (4 wire schema-gap skips per main's 2026-10-23 ruling, 1 `state` root-only row, 1 `inventory` row). 19 packages. Per package: cmd/bitscan-capread 1, cmd/bitscan-runner 8, internal (boundary) 1, agent/config 98, enrol 53, loops 124, runnerclient 38, schedule 12, state 47+1 skip, token 42, transport 56, wire 363+4 skip, capread 19, inventory 112+1 skip, redact 78, runner 121, runner/proto 108, sdsock 20, spool 34 |
| Agent suite, L | `go test -count=1 ./...` from `agent/` | PASS except the known pre-existing Windows rows | **1023/1052 passed, 25 failed, 4 skipped**. 17 packages: 11 pass, 3 have no Windows tests, 3 fail. Every failure is M4 code unchanged in M10 (`git diff HEAD -- agent/internal/agent/{enrol,state,transport}` is empty), and the Linux-only M10 files don't build on Windows:<br>• `enrol` 19 rows and `loops` 5 rows (TestJobChecks, TestJobSeenSevenDays, TestJobSeenBeforeAct, TestJobDispatchOrder, TestJobPickupRecheckedAtStart): `state.syncDir` fsyncs a directory, which Windows refuses ("Access is denied");<br>• `transport` TestTLSConfigErrors: chmod 0 isn't enforced on Windows.<br>Linux-only, not built on Windows: `compliance_linux_test.go`, `compliance_r1_linux_test.go`, `inventory_linux_test.go`, every `*_linux_test.go`. TestJobPickupRecheckedAtStart used to hang until the package timeout; a fail-fast was added (test-side only, no assertion changed). Loops on Windows: 93/98 passed, 5 failed (the rows above) |
| Delegated binary (G72 half) | WD, `-test.run Delegated` | **PASS** | **37/37 passed** (cgroup 5, spawn 7, remove-temp 3, job 22), unit exit 0. Identity logged: uid 999, CapEff/Prm/Bnd/Amb 0x4, NoNewPrivs 1 |
| G1 | `ruff check manager` (W) | PASS | "All checks passed!" |
| G2 | `ruff format --check manager` (W) | PASS | 386 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` (W) | PASS | "Success: no issues found in 386 source files" |
| G4 | the venv built with `--require-hashes`; `git diff --stat HEAD -- manager/requirements*.txt manager/pyproject.toml manager/bitscan_manager manager/openapi.json` | PASS | install OK; the diff is empty. M10 changed only manager **tests** (`tests/contract/fixtures/manifest.json`, `test_contract_fixtures.py`, `test_redaction_crosscheck.py`, the redaction corpus) |
| G5 | services coverage in G18 | PASS | **98.53 %** (5,692/5,777) of `bitscan_manager/services` (gate 85 %) |
| G6 | `tests/test_openapi.py` in G18; `git diff HEAD -- manager/openapi.json` | PASS | green; openapi.json unchanged |
| G18 | full manager suite, `pytest -n 2 -rfEs --cov` (W, `CI=true`, PostgreSQL 16 by Testcontainers) | **PASS** | First run: **11,205 passed, 3 failed, 3 errors** of 11,211 (26 min 45 s). All 6 were my environment: the WSL copy lacked the web UI build and `README.md` ("the web UI build is missing"; `FileNotFoundError …/README.md`). The UI was then built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`), and it and README.md were copied into the WSL copy only, not the worktree. The 6 node ids re-ran: **6/6 passed**. Final: **11,211/11,211**, 0 skipped. Not product failures |
| G7 | `gofmt -l agent` | PASS | prints nothing |
| G8 | `golangci-lint run ./...` v2.14.0 (W, plus `--build-tags delegated`; L) | PASS | 0 issues in all three. During the gate, 4 findings in **my** new test files were fixed: 3 × G204 in `cmd/bitscan-capread/main_test.go` and `internal/boundary_test.go` (test-file `nolint:gosec` with a reason, the repo's practice for tests), and an unused field in `results_test.go`. A deprecated `runtime.GOROOT()` was replaced with `go` from PATH. Earlier, a G115 in `serve_linux_test.go` was fixed with a checked bound (reviewer-m10c) |
| G9 | `go mod verify`; cold-cache `go mod download` | PASS | "all modules verified"; the cold-cache download rc 0 |
| G10 | `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath ./cmd/...`; `go list` for cgo/asm/syso | PASS | three ELF x86-64 binaries, statically linked; no cgo, asm or syso |
| G11 | nolint/linkname grep, non-test agent code | PASS | 0 hits |
| G17 | `check_units_verbatim.py`; `systemd-analyze verify` of the five agent units (0644 copies) | PASS | "OK 10 files checked, 0 problems". Verify printed only "Command /usr/sbin/bitscan-* is not executable" (binaries not installed). Plants CHK-M10-387 to -390 red (table) |
| G35 | Go contract test (in the W suite), plus the manager's `test_contract_fixtures.py` | PASS | `internal/agent/wire` 363/367 (4 schema-gap skips, main ruling 2026-10-23). The `redaction/corpus.json` fix: the manifest has a `shared_files` section and both checks count it; 5/5 plants red (Go and Python) |
| G36 | `go test -race ./internal/agent/... -run 'Security\|TLS\|Job'` (W) | PASS | **64/64 passed**, 0 failed, 0 skipped |
| G37 | `test_build_deb.sh all` (lintian part) in m4b-build-u24 | PASS | `lintian --fail-on error,warning` passes, with no E:/W: tag and every override used and reasoned |
| G38 | `test_maintainer_scripts.sh --deb <0.2.0~pre1-1> --from <0.1.0-1> all upgradefrom` in a privileged m4b-sysd-u24 container | **NOT RUN** | The first `.deb` build for it stalled downloading the SBOM tool's modules: its log stopped at 16:58, so the network stalled. The next action, stopping that run and its throwaway container, **was refused by a safety check**, so per my brief G38 was not retried or worked around. main was told. Cover: G37, G39 and G40 passed on a fresh M10 `.deb` (108/108, contents byte-identical to `deploy/`), and `check_debian_meta.py` 81/81. The 0.1.0-1 → 0.2.0~pre1-1 ordering is checked with `dpkg --compare-versions` (TASK-231). The maintainer scripts are unchanged since M6 (`git diff HEAD -- deploy/debian/*.post* deploy/debian/*.pre*` empty). package.yml runs G38 in CI on the push |
| G39 | `test_build_deb.sh all` (repro) | PASS | Two builds at different paths. Identical sha256: `.deb` 5ac2b149…8045, `.sha256` 206fa92b…6e89, bitscan-agent 490cc875…8917, bitscan-runner fb65da6b…76c2, bitscan-capread 7d001846…e06e; SBOM bytes identical |
| G40 | `test_build_deb.sh all` (sbom) | PASS | The runner and capread SBOMs list `golang.org/x/sys v0.49.0` (PD-41); the agent's doesn't link it. `test_build_deb.sh` total **108/108** |
| REQ-255 (3) | the M0 stub text in the built binaries | PASS | The static gate builds (same flags as the package) hold 0 copies of `bitscan-runner: not implemented` / `bitscan-capread: not implemented`. The other "not implemented" strings are the Go runtime's (ENOSYS "function not implemented"), not stubs. The packaged runner and capread are the same source and flags (test_build_deb `flags` 108/108) |
| G41 | `e2e/agent_manager.sh` (the installed `.deb` against the real manager, W) | **NOT RUN** | It was queued behind G38 and needs that `.deb`, so it was stopped by the same safety-check refusal (above). Cover: the M10 agent binary walk against the fake manager (TASK-227, 120/120, inventory included), the inventory package suites (W), M9's inventory suites in G18 (11,211/11,211). The inventory path is unchanged in M10 |
| G71 | redaction: `go test -race ./internal/redact/...`; `test_redaction_crosscheck.py` | PASS | **78/78**; the RE2 cross-check is green in G18 (45/45 at TASK-210) |
| G72 | runner Linux suites `./internal/runner/... ./internal/sdsock/...`, plus the delegated binary | PASS | **141/141** (runner 121, sdsock 20), plus **37/37 passed** (cgroup 5, spawn 7, remove-temp 3, job 22), unit exit 0 delegated |
| G73 | `./internal/agent/... ./internal/spool/...` | PASS | **867/872 passed, 0 failed, 5 skipped** (5 skips: 4 wire schema gaps and 1 state root-only row) |
| G74 | `./internal/capread/... ./cmd/bitscan-capread/` | PASS | **20/20**; the WSL helper-unit row (TASK-226) |
| G75 | protocol and the import boundary | PASS | **109/109** (proto 108, boundary 1); plants -323, -380, -381 red |
| G76 | sandbox suite on `bitscan-u2204`/`bitscan-u2404` | **NOT RUN** | VM hold (safety check), the named exception. Cover: G77 is also held, so the cover is the WD rows (TASK-215/221/224), the TASK-228 runner under all 37 verbatim service directives in WSL, G17 |
| G77 | sandbox suite on hosted runners (TASK-230) | **NOT RUN** | VM hold: it runs only the held harness (lead's ruling). Cover: as G76 |
| G78 | runner security suite | unit part **PASS**; host part **NOT RUN** | Unit: CHK-M10-260/261 (TASK-213 checks; TASK-225 serve rows: expired, foreign, replayed, malformed, second frame, busy; TASK-217 wrong peer; TASK-222 capread names). The WSL unit row also refused root (closed, no frame), and `nobody` got EACCES (TASK-228). Host part (CHK-M10-280 to -289) NOT RUN: VM hold |
| G79 | first compliance run on `bitscan-u2404` against the WSL manager | **NOT RUN** | VM hold. Cover: the agent binary walk end to end (TASK-227, 120/120), the redaction rows (TASK-210 CHK-M10-020/080; TASK-224 CHK-M10-155) and the manager's M9 intake suites in G18 |
| CHK-M4-223 | `TestNoOtherJobSourceStatic` | **PASS** (rewritten) | User decision 2026-11-01 (2): rewritten as **CHK-M10-271**, with `runner.sock`/AF_UNIX only in `internal/agent/runnerclient`; 9/9 plants red (TASK-223 report). It was held FAIL before the decision; it is no longer FAIL |
| CHK-M4-100 (static), -344, -345 | `TestNoOtherProcessExecutionInAgent` | **PASS** (rewritten) | Found at this gate: it forbade the M10 process sites that REQ-256 allows. main's ruling: rewritten as **CHK-M10-272**, below; 4/4 plants red |
| Pre-existing M6 row | `check_runbook_text.py deploy/runbooks/agent-install.md` | pre-existing (not M10) | HEAD and M10 give the same 2 findings, both M6 placeholder lines in §3 Install: HEAD L76/L120 = M10 L79/L123 (`… password bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`, `ENROL_TOKEN=bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`). M10's sections (§1, §4, §6, §9–§11; 5 more sh blocks) add none. The checker isn't a CI gate for this file, and nothing was edited |

### Old → new check ids at this gate

| Old | New | Rule |
| --- | --- | --- |
| CHK-M4-223 | CHK-M10-271 | `runner.sock`, `"unix"`/`"unixgram"`/`"unixpacket"`, `net.UnixAddr`/`DialUnix`, `syscall/unix.AF_UNIX`/`Socket`/`Connect`/`Bind` and `golang.org/x/sys/unix` only in `internal/agent/runnerclient`; `net.Dial*` only in runnerclient and transport; `net.Listen*`/`FileListener`/`FileConn` nowhere. The exec-name and RunJob/Handle-caller assertions are kept. The test fails if the walk sees fewer than 2 runnerclient sites |
| CHK-M4-100 (static), -344, -345 | CHK-M10-272 | Per file and exact: `internal/inventory/command.go` has exactly one `exec.CommandContext` and the 3 #35 command literals; `internal/runner/spawn_linux.go` has exactly one `exec.Cmd` literal and `"/bin/sh"` and `"-c"` once each, with no `exec.Command*`; `internal/capread/serve_linux.go` has exactly one `exec.CommandContext` and no shell literal. `os/exec` is imported only by those three and `inventory/command_*.go`. Everything else is kept. Plants red: an exec in loops; a shell literal in capread; a second `CommandContext` in the runner; a second `exec.Cmd` literal in another runner file |
| CHK-M6-100 | CHK-M10-318 (+ new CHK-M10-319) | `check_debian_meta.py`: `X.Y.Z-R` or `X.Y.Z~preN-R` (N, R ≥ 1), and `release.yml` keeps its `*"~"*) … exit 1` guard (TASK-231 report) |
| CHK-M4-220, -221 | PD-45 rows | TASK-223 report |

### M10 mutation table (CHK-M10-320 to -393)

Each plant was made in a throwaway copy and turned its named check red for the planted reason. "VM half" rows are part of the named exception (NOT RUN, VM hold) and keep the unit-level red shown. Source is the TASK test report holding the evidence.

| CHK | Plant | Unit-level result | VM half | Source |
| --- | --- | --- | --- | --- |
| -320 | peer check removed | red (CHK-M10-118) | NOT RUN, VM hold | TASK-217 |
| -321 | gid compared, not uid | red | — | TASK-217 |
| -322 | second request frame run | red ("executor ran 2 times") | — | TASK-225 |
| -323 | `"command"` beside `job` accepted | red | — | TASK-209 (+ TASK-225 malformed rows) |
| -324 | inventory job accepted | red | — | TASK-209, TASK-213 |
| -325 | runner `agent_id` check removed | red | NOT RUN, VM hold | TASK-213 |
| -326 | `pickup_by` > 25 h accepted | red | — | TASK-213 |
| -327 | seen set removed | red | NOT RUN, VM hold | TASK-213 |
| -328 | `pickup_by` = now accepted | red | — | TASK-213 |
| -329 | `PR_SET_DUMPABLE` not set | red (unit) and red at binary level (TASK-228 `noharden`) | NOT RUN, VM hold | TASK-216, TASK-228 |
| -330 | fd 3 not CLOEXEC | red | NOT RUN, VM hold | TASK-217 |
| -331 | runner environment inherited | red (WD) | NOT RUN, VM hold | TASK-221 |
| -332 | `TMPDIR` added / `PATH` changed | red ×2 (WD) | — | TASK-221 |
| -333 | stdin inherited | red (WD) | NOT RUN, VM hold | TASK-221 |
| -334 | niceness not applied | red (WD) | NOT RUN, VM hold | TASK-221 |
| -335 | I/O class not applied | red (WD) | NOT RUN, VM hold | TASK-221 |
| -336 | plugin in `supervisor` | red (fake tree, WD spawn and job rows) | NOT RUN, VM hold | TASK-215, -221, -224 |
| -337 | no `cgroup.kill` at exit | red (fake tree, WD) | NOT RUN, VM hold | TASK-215, TASK-224 |
| -338 | sweep removed | red (fake tree, WD as bitscan-runner) | NOT RUN, VM hold | TASK-215, TASK-224 |
| -339 | sweep skips nested | red (fake tree, WD) | NOT RUN, VM hold | TASK-215 |
| -340 | statfs check removed | red (unit) | NOT RUN, VM hold (u2204 v1 boot) | TASK-216 |
| -341 | temp dir kept | red (WD spawn and job) | — | TASK-221, TASK-224 |
| -342 | private `/tmp` not emptied | red (WD job; binary level `notmp`) | — | TASK-224, TASK-228 |
| -343 | timeout not enforced | red (WD) | NOT RUN, VM hold | TASK-224 |
| -344 | redaction after truncation | red | G79 half NOT RUN, VM hold | TASK-210 |
| -345 | cut-off rule skipped without pattern 2 | red | — | TASK-210 |
| -346 | read limit or drain removed | red | — | TASK-214 |
| -347 | `truncated` not set on overflow | red | — | TASK-210 |
| -348 | cut splits a rune | red | — | TASK-210 |
| -349 | stderr cut sets `truncated` | red | — | TASK-210 |
| -350 | `Expand` replacement | red | — | TASK-210 |
| -351 | 51 patterns accepted | red | — | TASK-210, TASK-213 |
| -352 | bad pattern skipped | red | — | TASK-210, TASK-213 |
| -353 | empty-match pattern accepted | red | — | TASK-210 |
| -354 | growth guard removed | red | — | TASK-210 |
| -355 | signal → −1 | red | — | TASK-214 |
| -356 | job written to spool/state | red | — | TASK-212 (+ TASK-223/227 state greps) |
| -357 | raw output on redaction failure | red | — | TASK-214 |
| -358 | resend to a restarted runner | red ("2 runner requests, want 1"; unit), and green-guarded at binary level (walk `sigterm`) | — | gate plant (this report), TASK-223, TASK-227 |
| -359 | final for an interrupted job | red | — | TASK-212 (+ walk `sigterm`) |
| -360 | batch of 51 | red | — | TASK-220 |
| -361 | batch over 1,572,864 | red | — | TASK-220 |
| -362 | 409 retried | red | — | TASK-220 |
| -363 | 429 dropped | red | — | TASK-220 |
| -364 | newest dropped first | red | — | TASK-219 |
| -365 | dropped without a marker | red | — | TASK-219 |
| -366 | non-atomic spool write | red | — | TASK-212 |
| -367 | `spool_bytes` 0 | red | — | TASK-223 |
| -368 | start notice missing or late | red | — | TASK-220 |
| -369 | two jobs at once | red | — | TASK-223 |
| -370 | inventory waits for compliance | red at binary level (walk `invheld`: "inventory_uploaded_while_compliance_held" FAIL with both kinds on one worker) | — | gate plant (this report) |
| -371 | capread third name | red | NOT RUN, VM hold | TASK-222 |
| -372 | request text as an argument | red | — | TASK-222 |
| -373 | capread environment passed | red | NOT RUN, VM hold | TASK-222 |
| -374 | capread peer check removed | red | NOT RUN, VM hold (the WSL helper unit refused uid 997 and 0 on the real code, TASK-226) | TASK-222 |
| -375 | capread timeout 60 s | red | — | TASK-222 |
| -376 | capread cap removed / cut sent | red | — | TASK-222 (+ the TASK-226 client cap plant) |
| -377 | capread parallel | red | — | TASK-222 |
| -378 | `net.FileListener` outside sdsock | red (G8) | — | TASK-211 |
| -379 | `exec.Command` in `compliance.go` | red (G8) | — | TASK-211 (+ CHK-M10-271/272 plants) |
| -380 | agent imports runner/redact | red ×4 | — | TASK-227 |
| -381 | runner imports `net/http` | red ×2 | — | TASK-227 |
| -382 | runner logs a stdout canary | red (executor and serve halves) | canary sweep NOT RUN, VM hold | TASK-224, TASK-225 |
| -383 | agent logs a result's stdout | red ("a result's stdout was logged") | — | gate plant (this report) |
| -384 | heartbeat triggers the runner | red (CHK-M10-271 static) | — | TASK-223 |
| -385 | euid 0 accepted | red | — | TASK-216 |
| -386 | capability check removed | red (unit) | NOT RUN, VM hold | TASK-216 |
| -387 | one unit character changed | red ("DIFF bitscan-runner.service line 48") | — | gate plant (this report) |
| -388 | D-Bus policy allows `StartUnit` | red ("DIFF bitscan-runner.conf line 17") | NOT RUN, VM hold | gate plant (this report) |
| -389 | runner unit without `InaccessiblePaths=` | red ("DIFF bitscan-runner.service line 45") | NOT RUN, VM hold | gate plant (this report) |
| -390 | runner unit without `NoExecPaths=` | red ("DIFF bitscan-runner.service line 20") | NOT RUN, VM hold | gate plant (this report) |
| -391 | runner keeps running after the close | red (executor and serve halves) | NOT RUN, VM hold | TASK-224, TASK-225 |
| -392 | foreign result spooled | red | — | TASK-212, TASK-218 (+ TASK-223 r1 row) |
| -393 | `agent_id` read once | red | — | TASK-213 |

Summary: 74 rows (-320 to -393), all red at unit or binary level. The VM halves of -320, -325, -327, -329, -330, -331, -333 to -340, -343, -371, -373, -374, -386, -388 to -391 are NOT RUN (the named exception), along with the G79 half of -344 and the canary sweep of -382.

### NOT RUN at the M10 gate, with reason and cover

| Row | Reason | Cover |
| --- | --- | --- |
| G76 (sandbox suite on `bitscan-u2204`, `bitscan-u2404`), every CHK-M10-200 to -259 row | VM hold (safety check), the named exception (decisions 2026-11-01 (1)) | WD rows as bitscan-runner (TASK-215, -221, -224: 37/37). The TASK-228 runner under all 37 verbatim service directives and the 5 socket directives in WSL: caps 0x4, 8 parallel plugins, cgroup moves and kills, private `/tmp` only, SIGTERM sweep, peer refusal, EACCES for a non-member. The TASK-226 helper under all 23 verbatim directives (CapEff 0x40001000, real nft). G17 for the directives |
| G77 (TASK-230 sandbox CI) | VM hold: it runs only the held harness | as G76 |
| G78 host part (CHK-M10-280 to -289) | VM hold | G78 unit part (TASK-213/217/222/225) and the TASK-228 WSL row |
| G79 (first compliance run, CHK-M10-290 to -292) | VM hold | The agent binary walk (TASK-227, 120/120: end to end, runner absent → runner_unavailable, overflow), real-path redaction (TASK-224 CHK-M10-155), the M9 manager intake suites in G18 |
| VM halves of the mutation rows listed above | VM hold | each row's unit-level red |
| TASK-231 runbook walk (CHK-M10-315f, REQ-258 (1)) | VM hold | 23/23 quoted lines found in the code; the commands parse; the TASK-226/228 WSL rows saw the same lines |
| REQ-252 audit half (`auditctl -l` real output) | not possible in WSL: the kernel refuses audit netlink to the distro (root itself gets EPERM) | TASK-222 rows; the helper passes the exit status through (`failed 255`, the same as root); VM row (held) |
| TASK-229 hosted run on `ubuntu-22.04`/`ubuntu-24.04`; actionlint, shellcheck | no push in this session; tools not installed | the step scripts extracted and run end to end in WSL, with plants (TASK-229 report) |
| Binary-level plant of the TASK-221 r2 m0 lock | not reproducible: the real runner's m0 never took a start goroutine in 88 spawns | the unit-level plant `notestmainlock` is red, with m0 at nice 10 |
| Nightly end-to-end on three VMs, results views, CSV, re-evaluation, N/N−1 matrix | M11 (planned) | — |
| Load tests | deferred by the user | — |
| Debian 12, arm64 | not supported (decisions 2026-10-24) | — |

## PR #18 CI fix

Tester: tester-m10d, 2026-11-01. Verdict and evidence: [work/reports/PR18-ci-fix-test.md](../../work/reports/PR18-ci-fix-test.md). Test files only. WN = WSL as non-root `bstester` (the CI condition), WR = WSL as root, WM = WSL manager suite (`CI=true`, Testcontainers). Go rows use `-race -count=1`.

| Check | Type | Env | Command / test | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-117, -118 (`TestPeerCheck`) | APP | WN / WR | `go test -race ./internal/sdsock/` | PASS (WR); named SKIP (WN) | It used to `t.Fatal` as non-root; it is now a named skip ("needs root … this row runs in agent.yml's root step"), the M4 form. WR 20/20 with 3 subtests. Plants -320 (peer check removed) and -321 (gid compared) red as root. Needs the new agent.yml root step (requested from impl-deploy via main) |
| CHK-M10-139 (`TestPeerCheckThroughSdsock`) | APP | WN / WR | `go test -race ./internal/capread/` | PASS (WR); named SKIP (WN) | As above. WR 19/19. Plant -320 red as root (`peer uid 0 got "ok\nserved"`) |
| Builder checklist 21 (`TestConnectPermissionDeniedLinux`) | APP | WN / WR | `go test -race ./internal/agent/runnerclient/` | PASS (WR); named SKIP (WN) | As above. WR 38/38 (child `WORD=connect … UID=65534 SECONDS=0.0`). Plant 218h (EACCES retried as busy) red as root (28 s) |
| Proposed agent.yml root step | CODE | WR / WN | the step body, emulated | PASS | WR exit 0, the three `--- PASS`. WN without root: exit 1 (each row SKIP → red). A copy with the peer check removed and EACCES retried as busy: exit 1, three `--- FAIL` |
| CHK-M10-079 (`TestHandlerSpoolBytesAndNoRunnerFromHeartbeat`) | CODE | WN | `go test -race -run … ./internal/agent/loops/` | PASS (rewritten timing) | CI red was a test race (a heartbeat built before `Finish` rewrote `job.json` 1 byte shorter), not product. Now compared at rest, against a heartbeat built after that point; the assertion is unchanged. ×20 20/20. Diagnosis plant: old test 0/3 with CI's exact 180969/180968, new 3/3. Plants -367 (0) and +1 red |
| CHK-M10-065 / CHK-M4-221 → REQ-246 (1) (`TestPD45Batches`) | CODE | WN | `go test -race -run TestPD45Batches ./internal/agent/loops/` | PASS (old → new assertion) | Old: the 503 retry is byte-identical. New (TASK-220 r1): the same plugins, each once, each the same result or its marker, and a final copy stays final; every other assertion is kept. 1/50/51/120 ×10 at `-cpu 1,2,4` 150/150; 5000 ×3 at `-cpu 1,2` PASS. Diagnosis plant (Finish 20 ms late): old 0/5 "sent different bytes", new 5/5. Plants (lost, duplicate, changed result) red |
| CHK-M9-225 (`test_well_formed_batches_for_jobs_that_cannot_take_them_are_409`) | APP | WM | serial and `-n 2`: `test_fleet_alerts_pg.py test_jobs_api_pg.py test_schema_scanning.py` | PASS (isolation fix) | The REQ-214 (2) case committed a result for a job dated 2026-10-23. From 2026-11-01 that row lands in `scan_result_default` of the shared database, which fails `test_default_partition_is_empty_after_migrate` (CI) and `test_default_partition_rows` (if run after it). Now removed in a `finally`; assertions unchanged. Culprit-first order: unfixed 1/3, fixed 3/3; 119/119 serial and with `-n 2`; the cleanup holds when the culprit fails |
| CHK-M3-232 (`test_slow_runs_never_execute_twice_at_once`) | APP | WM | `pytest tests/test_serve_scheduler_linux.py::test_slow_runs_never_execute_twice_at_once` (CI=true), ×30 | PASS (timing rewritten); ×30 30/30, stop delayed 0.5–2.5 s 8/8 | The attempt-1 flake was a test race. serve sets the stop flag only after the uvicorn and catalog shutdown, so a run starting after `signalled` could give up uncounted. "In flight" is now "still running when `SchedulerRunner.stop()` began", traced by the test launcher; the assertion is unchanged. Diagnosis plant (stop 1.5 s late): old 0/3 with CI's exact message, new 3/3. Two sweeps at once: red 3/3. Module 9/9 |
| CHK-M1-145, the "empty after migrate" part (`test_default_partition_is_empty_after_migrate`) | APP | WM | serial, CI order, every file up to and including `test_schema_scanning.py` | PASS after the fix (unchanged test) | Reproduced red before the fix (9,977 passed, 2 failed: this row and a no-web-build row of my copy). The probe pins the row to CHK-M9-225's case |
| CHK-M10-164, -165 + TASK-225 r1 (`TestServeBusy`, `TestServeMalformed`, new `TestServeNextConnectionAfterEndNeverBusy`, `TestServeNoJobAfterFatal`, `TestServeTightDialAroundFatal`) | CODE | WN / WR | `go test -race ./internal/runner/ -run TestServe`: all rows but the two wall-clock deadline rows ×50 at `-cpu 1,2,4`, those two ×1 at `-cpu 1,2,4` | PASS (TASK-225 r1) | 3750/3750 + 12/12 as uid 1000 and as root; each named row 150/150. TestServeMalformed's assertion is unchanged. Plants: Serve's LIFO defers (+2 ms) red (TestServeMalformed with CI's message, and the new busy row); `handle`'s close-to-wake (+2 ms) red (the new row only, after job rounds); r1 with the same 2 ms green 420/420; `failed` check removed → TestServeNoJobAfterFatal red 15/15. Report §6 |

## M10 sandbox suite, G78 host part, VM plants, TASK-230 (2026-11-02, cloud session)

Full record: [work/reports/M10-vm-test.md](../../work/reports/M10-vm-test.md) "Sandbox suite, G78 host part, VM plants and TASK-230"; row tables in [work/reports/m10-sandbox/](../../work/reports/m10-sandbox/). Harness: `agent/test/sandbox/` (`run_vm.sh`, `sandbox.py`, `plants.sh`) and `.github/workflows/sandbox.yml`.

| Gate | Where | Result |
| --- | --- | --- |
| G76 (CHK-M10-200 to -223) | QEMU stand-in VMs of the Ubuntu 22.04 and 24.04 cloud images, fresh overlay per run (not the Hyper-V VMs) | 32 PASS, **2 FAIL (201, 203)**, 2 NOT RUN on each; CHK-M10-214 PASS on the 22.04 VM booted with cgroup v1 |
| G77 (TASK-230) | GitHub `ubuntu-22.04`, `ubuntu-24.04` (24.04 with `auditd`) | 22.04: 32 PASS, 2 FAIL (201, 203), 2 NOT RUN; 24.04: 31 PASS, **3 FAIL (201, 203, 222)**, 2 NOT RUN |
| G78 host part (CHK-M10-280 to -289) | all four cgroup v2 hosts | **PASS** (10/10 on each) |
| VM plants (REQ-262) | hosted 24.04; plant 340 on the cgroup v1 VM | 22/25 red for their own sub-check; 333, 382, 340 not red on a host (reasons in the record; each has its G72 unit red) |

FAIL rows are real host behaviour against TS §3.7, not harness: `/dev/shm` writable and shared with the host (201); a file written to the private `/tmp` or `/var/tmp` executes (203); the cramfs sample answers `absent` under `ProtectKernelModules=yes` on a kernel that ships the module (222, #143). They wait for the owner's decision; no unit, sample or gate was changed.
