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
