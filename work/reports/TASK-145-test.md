# TASK-145 TEST: PASS

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost). REQ-156; #108 (c), (h), (j). Spec: SR §4.2 (SR L277, L285, L287); POSIX XCU §2.3, §2.6.3, §2.7, §2.10; design note D2 and `work/plans/TASK-145.md` §5. Checks CHK-M7-100 to -102 and -112; mutation rows CHK-M7-332 (lexer half) and -387. Test file: `manager/tests/test_bit102_lexer.py`. Implementation: `shlex_model.py`, `shlex_grammar.py`, `shlex_posix.py` under `manager/bitscan_manager/services/importer/` (impl report `work/reports/TASK-145-impl.md`).

C is as in `work/reports/TASK-144-test.md` (Ubuntu 24.04.5 container, 4 cores, CPython 3.12.3, `manager/.venv`, `CI=true`). Unit-only; no PostgreSQL needed. Plants are in the same scratch copy, imported first through `PYTHONPATH`.

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit102_lexer.py` | 173/173 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final) | C | same | 175/175 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit102.py` (BIT102 runs on the lexer) | 1177/1177 passed |
| load | C | full manager suite `pytest -n 8` on 4 cores, 3 times | 8143/8143, 8145/8145, 8147/8147 passed, 0 failed |
| load + 12 CPU burners | C | `pytest -n 8 tests/test_bit_parse.py tests/test_bit102_lexer.py tests/test_bit102.py tests/test_bit_validate.py`, 3 rounds | 2317/2317 passed each round |
| static | C | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean; 276 files |

The load runs used no `CI=true`. With `CI=true` the PostgreSQL fixtures error, because the Docker image build cannot reach the Debian apt hosts (`docker.errors.BuildError` on `apt-get install postgresql-16-debversion`): 6491 passed, 1652 errors, all of them PostgreSQL setup. None of this task's tests use PostgreSQL.

## Test added (tester-owned)

`test_param_and_arith_count_toward_depth_8[param, arith]` (REQ-156 "nesting deeper than 8"). As built, `${…}` and `$((…))` count toward `MAX_DEPTH` like `$( )` (impl report, accepted by the lead), so no form nests without a bound. Plant `L-scan-depth` (that count removed) **survived** the 173 tests as found. The new test checks that 7 wrappers plus a `$( )` lex with `rm` found, and that 8 wrappers plus the `$( )` raise. It also checks 8 plain wrappers pass and 9 raise. The plant is now red (2 failed).

## Acceptance criteria (tasks.md TASK-145, REQ-156)

| Criterion | Check | Result |
| --- | --- | --- |
| A table of at least 60 inputs gives the expected tokens | CHK-M7-100 | PASS: 85-row table (command words and nested scripts at each depth), plus quoting (`echo "rm -rf /"` one `dq` argument; `r''m`, `\rm`, `"r"m` → `rm`), word boundaries, assignments, 15 redirection rows (fd, op, target), the SR §1.1 command, quoted here-document body as data and unquoted body scanned, CRLF `\r` literal, line counts, `for`/`case`/function names as data words, reserved words only in command position |
| Unterminated quotes or substitutions and 9-deep nesting raise the fail-closed error | CHK-M7-101 | PASS: 34 fail-closed inputs (incl. `'`, `"`, `$(`, backtick, `${`, here-document, `)`, `fi`, `if x; then y`, `; rm`, NUL, `$((1)`) raise `ShellSyntaxError` with a line and quote no input; 8 nested `$(`, `<(`, `>(`, backticks accepted, 9 refused; mixed nesting; `depth=` argument; new param/arith depth test |
| Random strings up to 16,384 characters raise nothing else, within 100 ms each | CHK-M7-112 | PASS: 3,000 shell-soup and 1,000 random-text Hypothesis examples, 60 inputs repeated to 16,384 chars, 10 pathological 16,384-char inputs; each under 100 ms of thread CPU time (best of 5 only when the first try is over) |
| The module imports nothing that executes | CHK-M7-102 | PASS: AST of all three files: no `subprocess`, `os`, `shlex`, `re`, `regex`, `pty`, `ctypes`, `multiprocessing`, `importlib`, `runpy`, `code`, `socket`; no `eval`/`exec`/`compile`/`__import__`/`open` calls; no `system`/`popen`/`exec*`/`spawn`; `test_lexer_runs_nothing` with those patched to raise |

## Plants (scratch copy; tests run: `tests/test_bit102_lexer.py tests/test_bit102.py`, 1352 tests, `-n 4`)

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-332 (lexer half) | `lex` returns an empty `Script` on `ShellSyntaxError` and on NUL (fail open) | red, 58 failed (TASK-146's corpus included, as the plan requires) |
| CHK-M7-387 | `$( )`, `<( )`, `>( )` keep no nested script | red, 192 |
| L-backtick | backticks keep no nested script | red, 35 |
| L-heredoc-unscanned | unquoted here-document bodies not scanned | red, 34 |
| L-heredoc-quoted-scanned | quoted bodies scanned as code (over-detection) | red, 6 |
| L-maxdepth9 | `MAX_DEPTH` 9 | red, 10 |
| L-scan-depth | `${…}`/`$((…))` not counted toward depth | red, 2 (survived before the added test) |
| L-scan-noscripts | `${…}`/`$((…))` drop their substitutions' scripts | red, 32 |
| L-sq-unterminated | an unterminated `'` runs to the end | red, 4 |
| L-dq-unterminated | an unterminated `"` accepted | red, 3 |
| L-reserved-anywhere | reserved words recognised outside command position | red, 1 |
| L-forlist-dropped | `for`/`case` list words dropped (substitutions hidden) | red, 6 |
| L-escape-lit | `\x` kept as a literal part (so `\if` is a keyword) | red, 1 |
| L-lines | line numbers off by one | red, 2 |
| L-unbalanced-paren | a stray `)` ignored | red, 3 |
| L-assign-not-kept | assignments treated as command words | red, 11 |
| L-quadratic | `line()` rescans the source in Python per token (super-linear) | red, 8 (best of 5 ≈ 1.95 s against 100 ms). A first form using C-speed `str.count` stayed under the bound; it is not a realistic regression, so the plant was made genuinely super-linear |

**17/17 red** (one after the added test).

## Load-sensitive time bounds (main's known item)

In the user's full `pytest -n 8` run, `test_bit_parse.py::test_35015_elements_is_bit002_bounded` (TASK-141) and `test_bit102_lexer.py::test_pathological_inputs_bounded[seps]` each failed once, and passed alone.

Measurements (C, 4 cores):

| Test | Bound and measure | Idle | 3× oversubscribed (12 burners on 4 cores) |
| --- | --- | --- | --- |
| `test_35015_elements_is_bit002_bounded` | 2.0 s, **wall clock** (`perf_counter`), tracemalloc on | 0.20–0.26 s (15 samples) | 0.20–**1.50 s** (15 samples) |
| `test_pathological_inputs_bounded[seps]` | 100 ms, thread CPU time, best of 5 when the first try is over | 39–56 ms (30 samples) | 39–63 ms (30 samples, 0 over 100 ms) |

Repeated runs: neither test failed in 3 full-suite `-n 8` runs, nor in 3 rounds of the four importer test files under `-n 8` with 12 burners.

Diagnosis:
- **The parse bound is load-sensitive.** It measures wall time, so time spent waiting for a core counts. Under 3× oversubscription one run took 1.5 s, 7.5× its idle time. On a slower machine shared with other agents, more than 2 s is plausible, which explains the failure.
- **The lexer bound is not scheduler-sensitive.** It measures the thread's CPU time and takes the best of 5. Here it never exceeded 63 ms, even single-shot under load. The bound is the REQ-156 (4) acceptance figure (100 ms), so I did not raise it.
- The margin on `seps` is still about 2× (impl report: 52 ms worst on the user's Windows box). The one failure there was likely CPU contention: an SMT sibling or frequency drop lowers per-thread throughput, which CPU time does not hide.

Changes (tester-owned test files; nothing weakened):
1. `manager/tests/test_bit_parse.py` `_measure` (TASK-141's test): the elapsed time is now `time.thread_time()` (this thread's CPU time) instead of `time.perf_counter()`, with the same 2.0 s bound and the same tracemalloc peak. It applies to every `_measure` user (bombs, 5 MiB file, 5 MiB element, 35,015 elements).
   - The parser is single-threaded, so expat and the collector are all counted; only waiting for a core is not.
   - Proof it still catches a slow parser: plant `P-quadratic-collector` (per start tag, Python work proportional to the elements seen so far) is red, `test_35015_elements_is_bit002_bounded` 1 failed.
2. `manager/tests/test_bit102_lexer.py` `_bounded`: diagnostics only. The assertion now reports the five measured times in ms. The bound, the measure and the best-of-5 rule are unchanged. Plant `L-quadratic` is still red.

Recommendation: keep both bounds as they now are. If `seps` fails again on the user's machine, the message now gives the five times. If they are all just over 100 ms with no super-linear growth, the fix is a decision on the REQ-156 (4) figure for loaded developer machines, which is for main and the user. It is not a test change: retrying until green is not allowed. Note for TASK-141: its report should cite this change to `_measure`.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "table or command_words or quoted or escaped or boundaries or assignments or redirections or digits or sr_example or heredoc or crlf or lines or function or reserved"` | PASS | 85-row table and the plan §5 row 1 shapes | 2026-10-27 |
| CHK-M7-101 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "fail_closed or unlexable or depth or nested or mixed"` | PASS | 34 inputs raise with a line; 8 accepted, 9 refused for `$(`, `<(`, `>(`, backticks, `${`, `$((` | 2026-10-27 |
| CHK-M7-102 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "imports_nothing or runs_nothing"` | PASS | AST clean in 3 files | 2026-10-27 |
| CHK-M7-112 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "random or long_inputs or pathological"` | PASS | 4,060 generated + 10 pathological inputs, each < 100 ms CPU | 2026-10-27 |
| CHK-M7-332 | CODE | C | plant: lexer errors swallowed (empty `Script`) | PASS (red) | 58 failed incl. the TASK-146 corpus | 2026-10-27 |
| CHK-M7-387 | CODE | C | plant: `$( )` recursion dropped | PASS (red) | 192 failed | 2026-10-27 |
| CHK-M7-145-extra | CODE | C | 15 further plants (table above) | PASS (red) | 15/15 red | 2026-10-27 |
| CHK-M7-112-load | CODE | C | 3 × full suite `-n 8`; 3 × importer files `-n 8` + 12 burners | PASS | both named tests green every time; measurements above | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 175/175 passed, 0 failed, 0 errors, 0 skipped. Plants: 17/17 red. Changed: `test_bit102_lexer.py` (added test; bound message) and `test_bit_parse.py` (`_measure` uses CPU time).

---

# TASK-145 TEST (revision 1 and 1b): PASS

Tester: tester-m7d, 2026-10-27. Code under test: `0529083` (r1 at `8173527`, plus r1b, which makes the function-definition removal linear). Impl report: `work/reports/TASK-145-impl.md` "Revision 1" and "Revision 1b". Review being answered: `work/reviews/TASK-145.md` findings 1 (blocking), 2 (should-fix) and 3 (nit). Spec: SR §4.2 L277 and L287; TS §3.3 L249 (`/bin/sh -c` is dash); POSIX XCU §2.7.4; REQ-156 (4).

Environment C: cloud container, Ubuntu 24.04, 4 cores, `manager/.venv`, dash 0.5.12-6ubuntu5, bash 5.2.21. Unit-only; no PostgreSQL. Plants were made in the scratch copy `scratchpad/mut`, which was refreshed from the working tree. A control run first proved that the copy is the code imported: a marker planted in the copy raised on import through `PYTHONPATH`.

## Runs

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| as found (r1, before my rows) | `pytest -q -p no:cacheprovider -n 4` on the six files | 2548/2548 passed |
| r1 + my rows | `pytest -q tests/test_bit102_lexer.py -k pathological` | 10/14 passed, **4 failed** (`fndefs*`, see the finding below) |
| re-run, failing rows only, after r1b | the 4 node ids `test_pathological_inputs_bounded[fndefs]`, `[fndefs-nl]`, `[fndefs-true]` and `[fndefs-hypothesis]` | 4/4 passed |
| final (`0529083`) | `pytest -q -p no:cacheprovider tests/test_bit102_lexer.py` | 230/230 passed, 0 failed, 0 errors, 0 skipped |
| final, six files, 3 runs | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` | 2981/2981 passed, 3 times |
| static (repo root) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 278 files |

## Finding (product, fixed in r1b): the lexer was quadratic on function definitions (REQ-156 (4))

- **How it was found.** Hypothesis found it in `test_long_inputs_up_to_16384_chars`, with `unit='{{\nrm()'` repeated to 16 KB. The example was stored in the scratch copy's `.hypothesis` database, and from then on the test failed every run there.
- **Cause.** `cmds.remove(cur)` in the `NAME ( )` branch of `shlex_grammar.py` ran the dataclass `__eq__` against every earlier command. cProfile: 2.74 M `__eq__` calls, 0.58 s of 0.68 s.
- **Timings before the fix**, `lex()`, best-of-3 thread CPU time, at 4 K / 8 K / 16 K chars:
  - `x;f(){ :;};`: 53 / 200 / **774 ms**;
  - `a\nf()\n:\n`: 37 / 134 / 533 ms;
  - `true\nf() { :; }\n`: 13 / 41 / 140 ms;
  - `{{\nrm()`: 24 / 87 / 326 ms.

  `150bcd3` timed the same, so this predates r1. The r0 PASS was a test gap: no fixed input had many function definitions.
- **After r1b**, `cmds.pop()` behind an identity check that raises (fail closed): 34 ms and 26 ms at 16 K for the first and last forms.
- **Pins.** Four fixed rows were added to `test_pathological_inputs_bounded`. They make the bound deterministic, without relying on Hypothesis finding the input again.

## Tests added (tester-owned; nothing weakened)

- `bits/tests/bit102/must_reject.json` gets 38 TASK-145 rows, `rule` starting `145r1`:
  - the 10 review here-document forms, each with `rm -rf /x` and with `rm x`;
  - two levels (`$(echo $(⏎…))`), a backtick inside `$( )`, two here-documents, `<<-`, and a flock `-c` script;
  - a substitution on the here-document line with no newline inside it;
  - `coproc rm x` and 9 `bash -c 'coproc …'` forms;
  - the nit `>/etc/x f() { :; }`, and `f() { :; } >/etc/x; f`.
- `must_pass.json` gets the 6 forms the shells read normally: `cat <<E $(date)` (the old false positive), `x=$(cat <<E⏎body⏎E⏎)`, `cat <<E⏎$(⏎date⏎)⏎E`, backticks in a body, `( cat <<E )`, and a quoted body inside `{ }`. It also gets `bash -c 'coproc cat /etc/x'`, `coproc NAME { … }` and `f() { cat /x; }; f`.
- `manager/tests/test_bit102_lexer.py`:
  - `test_heredoc_pending_across_a_substitution_newline_fails_closed` (13), which asserts the exact reason;
  - `test_heredoc_forms_the_shells_read_normally` (7);
  - `test_coproc_command_words` (10) and `test_coproc_name_is_a_data_word_and_assignment_kept`;
  - `test_redirection_before_a_function_definition_fails_closed`;
  - the 4 `fndefs` rows in `test_pathological_inputs_bounded`;
  - `test_time_keyword_or_command` (6) and `test_prompt_and_escape_transforms_fail_closed` / `test_quoted_or_other_transforms_lex`, which are for TASK-146 r2 but live in the lexer file.

## Real-shell confirmation (scratch `sh146/shellprobe.py`; `rm` replaced by `echo RAN`, run in a fresh temp dir under the scratchpad)

| Rows | Result |
| --- | --- |
| Here-document forms (`$( )`, `<<E`, `"$( )"`, `; echo $( )`, `${x:-$( )}`, backticks, two levels, backtick in `$( )`, two here-documents, `<<-`, flock `-c`) | dash runs the inner line (prints RAN, then `E: not found`) in every form |
| `<( )`, `>( )` | bash runs it; dash has no process substitution |
| `$(($( ⏎…)))` | dash runs it; RAN shown on stderr (stdout is used up by the arithmetic) |
| `x=$(cat <<'E' $(⏎…⏎E⏎)⏎)` | dash and bash give a syntax error and nothing runs; the refusal is fail closed |
| coproc: 9 `bash -c` forms, and `coproc rm x` under bash | bash runs the command (RAN on stderr). dash has no coproc keyword, so the top-level row is over-detection, which is allowed |
| `>/etc/x f() { :; }` | dash: `Syntax error: "(" unexpected`; nothing runs |
| `f() { :; } >FILE; f` | dash creates FILE |

## Plants (scratch copy; tests `tests/test_bit102.py tests/test_bit102_lexer.py`, `-n 4`)

| Plant | Change | Result |
| --- | --- | --- |
| L1-heredoc-depth | the depth test removed from the newline check (`if self.outer:`) | red, 34 |
| L1-backtick-outer | backticks no longer get `outer=` | red, 6 |
| L1-coproc-reserved | `coproc` not reserved | red, 21 |
| L1-coproc-name-dropped | `coproc NAME` not kept as a data word | red, 1 |
| L1-fn-redirect-dropped | the raise for a redirection before `NAME ( )` removed | red, 2 |
| L1-close-paren-any-pending | the r0 `)` rule (any pending here-document) | red, 4 (incl. must-pass `cat <<E $(date)`) |
| L1b-fndef-remove-by-eq | `cmds.remove(cur)` back (quadratic) | red, 5 (the 4 `fndefs` rows and `test_long_inputs`) |

**7/7 red.**
- The grammar plants were re-run on `0529083`.
- The two shlex_posix plants were run on `8173527`; r1b does not touch that file.
- In the first plant pass, `test_long_inputs_up_to_16384_chars` also failed, because of the stored quadratic example described above. Every plant also had a red test of its own, and the counts above leave that extra failure out.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "heredoc_forms or coproc or time_keyword or transforms_lex"` | PASS | 7 + 11 + 6 + 5 rows | 2026-10-27 |
| CHK-M7-101 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "across_a_substitution or redirection_before or transforms_fail_closed"` | PASS | 13 + 1 + 8 raise the fail-closed error | 2026-10-27 |
| CHK-M7-112 | CODE | C | `pytest -q tests/test_bit102_lexer.py -k "pathological or long_inputs or random"` | PASS after r1b (FAIL at r1) | 4 `fndefs` rows: 774/533/140/326 ms → < 50 ms | 2026-10-27 |
| CHK-M7-115 (145 rows) | CODE | C | `pytest -q tests/test_bit102.py -k must_reject` | PASS | 38 rows `145r1`, each with its token; real-shell: dash/bash run each hidden command (table above) | 2026-10-27 |
| CHK-M7-145-r1-plants | CODE | C | `python plant2.py plants_r2_grammar.json` and the full `plants_r2.json` | PASS (red) | 7/7 | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 278 files | 2026-10-27 |

Verdict: **PASS** (r1b). 230/230 passed in the lexer file; 2981/2981 passed across the six files, 3 times; 0 failed, 0 errors, 0 skipped. Plants: 7/7 red. Revision 1 alone was **FAIL** on REQ-156 (4); r1b fixes it.
