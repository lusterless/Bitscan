# TASK-210 TEST: PASS

Tester: tester-m10, 2026-10-30. Full rigor (redaction, TS §8.2 second approval). REQ-242, REQ-243, REQ-244 (package level); TS §3.5 L251, §8.1 L1249, §8.3 L1275, §8.6 L1324, L1329–L1339; #57, #113, #116 (a), #121, #133, #134.

Code under test (impl-agent-m10, `work/reports/TASK-210-impl.md`): `agent/internal/redact/redact.go` (sha256 `a7e12392dbbca58d…`), `cutoff.go` (`9b44992050a919a0…`), `patterns.go` (`c5ae62c2d8a6da2e…`).

Test files (new):
- `agent/internal/redact/redact_test.go` (`0627cdcda5d07922…`)
- `agent/internal/redact/fuzz_test.go` (`c420fd81eef4c817…`)
- `manager/tests/test_redaction_crosscheck.py` (`08e1b51539d1876f…`)
- the shared corpus `manager/tests/contract/fixtures/redaction/corpus.json` (`0b79cdd33986ea45…`, 44 cases)

Plan rows: CHK-M10-011 to -024, -080, -081, -083 (`tests/m10/test-plan.md`), and mutation rows CHK-M10-344, -345, -347 to -354.

The five default patterns are read from TS §8.6 at test time, by both Go and Python; they are never copied. The corpus's expected matches were written by hand from the pattern text, and the byte spans are derived by sequential search, not by an engine.

## Runs

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

## Report rows (for tests/m10/report.md)

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

## Acceptance (TASK-210: "REQ-242 (1)–(8) and REQ-244 (1), (2) hold at package level, and the REQ-243 fixtures pass with the five patterns extracted from TS §8.6")

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
