# TASK-210 REVIEW: redaction engine (`internal/redact`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-242, REQ-243 (fixtures: tester), REQ-244 (package level). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-210-impl.md`: `agent/internal/redact/redact.go` (sha256 `a7e12392…`), `cutoff.go` (`9b449920…`) and `patterns.go` (`c5ae62c2…`), all new. 161 code lines in 3 files, inside the estimate.

TEST: PASS (`work/reports/TASK-210-test.md`):
- 78/78 on Windows and on WSL with `-race`;
- the Go/`google-re2` cross-check 45/45 on the shared corpus;
- `FuzzApply` and `FuzzCompile` clean;
- 12/12 plants red (CHK-M10-344, -345, -347 to -354, plus two extras).

Spec read: TS §3.5 L251, §8.1 L1249, §8.3 L1275, §8.6 L1324, L1329–L1339; #57, #113, #116 (a), #121, #133, #134; plan TASK-210 §2–§3.

My re-run (Windows): `go test -count=1 ./internal/redact/` ok (39 s). `gofmt -l` is empty, and `golangci-lint run` gives 0 issues on Windows and with `GOOS=linux`. `pytest tests/test_redaction_crosscheck.py` gives 45 passed, run with the main checkout's venv against this worktree, writing no bytecode or cache. The hashes match the test report.

## Checks
1. **Redact before truncate (TS §3.5 L251; security invariant "Secrets and output").** `Apply` runs four steps in order:
   - it sanitises the whole kept buffer (≤ 1 MiB);
   - it runs every pattern over it in list order;
   - it applies the cut-off rule;
   - only then does it cut to the cap, at a rune boundary.

   A token starting at 65,530 and at four other offsets around the cap leaves no prefix (CHK-M10-020). Plant 344 (cut first) is red, along with the 564-case property test and the fuzz.
2. **Literal replacement, list order, no expansion (TS §8.6 L1329).** The `ReplaceAllFunc` callback returns the fixed marker bytes, so `$1` and `${1}` stay literal (CHK-M10-017, plant 350 red).
3. **Cut-off rule always applies (#133).** It runs whatever the list holds, including `[]` and the defaults minus pattern 2. It runs on the kept buffer, so a key cut by the 1 MiB read is caught (CHK-M10-019). Its markers equal pattern 2's markers byte for byte (`[A-Z0-9 ]*PRIVATE KEY`). Searching from one byte after the last END start catches END glued to BEGIN (plant 210b red).
4. **Fail-closed pattern list (REQ-244, #134 (e)).** `Compile` refuses the whole list on a 51st entry, a Go compile error, or a nullable entry. The nullable walk on the simplified tree treats assertions as nullable, so `\b`, `^`, `(?m)^$` and `\b\B` are refused, while `^a`, `\bx` and `x\b` are accepted (CHK-M10-012/-013). Plants 351–353 are red.
5. **Same matches as the manager (REQ-243 (3)).** The five defaults are read from TS §8.6 at test time. They equal the M9 seeded default and migration m0005 byte for byte, and give identical spans in Go and `google-re2` on 44 corpus inputs, `(?i)` folding of `ſ`/`K`, `\b` after `é`, NUL, CRLF and U+FFFD included.
6. **Caps and UTF-8 (#116 (a), #113, #134 (c), (g)).** Every output is valid UTF-8 and at most the cap in bytes. stderr is never `truncated`. `Overflow` sets stdout `truncated` even when redaction shrinks the text (plants 347–349 red).
7. **Memory under `MemoryMax=256M` (#134 (f), (h)).** The running-size guard bounds each pass to the input plus 4 MiB. The measured peak heap for a guarded 1 MiB `Apply` is about 11 MB. Nothing in the package logs, and it is pure Go with no platform file.

## The implementer's own choices (lead's list)
- **(1) `PatternError.Error()` never holds the pattern.** Accepted. It's hardening in line with builder checklist 11/12. The Go error, which quotes the pattern, is reachable only through `Unwrap`. Callers log the index only.
- **(2) The growth guard trips on the running size.** Accepted, and not a spec change. The guard itself is the #134 (f) product choice. Tripping on the projected size, rather than after a full `ReplaceAllLiteral`, is stricter (it fails closed earlier on contrived input) and avoids a large intermediate under the 256 MiB unit cap. The exact-4 MiB and 4 MiB + 1 boundary rows pin it.

## NOT RUN rows and cover
- **CHK-M10-344, G79 half** (a canary on a real host must reach the manager as `[REDACTED]`): NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover, adequate for the redaction logic:**
  - the plant is red at unit level in G71 (`TestSecretAtTheCap`, `TestPropertySecretsNeverLeak`);
  - the fuzz;
  - TASK-214's `Build` path, which runs `Apply` on captured streams.
- **Unproven on a real host:** the whole chain from plugin to stored result. That is the runner capturing a real plugin's pipes, redacting, framing, the agent spooling and posting, and M9 storing the redacted text. The unit tests prove the function; only G79 proves the redacted text is the one that leaves the host.

## Findings
None blocking or should-fix.

1. nit, `redact.go:48-54`: a secret that straddles the **1 MiB read limit** (not the cap) is cut by the read, and its kept prefix may no longer match its pattern. For example, `bsa_` plus 19 characters fails `{20,}`. Normally that prefix lies far past the 64 KiB cap and is cut away. It can only reach the output if earlier redaction shrinks about 1 MiB to under 64 KiB, for example a ~1 MiB complete PEM block (pattern 2) followed by the token. That's contrived, and the read limit is TS §3.5's own design. Consider, when `Overflow` is set, dropping the bytes after the last LF of the kept buffer before matching, then adding one marker. Otherwise, record it as a spec-internal note beside #133.
