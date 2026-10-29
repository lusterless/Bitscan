# TASK-145 TEST: PASS

Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-156. Spec: SR §4.2 ("split into tokens with a POSIX sh lexer"), TS §8.1 (L1244, L1255), §8.3 (the BIT102 lexer unit row); answer #108 (c), (h), (j); design note D2 and `work/plans/TASK-145.md` §5. Token expectations from POSIX XCU §2.3, §2.6.3, §2.7, §2.10. Checks CHK-M7-100, -101, -102, -112; plants CHK-M7-332 (lexer half) and -387 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit102_lexer.py`. Implementation: one task in three files (user ruling 2026-10-27), `shlex_model.py`, `shlex_grammar.py`, `shlex_posix.py` in `manager/bitscan_manager/services/importer/` (impl report `work/reports/TASK-145-impl.md`).

## Runs

Code under test: `git archive 25d41ec` of `manager`, `bits`, `docs` in `/root/bstest-m7b-head` (no product change in the worktree; the old copy differs only in CR LF).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit102_lexer.py` | 173/173 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `tests/test_bit102.py` (the only consumer, through `bit102.py`); `test_bit_fixtures.py`, `test_bit_model.py`, `test_module_imports.py` | 1160/1160, 227/227, 71/71, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W and L are as in `work/reports/TASK-144-test.md` (WSL2 Ubuntu 24.04.5, CPython 3.12.3, venv `/root/venv-m7b`, `CI=true`; Windows for static gates only).

## Acceptance criteria (tasks.md TASK-145)

| Criterion | Check | Result |
| --- | --- | --- |
| The REQ-156 (1) table of at least 60 inputs gives the expected tokens | CHK-M7-100 | PASS: 85 table rows (guard: at least 60) give the expected command words, including `echo "rm -rf /"` (one quoted argument), `r''m`, `\rm`, `"r"m` and `r\<newline>m` (the word `rm`), `a;rm`, `a&&rm`, `$(rm x)`, `` `rm x` ``, `<(cat /etc/x)`, `cat <<'EOF'` with a body (data), `cat <<EOF` with `$(id)` in the body (found), `${x:-$(rm y)}` in a here-document (found), `# rm` (comment), `a#b` (a word). Separate tests: 14 redirection rows with descriptor and target (`2>/dev/null`, `>|`, `>>`, `&>`, `2>&1`, `<`, `<>`), assignments before the command, reserved words only in command position (a quoted `"if"` is a word), function names and `for` lists are data, escapes inside double quotes, CR kept literal, line numbers counted |
| Unterminated quotes or substitutions and 9-deep nesting raise the fail-closed error; 8 deep accepted | CHK-M7-101 | PASS: 34 unlexable inputs (unterminated `'`, `"`, `$(`, backtick, `${`, here-document without its end, `)` or `fi` alone, `if x; then y`, `; rm`, NUL, …) raise `ShellSyntaxError` with a line and without quoting the input; 8 nested `$(`, backticks and mixed nesting accepted, 9 refused; `MAX_DEPTH` is 8 and the `depth=` argument counts toward it |
| The module imports nothing that executes | CHK-M7-102 | PASS: AST scan of all three files bans `subprocess`, `os`, `shlex`, `re`, `regex`, `pty`, `ctypes`, `multiprocessing`, `importlib`, `runpy`, `code`, `socket` calls to `eval`/`exec`/`compile`/`__import__`/`open` and the attributes `system`, `popen`, `execv`, `execve`, `spawn`; with `subprocess.Popen` and `os.system` patched to fail, lexing `$(rm -rf /) \`id\` <(cat /etc/shadow) ${x:-$(reboot)}` runs nothing |
| Random strings up to 16,384 characters raise nothing else and finish within 100 ms each | CHK-M7-112 | PASS: Hypothesis, 3,000 shell-piece inputs and 1,000 random texts up to 2,000 characters, 60 repeated units cut to exactly 16,384 characters, plus 10 pathological inputs at the limit (`a;` × 8,192, 2,700 here-document substitutions, 8,000-term arithmetic, …): only `ShellSyntaxError`, each under 100 ms of thread CPU time. The bound helper measures once and, only if that exceeds 100 ms, takes the best of 5, so a GC pause from the test process can't fail it while a super-linear lexer still does |

Over-detection (`[[ ]]`, `(( ))`, `$((`, `time` treated toward rejecting) is accepted by the user's ruling of 2026-10-27 and isn't flagged.

## Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first, asserted; definitions `%TEMP%\m7b-plants\plants_145_146.json`; each run against `test_bit102_lexer.py` and `test_bit102.py`)

Control copy (`CTRL-145-146`, no-op): ruff clean; both files green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-387 | `$(` recursion dropped (a substitution's script not lexed) | `test_heredoc_quoted_body_is_data_unquoted_is_scanned`; `test_must_reject[echo $(rm x)]`, `[bash -c "$(curl x)"]` |
| CHK-M7-332 (lexer) | `lex` returns an empty script on `ShellSyntaxError` (fail open) | `test_nested_shell_scripts_past_depth_8_fail_closed`, the unlexable rows |
| P145-backtick | backtick script not lexed | `test_8_nested_backticks_accepted_9_refused`; `` echo `rm x` ``, ``sh -c '`id`'`` |
| P145-heredoc-unscanned | unquoted here-document bodies not scanned | `test_heredoc_quoted_body_is_data_unquoted_is_scanned`; `cat <<EOF $(rm -f /etc/x)`, `<<-EOF` |
| P145-heredoc-quoted-scanned | quoted here-document bodies scanned as code | `test_must_pass[cat <<'EOF' … $(rm -rf /)]`, the `<<'EOF'` table row |
| P145-depth9 | `MAX_DEPTH` 9 | `test_max_depth_is_8`, `test_depth_argument_counts`, `test_8_nested_substitutions_accepted_9_refused` |
| P145-dq-noexpand | `$` and backtick inside double quotes not expanded | here-document and `"$(…)"` rows |
| P145-escape-literal | `\x` kept as the two characters | `test_reserved_words_only_in_command_position`; `test_must_reject[\rm x]` |
| P145-reserved-quoted | quoted words taken as reserved words | `test_command_words["if" x]`, `test_reserved_words_only_in_command_position` |
| P145-no-assignments | leading `NAME=value` taken as the command word | `FOO=1 rm x`, `A=1 B=2 rm x` |
| P145-linecont | backslash-newline not removed | `test_command_words[r\<newline>m x]` |
| P145-sq-failopen | unterminated `'` read to the end | `test_fail_closed_error_quotes_no_input`, `test_unlexable_input_…[echo 'abc]`, `test_fail_closed_error_has_the_line` |
| P145-heredoc-eof-open | here-document without its end accepted | `test_unlexable_input_raises_the_fail_closed_error[cat <<EOF]` |
| P145-procsub-dropped | `<( )`/`>( )` kept as a literal | `test_command_words[cat < <(rm x)]`; `cat <(rm x)`, `cat >(rm x)`, `dash -c 'cat <(id)'` |
| P145-param-script | `${…}` scripts dropped | `test_command_words[cat <<EOF ${x:-$(rm y)} EOF]`; every `${x:-$(…)}` context row |

All 15 plants are red; the control is green.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-100 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "command_words or table_has or quoted_argument or escaped_and_split or word_boundaries or redirections or assignments or heredoc or reserved or function_names or escapes_inside or digits_not or crlf or lines_are or sr_example"` | PASS | 114/114; 85-row table | 2026-10-28 |
| CHK-M7-101 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "unlexable_input or nested_substitutions or nested_backticks or mixed_nesting or max_depth or depth_argument or fail_closed_error"` | PASS | 45/45; 8 deep accepted, 9 refused | 2026-10-28 |
| CHK-M7-102 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "import_nothing or runs_nothing"` | PASS | 4/4; AST scan of 3 files, nothing executed | 2026-10-28 |
| CHK-M7-112 | CODE | W | `pytest -q tests/test_bit102_lexer.py -k "random or long_inputs or pathological"` | PASS | 14/14; only `ShellSyntaxError`, each < 100 ms, up to 16,384 chars | 2026-10-28 |
| CHK-M7-315 (TASK-145 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-332 (lexer) | CODE | W | plant: `lex` fails open | PASS (red) | depth and unlexable rows failed | 2026-10-28 |
| CHK-M7-387 | CODE | W | plant: `$(` recursion dropped | PASS (red) | lexer here-document row and `$(…)` must-reject rows failed | 2026-10-28 |

## Measurement fix at the M7 gate (tester-m7, 2026-10-28; lead ruling, option (b))

At the M7 gate, `test_pathological_inputs_bounded[seps]` (`"a;" * 8192`) failed against the 100 ms bound (REQ-156 (4)) with 0.103 s, best of five thread-CPU timings, in the G54 batch and again alone. The lexer modules are unchanged since the run above.

**Cause.**
- Inside a pytest test, `sys.gettrace()` and `sys.getprofile()` are None, `sys.monitoring` has no tool registered, and `sys.flags` show no debug or dev mode. No tracer is involved.
- The identical loop measured 55–59 ms inside pytest in one run and 103.5 ms in another, against 56 ms in a plain script. Thread CPU time still scales with core speed and contention on this shared WSL machine (other agents' containers and builds), so the in-process best-of-five has no headroom at 16,384 characters.

**The change (a measurement fix; the 100 ms bound is unchanged).**
- `test_pathological_inputs_bounded` (all ten parameters) still lexes in process for the functional assertions: the right `Script`, or only `ShellSyntaxError`.
- It now times the lexer in a clean `python -I` subprocess of the same venv, importing the tree under test, with no tracer and no test-process heap. It takes the best of 10 thread-CPU timings there and asserts < 100 ms.
- The property tests keep their in-process `_bounded`.

**Evidence.**
- `tests/test_bit102_lexer.py`: **173/173 passed** (W, gate copy).
- A quadratic plant (`len(list(src[:pos]))` per token in `shlex_posix`) → red, 6 of 10 parameters fail under the subprocess timing (`seps`, `args`, `nest8`, `heredoc`, `parens`, `ifs`).
