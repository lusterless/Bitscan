# TASK-001 IMPL report: manager project config and hashed lock files

REQs: REQ-001 to REQ-005. Spec: TS §2.1 (stack), TS §8.1 "Install and supply chain" (hashed Python dependencies), TS §8.2 (Python standards, `pip --require-hashes`), TS §8.3 (85 % on services), TS §4.1 (defusedxml), TS §4.5 (RE2).

## Files

- `manager/pyproject.toml` (hand-written, 66 lines)
- `manager/requirements.txt` (generated, runtime lock: 15 packages + `tzdata` on win32)
- `manager/requirements-dev.txt` (generated, dev superset: 46 packages + `colorama`, `pywin32`, `tzdata` on win32)
- `manager/.venv` (dev venv, gitignored; created with `uv venv --python 3.12 manager/.venv`, filled from the dev lock)

**Revision 1 (during TASK-002):** added `editables>=0.5` to the `dev` extra and regenerated both locks with the same command. Hatchling's editable build (`pip install --no-deps --no-build-isolation -e manager`) fails with `bitscan-manager = ["editables"]` when it is missing, and it is part of the build backend (plan step 3). `requirements.txt` is byte-identical. `requirements-dev.txt` gains only `editables==0.6` with its hashes. I reran a fresh `python -m venv` install of the dev lock: exit 0. The mutation checks below target `annotated-doc`, which did not change.

**Revision 2 (after TEST PASS, CHK-M0-012 follow-up):** regenerating without a cutoff picks up newer releases (fastapi 0.148.0 to 0.149.0, uploaded 2026-10-19T17:22Z). Both locks are now regenerated with `--exclude-newer 2026-10-19T16:56:37Z`, the write time (UTC) of the existing locks. `diff` against the previous files shows only header line 2 changed in each file; every pin and hash is identical. Rerun after the change: a second regeneration in a temp dir is byte-identical to the committed locks. Fresh `python -m venv` installs of both locks exit 0 with 0 builds. The altered-hash, removed-hash and unpinned-line copies exit 1 for both locks. The imports work (fastapi 0.148.0, pydantic 2.14.1).

**Revision 3 (reviewer nit 2, after REVIEW APPROVED):** `pyproject.toml` only, with the locks untouched: added `xmlrpc` and `plistlib` to `banned-api`, with the same message. Both parse XML with expat; TS §4.1 allows defusedxml only. To check it, I made a throwaway copy with planted `import plistlib`, `import xmlrpc.client`, `import xmlrpc.server` and `from xmlrpc import client`, in both `bitscan_manager/` and `tests/`. Every one was flagged TID251 and ruff exited 1. `import defusedxml.ElementTree` and `import defusedxml.xmlrpc` in the same file were not flagged. Clean tree: `ruff check manager/bitscan_manager` passes and `ruff format --check manager` passes. `ruff check manager` currently fails only on S603 in the tester's new `tests/test_cli.py` (lines 79, 89) and `tests/test_openapi.py` (line 56); that is unrelated to this change.

## What `pyproject.toml` holds

- `[build-system]` hatchling. `[project]` `bitscan-manager` 0.1.0, `requires-python = ">=3.12,<3.13"`. Runtime deps: fastapi, pydantic>=2.9,<3, apscheduler>=3.10,<4, defusedxml, google-re2. Extra `dev`: pytest, pytest-cov, ruff, mypy, types-defusedxml, testcontainers, psycopg[binary] (psycopg 3), httpx, hatchling and editables (the build backend, for `--no-build-isolation`). Script `bitscan-manager = "bitscan_manager.cli:main"` (target arrives in TASK-002).
- `[tool.ruff]` py312; lint select E, W, F, I, B, UP, S, TID; `tests/**` ignores S101 only. `banned-api`: `xml.etree`, `xml.dom`, `xml.sax`, `xml.parsers.expat`, `lxml`, `xmlrpc`, `plistlib` (defusedxml only) and `re` (PD-14 (g), RE2 only).
- `[tool.mypy]` strict, python 3.12, `pydantic.mypy` plugin. `[tool.pytest.ini_options]` `testpaths = ["tests"]`, marker `pg`; no `--cov-fail-under` in addopts. `[tool.coverage.run]` `source = ["bitscan_manager/services"]`, `branch = false`; `[tool.coverage.report]` `fail_under = 85`, `show_missing = true`.

## Lock generation (exact commands, run from `manager/`, also in each file's header)

```
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 pyproject.toml -o requirements.txt
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 --extra dev pyproject.toml -o requirements-dev.txt
```

- `--exclude-newer`: makes regeneration reproducible. To upgrade a dependency on purpose, move the timestamp forward in both commands and regenerate both files.

- `--system-certs`: this network intercepts TLS with a CA that is only in the Windows trust store. uv's bundled roots reject it. The flag keeps verification on against the OS store and does not change the output. CI can drop it.
- **Added to the decided PD-13 command: `--only-binary :all: --emit-build-options`.** Reason: uv lists the sdist hash next to the wheel hashes. With the first lock, altering a wheel hash still exited 0, because pip fell back to the hash-matching sdist and built it ("Building wheel for annotated-doc"). That build runs in an isolated environment that downloads the build backend **without** hash checks, which is a hole in TS §8.1 "hashed Python dependencies". `--emit-build-options` writes the line `--only-binary :all:` into each lock. Plain `pip install --require-hashes -r <lock>` now installs wheels only and never builds anything. Every locked package has wheels for Windows amd64 and Linux x86_64/aarch64.
- google-re2 1.1.20251105 has CPython 3.12 wheels for win_amd64, manylinux_2_28 x86_64 and manylinux_2_28 aarch64, so PD-14 (j) holds.

## Checks run (Windows 11, CPython 3.12.10, fresh `python -m venv` with its bundled pip 25.0.1, nothing upgraded)

| Check | Result |
| --- | --- |
| `pip install --require-hashes -r requirements.txt` | exit 0, 0 sdist builds |
| `pip install --require-hashes -r requirements-dev.txt` | exit 0, 0 sdist builds |
| Temp copy, first `--hash` digest altered by one character (the installed `annotated-doc` wheel), both locks | exit 1, "THESE PACKAGES DO NOT MATCH THE HASHES" |
| Temp copy, all hashes of `annotated-doc` removed, both locks | exit 1, "Hashes are required in --require-hashes mode" |
| Temp copy, unpinned line `six` appended, both locks | exit 1, "must have their versions pinned with ==" |
| `import fastapi, pydantic, apscheduler, defusedxml, re2` (runtime venv) | ok; pydantic 2.14.1, APScheduler 3.11.3 |
| `requires-python` with `packaging.specifiers` | 3.12.10 in, 3.11.9 out, 3.13.0 out |
| Runtime lock contains pytest/ruff/mypy/testcontainers | no |
| Planted copy: `ruff check` | TID251 for `re`, `xml.etree.ElementTree`, `from xml.dom import minidom`, `xml.sax`, `xml.parsers.expat`, `lxml.etree`; S608 for f-string `execute`; F401; `defusedxml.ElementTree` not banned |
| Planted copy: `mypy --strict --config-file manager/pyproject.toml manager` (from root) | no-untyped-def in `bitscan_manager/` and in `tests/`; config is read |
| Real tree: mypy and ruff skip `manager/.venv` | yes (mypy "checked 2 source files" = the tester's tests) |
| Linux proxy: `uv pip install --require-hashes --python-platform {x86_64,aarch64}-manylinux_2_28 --python-version 3.12 --target <tmp> -r <lock>` | all four exit 0, Linux `.so` files for `re2` and `pydantic_core`, no `pywin32` or `colorama` |

**Real Linux `pip install --require-hashes`: NOT RUN locally (no Docker, no WSL).** The uv cross-platform install above is a proxy. The real check runs in CI (TASK-009).

## For the tester

- Each lock now starts with an option line `--only-binary :all:` (after the header comments). It is a pip option, not a requirement. `tests/test_lock_files.py::parse` treats it as a requirement and fails 7 tests ("not pinned with ==: '--only-binary :all:'"). Please skip lines starting with `--` that are not `--hash=`. The 12 other tests pass.
- Altering or removing one hash: pip accepts any listed hash, so changing the hash of an artifact this platform does not use (another OS's wheel, or the sdist hash, which uv still lists) correctly exits 0. To prove the gate, alter the hash of the wheel that is installed, for example the first hash of `annotated-doc` (its only wheel), or remove all hashes of one package.
- Use `python -m venv` for the fresh venv (it has pip offline). `uv venv` has no pip, and upgrading pip would download it unhashed.
- `ruff check manager` and `ruff format --check manager` currently fail on your files: E501 in `tests/test_lock_files.py` (lines 1, 13, 14, 65) and `tests/test_project_config.py` (line 1), and `test_lock_files.py` needs reformatting. mypy passes on them.
- The `re` ban applies to `manager/tests/` too (ruff has one config here), so use `re2` in tests or ask me for a per-file ignore.
- `re2` has no type stubs or `py.typed`. If a mypy-checked test imports it, ask me for a `[[tool.mypy.overrides]]` entry.

## How to rerun

From the repo root with the brief's PATH: `python -m venv <tmp>/v && <tmp>/v/Scripts/python.exe -m pip install --require-hashes -r manager/requirements.txt` (the same for `requirements-dev.txt`). Lint and type checks run from `manager/.venv/Scripts/`: `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager`.
