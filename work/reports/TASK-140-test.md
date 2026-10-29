# TASK-140 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-152, REQ-155; SR §2, §3.3, §3.5, §4, §4.1; #57, #105 (g). Checks CHK-M7-010 to -014, plants CHK-M7-385, -386 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit_model.py` (expected values read from the SR §4.1 table and the TS §5.2 DDL text by the test, not copied from the code).

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W (WSL 24.04, `CI=true`, label m7t-u1, `-n 0`) | `pytest -q tests/test_bit_model.py` (with the TP-M7-01 and TASK-139 files) | 71/71 passed (whole run 437/437), 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 248 files |
| plant 385a | W, throwaway copy | `BIT006` added to `Code` | red: 2 failed |
| plant 385b | W, throwaway copy | BIT101 made Reject | red: 2 failed |
| plant 386 | W, throwaway copy | `PolicyName` limit (1, 129) | red: 2 failed |

## Acceptance criteria

| Criterion (tasks.md TASK-140) | Check | Result |
| --- | --- | --- |
| every SR §4.1 code has its SR severity | CHK-M7-010 | PASS: 18 codes = SR table; only BIT101 and BIT103 Warn |
| BIT006, BIT009 and BIT018–BIT020 absent | CHK-M7-010 | PASS: refused by `Code` and `Finding` |
| each limit equals its SR §2 value | CHK-M7-011 | PASS: lengths, 5,242,880 bytes, 1–5,000 plugins, timeout 1/600/60, control_ref 32, 14 operators in DDL enum order |
| `Finding` serialises to exactly `{line, element, code, message}` | CHK-M7-012 | PASS: also `quote` (64 chars, C0, DEL and backslash escaped) and `plugin_path` (#105 (g)) |
| frozen dataclasses, `mypy --strict` | CHK-M7-013, -014 | PASS |

Not in this task: the #105 (a) element, depth and attribute caps (35,014 / 16 / 8) are not model constants. They are checked against TASK-141's parser (CHK-M7-026).

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-001..006 | CODE | W | `pytest -q -n 0 tests/test_bit_fixtures.py` (m7t-u1) | PASS | 227/227 passed (TP-M7-01 fixtures: manifest complete, one fixture per code, BIT001 set, SR §1.1 byte-identical, corpora, hostile names, hashes, no CR) | 2026-10-27 |
| CHK-M7-010..013 | CODE | W | `pytest -q -n 0 tests/test_bit_model.py` (m7t-u1) | PASS | 71/71 passed | 2026-10-27 |
| CHK-M7-014 | CODE | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | PASS | clean; 248 files | 2026-10-27 |
| CHK-M7-385 | CODE | W | plants (a) BIT006 added, (b) BIT101 Reject; `pytest tests/test_bit_model.py` | PASS (red) | (a) 2 failed, (b) 2 failed | 2026-10-27 |
| CHK-M7-386 | CODE | W | plant PolicyName (1, 129) | PASS (red) | 2 failed | 2026-10-27 |
