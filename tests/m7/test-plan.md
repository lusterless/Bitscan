# M7 test plan (compliance catalog: `.bit` importer and validator)

Owner: tester (`tester-m7`). Written 2026-10-27 from `work/tasks.md` "M7 compliance catalog" (TASK-139 to TASK-175 acceptance tests, design notes D1 to D5, TP-M7-00 to TP-M7-30, gates G54 to G61, mutation table CHK-M7-320 to -371), `work/requirements.md` REQ-150 to REQ-185, the approved answers in `work/open-questions.md` "M7" (#1, #2, #9, #10, #11, #13 to #17, #20, #21, #23, #27, #98 to #111, PD-33 to PD-36; user approval in `work/decisions.md` 2026-10-27: every recommended answer applies), and the spec itself (SR in full; TS §1.4, §4.1 to §4.3, §4.6, §5.2 catalog tables, `task`, `v_plugin` and grants L992 to L1013, §6.2, §6.3, §8.1, §8.3, §8.4). Written **before any M7 product code existed** (`bm/services/importer/` absent at the time of writing). Results go to [report.md](report.md).

`bm/` means `manager/bitscan_manager/`; `bt/` means `bits/tests/`; `w/` means `web/`.

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree (no running app, no database). **APP** = the real code against real dependencies: a PostgreSQL 16 database through the Testcontainers harness, a real temporary bits folder on a Linux file system, `create_app(...)` served by the ASGI test client, the `bitscan-manager` CLI or `serve` process, or the built web bundle.
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m7` (ruff, `ruff format`, `mypy --strict`, `npm` checks only). **W** = WSL2 Ubuntu 24.04 with Docker, tester-m7 only: working copy `/root/bstest-m7-<label>` (tree copied without `.venv`, `node_modules`, `__pycache__`), venv `/root/venv-m7` built with `pip install --require-hashes -r manager/requirements-dev.txt` plus `pip install --no-deps --no-build-isolation -e manager`, `CI=true` (nothing skipped), `BSTEST_RUN_LABEL=m7t-<label>` (only my containers, named and labelled `m7t-*`, are created and removed), pytest-xdist `-n auto` (one PostgreSQL 16 container per worker), every run under `timeout`. **Python tests run on W only.** Before a W run, Windows free memory must be at least 3,500 MB; otherwise the run waits and the row says so. **CI** = GitHub Actions only.
- PostgreSQL checks use the M1 harness: the TS §5.2 Bootstrap from the spec, `bitscan-manager db migrate`, then connections only as `bitscan_app` (product code under test) or, to build a state the app cannot write (scans, jobs, schedules, corruption), as **owner** (`bitscan_migrate` + `SET ROLE bitscan_owner`). Modules that need an untouched catalog use `own_migrated_server` (one container per module).
- **Row checksum** = `md5(string_agg(t::text, '|' ORDER BY <pk>))` per table, read as owner; "unchanged" means equal checksums for `family`, `policy`, `plugin`, `policy_plugin` (catalog) and, where named, `agent`, `agent_package`, `os_info`, `scan`, `scan_job`, `scan_schedule`, `scan_result`, `audit_log`, `bit_import`, `task`.
- **Fixtures** come from `bt/` (TP-M7-01) and its `manifest.json` (file → expected codes, line, element). Oversize and 5,000-plugin files are generated at test time. Every expected value below comes from the spec or an approved answer, never from the implementation.
- **Alert entry** = an `audit_log` row with `detail.alert = true` and `detail.alert_kind` = the #101 kind; "reaches the sink" = it appears in the fake sink (`manager/tests/fake_sink.py`); metric = `bitscan_alerts_total{kind}` (+1 exactly).
- **Time** is never waited out: the `Clock` fake or a backdated row (decisions 2026-10-26). The watcher's "within 5 s" is a bound polled at 50 ms, not a sleep.
- **Races** use two threads or two connections held at a `threading.Barrier` / a held advisory lock, never sleeps for ordering.
- **Planted violations** are made in a throwaway copy (`$TEMP/m7t-mut-<id>` on L, `/root/bstest-m7-mut-<id>` on W), never in the worktree; the unmodified copy is green first; "red" = non-zero exit **and** the named test fails for the planted reason. High-risk (importer) tasks get every plant of their rows plus the per-task plants in "Extra plants".
- **Results are totals**: `passed/total`, plus failed, errors, skipped. A failing test is re-run alone by node id after the fix, as its own row (`1/1 passed`).
- Every route task's TEST also re-runs G6 (OpenAPI export byte-identical), the OpenAPI error contract (`test_openapi.py`), the route walk G34 (`test_invariants_m3.py`) and `test_security_m7.py`.

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| File size | ≤ 5 MiB = 5,242,880 bytes passes BIT001; 5,242,881 is BIT001 (folder) / 413 `too_large` (upload) | SR §4.1 BIT001; TS §6.3 L1138; #57 |
| Upload envelope | request body cap 5 MiB + 64 KiB = 5,308,416 bytes; `file` part ≤ 5,242,880; above either → 413 `too_large`, no `bit_import` row, no alert, no file; every other user route keeps 1 MiB | #99 (a), (b); REQ-037 change |
| Encoding | UTF-8 only; UTF-8 BOM allowed; UTF-16/UTF-32 BOM, declared encoding other than UTF-8 (any case, `utf-8` allowed), invalid UTF-8 (strict) → BIT001; XML 1.0 only | D1; #105 (f) |
| XML hazards | any DTD (with or without entities), entity declarations, parameter entities, external references → BIT001; no file or network access; peak memory < 64 MiB | TS §4.1 L517, §8.1 L1251; REQ-150 (1) |
| Parser caps | stop after 35,014 elements: BIT017 if > 5,000 `Plugin` seen, otherwise BIT002; depth > 16 → BIT002; > 8 attributes on an element → BIT002 | #105 (a) |
| Structure | root `Policy` (`@formatVersion` only attribute); children in order `PolicyName`, `PolicyDescription`, `PolicyStatus`, `Family` (only `FamilyName`), `PluginsGroups` (≥ 1 `Plugin`); `Plugin` children in order `PluginName`, `PluginDescription`, `PluginId`, `Execute` (`@timeout` only attribute), `Operator`, `ExpectedResult`; case-sensitive; each once; anything else BIT002; comments ignored; PIs (other than the XML declaration) and namespaces BIT002; whitespace-only text between elements ignored, other text in a container BIT002; empty `PluginsGroups` BIT002; second `Family` BIT002 | SR §2; #2, #10, #16, #105 (b)–(d) |
| Missing `Operator` / `ExpectedResult` | BIT010 / BIT011 (content rules still run), never BIT002 | #2 |
| `@formatVersion` | absent or exactly `1.0` (stored `1.0`); `1.1`, `1.00`, `` → BIT016 | SR §2.1; REQ-151 (5) |
| Trimming | only space, tab, CR, LF, both ends, before every length and empty check; U+00A0 is kept | #17 |
| Lengths (characters) | `PolicyName` 1–128, `PolicyDescription` 0–4,000, `FamilyName` 1–128, `PluginName` 1–255, `PluginDescription` 0–4,000, `ExpectedResult` 0–4,000 → BIT017 outside; `Execute` 1–16,384 → BIT008 outside | SR §2; REQ-152 |
| Plugins | 1–5,000; 5,001 → BIT017 | SR §2.3; REQ-152 (6) |
| `PolicyStatus` | `enabled`/`disabled` any case, stored lowercase; else BIT003 | SR §2.1 |
| `PluginId` | exactly `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (version and variant bits not checked); uppercase, braces, `urn:uuid:`, 32-hex → BIT004; repeated id → BIT005 on the later plugin | #109; SR §4.1 |
| `@timeout` | ASCII digits only, leading zeros allowed, 1–600; absent → 60; `0`, `601`, `30s`, `1.5`, `-1`, `+5`, ` 30`, `` → BIT017 | #105 (e); REQ-152 (5) |
| `Operator` | 14 names (`equals`, `not_equals`, `contains`, `not_contains`, `regex`, `not_regex`, `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `empty`, `not_empty`), any case, stored lowercase; else BIT010 | SR §2.4; #11 |
| Number (BIT012) | trimmed `[+-]?[0-9]+(\.[0-9]+)?`, ASCII digits | #13 |
| Regex (BIT013) | compiled by google-re2 in the evaluator's form; `(?=x)`, `(a)\1`, `[` refused; never Python `re`; no RE2 text on stderr or in logs | REQ-153; security invariants |
| BIT014 | `empty`/`not_empty` need empty trimmed `ExpectedResult`; all others need non-empty | SR §4.1 |
| `control_ref` | leading ASCII `[0-9]+(\.[0-9]+)*` of trimmed `PluginName`; none → NULL + BIT101 (Warn); > 32 chars → NULL + BIT103 (Warn) | SR §3.3; REQ-154 |
| Warnings | stored in `bit_import.errors` and returned, on success and on rejection; never reject | #110 |
| Finding | exactly `{line, element, code, message}`; `line` 1-based start-tag line or null; `element` path `Policy/PluginsGroups/Plugin[n]/<Element>` (1-based `n`), `…/Execute/@timeout`, null for file-level; `message` fixed text quoting ≤ 64 chars of the value, C0, DEL and `\` escaped; order by line; no cap on count | #105 (g), (h); REQ-155 |
| Code table | BIT001–005, 007, 008, 010–017 Reject; BIT101, BIT103 Warn; BIT102 Reject; BIT006, BIT009, BIT018–BIT020 absent | SR §4, §4.1 |
| BIT001/BIT002 first | either present → no other code reported | SR §4 |
| BIT102 | SR §4.2 lists; #108 (a)–(k) matching; fail closed on unlexable input (unterminated quote or substitution, depth > 8) | SR §4.2; #108 |
| Store | SR §3.6; `version` +1 on hash change and on revival (#14); counts per #21; retire = not listed by any non-deleted policy (#104 (b)); never DELETE `policy` | SR §3.6; #14, #21, #104 |
| `bit_import.file_name` | folder: path relative to the server folder; upload: part `filename` decoded UTF-8 with replacement, U+0000, other C0 and DEL → U+FFFD, cut to 255 characters, missing → `` | #99 (d) |
| Upload paths | temp `uploaded/.tmp-<policy_id>-<sha256>` with `O_WRONLY\|O_CREAT\|O_EXCL\|O_NOFOLLOW`, flushed before commit; final `uploaded/policy-<policy_id>.bit`, mode 0600 | TS §4.1 L522; REQ-163 |
| Audit actions | `policy.import`, `policy.import_rejected`, `policy.import_refused`, `policy.move`, `policy.delete`, `policy.status_change`, `bits.rebuild`, `catalog.integrity_check` | #101 |
| Alert kinds | `policy_imported`, `policy_import_rejected`, `policy_deleted`, `policy_rebuilt`, `policy_reenabled`, `catalog_integrity_failed` | #101 |
| Actors | `user:<user_id>`, `cli:root`, `system` | #101 |
| Import metric | `bitscan_import_failures_total{mode}` +1 per rejected import on record commit | #101 |
| Import alert detail | changed Executes = new plugins + changed `execute_sha256`; each `{plugin_uuid, plugin_name, execute, execute_sha256, flags}`; flags = case-insensitive substrings of `shadow`, `.ssh`, `.pem`, `.key`, `token`, `credentials` | #100 |
| Skipped | `auto` with hash equal to that policy's last success → one `skipped` row, no audit entry; `manual` and `rebuild` never skip | TS §4.1 L532; #23 |
| Routes (#98) | list `{items, next_cursor}`; item fields (a); detail (b) incl. `deleted_at`, `plugins` in `sort_order`; PATCH 200 item / 409 `conflict` deleted / 404 `not_found`; import 200 `{import_id, outcome, policy_id, policy_name, policy_version, plugins_added, plugins_updated, plugins_retired, errors}`; DELETE 204 / 404 / 409 `conflict` / 409 `policy_managed_on_server`; rebuild 202 `{task_id}`; task `{task_id, kind, state, requested_by, result, started_at, finished_at}`; `policy_id`, `import_id` integers, `task_id` UUID string; internal error 503 `about:blank`, no row | #98 |
| Auth (routes) | GET `/policies*` viewer; PATCH admin (session or `bsk_`); import admin (session or `bsk_`); DELETE and rebuild admin TOTP session + sink gate (403 `totp_session_required` for `bsk_`, 503 `audit_sink_unavailable` after 15 min outage); `/tasks/{id}`, `/imports` admin; `bsa_`/`bse_` 401 everywhere; restricted admin session 403 `totp_enrolment_required` | TS §6.2; #1 |
| Start-up gate | until start-up ends: upload, delete, rebuild → 503 `about:blank` with `Retry-After: 10`; reads and health served | #102 (d) |
| CLI | folder: `BITSCAN_BITS_DIR` env, else `/etc/bitscan/manager.env`, else `/var/lib/bitscan/bits`; exit 0 committed (even with rejected files), 1 failed, 2 configuration; one line per file `<outcome> <source_file> …`; `requested_by` NULL, actor `cli:root` | #107 |

## Gate map

| Gate | Checks |
| --- | --- |
| G1 ruff (S608, `re`, `xml.*`, `lxml` bans) | CHK-M7-315, -336, -337, -347, -348 |
| G2 ruff format, G3 mypy --strict, G4 hashed locks | CHK-M7-315, CHK-M7-016 to -019 |
| G5 services coverage ≥ 85 % incl. `services/importer` (W) | CHK-M7-316 |
| G6, G16 OpenAPI export and client regeneration | CHK-M7-317 and each route task's last row |
| G12–G15 web | CHK-M7-319 |
| G18 full W run, 0 skipped | CHK-M7-318 |
| G34 route walk | CHK-M7-281 |
| G54 importer unit suite | CHK-M7-010 to -139, -185 to -189 |
| G55 property and fuzz | CHK-M7-027, -112, -197 |
| G56 importer integration | CHK-M7-140 to -184, -190 to -249 |
| G57 catalog API and security suite | CHK-M7-250 to -289 |
| G58 CLI | CHK-M7-290 to -296 |
| G59 samples | CHK-M7-300 to -304 |
| G60 catalog alerts | CHK-M7-286 |
| G61 watcher and `serve` (Linux) | CHK-M7-237 to -249 |

## TP-M7-01: fixtures (REQ-180) — `bits/tests/**`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-001 | CODE | `bt/manifest.json` lists every fixture with its expected codes, and every listed file exists; every SR §4.1 code (BIT001–005, 007, 008, 010–017, 101, 102, 103) has at least one fixture failing only that code (BIT007 and BIT015 as fixture pairs needing a catalog state) | W |
| CHK-M7-002 | CODE | The BIT001 set exists: external entity by `file://` and `http://`, parameter entity, billion laughs, quadratic blow-up, DTD only, external DTD, UTF-16 BOM, UTF-32 BOM, ISO-8859-1 (with and without non-ASCII bytes), invalid UTF-8 (bad byte, overlong, encoded surrogate), not well-formed, mismatched tags, empty, whitespace only, the TS §1.4 sample tag forms; oversize generated at test time | W |
| CHK-M7-003 | CODE | `bt/valid/sr-1.1-example.bit` is byte-identical to the SR §1.1 code block (extracted from the spec text by the test) | W |
| CHK-M7-004 | CODE | `bt/bit102/must_reject.json` holds one case per SR §4.2 word, option, verb and form plus the REQ-157 (1) extras; `must_pass.json` holds the REQ-157 (2) list plus ≥ 40 more CIS audit commands | W |
| CHK-M7-005 | CODE | `bt/hostile_names.json` holds the REQ-163 (1) client names (invalid UTF-8 as hex) | W |
| CHK-M7-006 | CODE | No fixture contains a CR byte unless the manifest says so (`.gitattributes` `eol=lf`); binary encodings survive a git round trip (hash in manifest equals the file) | W |

## TP-M7-02: model and code table (TASK-140, REQ-152, REQ-155) — `manager/tests/test_bit_model.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-010 | CODE | The code table holds exactly BIT001–005, 007, 008, 010–017, 101, 102, 103 with the SR §4.1 severity each (101 and 103 Warn, the rest Reject); BIT006, BIT009, BIT018, BIT019, BIT020 absent | W |
| CHK-M7-011 | CODE | Each SR §2 limit constant equals its value: 128, 4,000, 128, 255, 4,000, 4,000, 16,384, timeout 1–600 default 60, 5,000 plugins, 5,242,880 bytes, #105 caps (35,014 elements, depth 16, 8 attributes), message quote 64 | W |
| CHK-M7-012 | CODE | A `Finding` serialises to exactly `{line, element, code, message}` (no severity key), `line` int or null, `element` str or null; JSON round trip | W |
| CHK-M7-013 | CODE | `Finding`, `Node`, `ParsedPolicy`, `ParsedPlugin` are frozen dataclasses (assignment raises); the module imports nothing from `xml`, `lxml`, `re` | W |
| CHK-M7-014 | CODE | `mypy --strict` and ruff pass on `bm/services/importer/{__init__,model}.py` | L |

## TASK-139 dependencies (REQ-185, PD-33)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-016 | APP | Fresh CPython 3.12 venvs on Windows and Linux: `pip install --require-hashes -r manager/requirements.txt` and `-r manager/requirements-dev.txt` exit 0; `import python_multipart` works (the planner's revised acceptance text; `multipart` is a deprecated alias), its low-level `MultipartParser` is present | L, W |
| CHK-M7-017 | CODE | The recorded lock command reproduces both lock files byte for byte | W |
| CHK-M7-018 | CODE | The runtime lock names no test or lint tool (pytest, ruff, mypy, hypothesis, testcontainers, coverage, …); the diff adds only python-multipart (and nothing else changes in the runtime lock) | L |
| CHK-M7-019 | APP | Existing `test_lock_files.py`, `test_project_config.py`, `test_module_imports.py` pass | W |

## TP-M7-03: parser BIT001 (TASK-141, REQ-150, REQ-176) — `test_bit_parse.py`, `test_bit_fuzz.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-020 | CODE | Each BIT001 fixture gives exactly one finding, code BIT001, no other code | W |
| CHK-M7-021 | CODE | External entity (file): the canary file's content never appears; the parser opens no file (an `open`/`os.open` audit hook sees no path beyond none); `http://` entity and external DTD: a local listener sees no connection | W |
| CHK-M7-022 | CODE | Billion laughs and quadratic blow-up: BIT001, peak `tracemalloc` < 64 MiB, < 2 s | W |
| CHK-M7-023 | CODE | 5,242,880-byte valid file passes BIT001 (no finding); 5,242,881 bytes → BIT001 without being parsed (no tree) | W |
| CHK-M7-024 | CODE | The SR §1.1 example gives a `Node` tree whose start-tag lines equal the file's (line of each tag computed from the text); comments not in the tree; CDATA and text in `Execute` joined in order | W |
| CHK-M7-025 | CODE | UTF-8 BOM and `encoding="utf-8"` accepted; ISO-8859-1 declared (even ASCII-only), UTF-16/32 BOM, invalid UTF-8 → BIT001 with the line of the first bad byte where applicable | W |
| CHK-M7-026 | CODE | #105 caps: 35,015 elements → stops (BIT002 or BIT017 per (a)); depth 17 → BIT002; 9 attributes → BIT002; parse of the cap case is bounded in time and memory | W |
| CHK-M7-027 | CODE | Property: ≥ 10,000 random and mutated inputs (bytes, mutated SR example and samples) return findings or a tree, never raise, each < 2 s (G55 unit half) | W |
| CHK-M7-028 | CODE | No module under `bm/services/importer/` imports `xml.*` (other than through `defusedxml`) or `lxml` (AST scan) | L |

## TP-M7-04: value helpers (TASK-142, REQ-152 to REQ-154) — `test_bit_values.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-040 | CODE | #13 accept: `0`, `-1`, `+2.5`, `14`, `007`, `-0`, ` 14 ` (trimmed); reject: `abc`, `1e3`, `nan`, `inf`, `1_000`, `0x10`, `.5`, `5.`, `١`, `１`, ``, `+`, `1.2.3`, `--1` | W |
| CHK-M7-041 | CODE | RE2 helper: `^MaxAuthTries\s+[1-4]$`, `^\s*PermitEmptyPasswords\s+yes` compile; `(?=x)`, `(a)\1`, `[`, `(?<!a)b` refused; a 4,000-char pattern within 1 s; nothing on stderr (capfd) and no log record | W |
| CHK-M7-042 | CODE | #109: lowercase 8-4-4-4-12 accepted (incl. nil UUID, any version nibble); uppercase, mixed case, braces, `urn:uuid:`, 32-hex, 35/37 chars, misplaced hyphens, non-hex letter, non-ASCII digit refused | W |
| CHK-M7-043 | CODE | Trim removes only space, tab, CR, LF at both ends; U+00A0, U+2003, U+FEFF kept; inner whitespace kept | W |
| CHK-M7-044 | CODE | `control_ref`: `1.3.1.1 - Ensure …` → `1.3.1.1`; `Ensure` → None (BIT101); 32-char ref kept, 33 → None (BIT103); Arabic-Indic digits → None (BIT101); `1.3.` → `1.3`; `1..2` → `1`; `1.3.1.1Ensure` → `1.3.1.1` | W |
| CHK-M7-045 | CODE | No `import re` in `values.py`; the module is the one M8 will import (exports the number and RE2 helpers) | L |

## TP-M7-05: structure (TASK-143, REQ-151) — `test_bit_structure.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-050 | CODE | SR §1.1 tree → `ParsedPolicy` with raw values and lines, no finding | W |
| CHK-M7-051 | CODE | Each required element (except `Operator`, `ExpectedResult`) missing → BIT002 at the parent's line with the path; no `ParsedPolicy` | W |
| CHK-M7-052 | CODE | Each element duplicated, and each adjacent pair swapped → BIT002 at the offending element's line | W |
| CHK-M7-053 | CODE | `<policyName>`, wrong root, second `Family`, empty `PluginsGroups`, unknown element, unknown attribute (root, `Plugin`, `Execute`), non-whitespace text in a container, child in a leaf, PI, namespace (incl. XInclude, never fetched) → BIT002 | W |
| CHK-M7-054 | CODE | Missing `Operator` in plugin 2 → `ParsedPolicy` with that field marked missing, no BIT002 (BIT010 reported later, CHK-M7-072); same for `ExpectedResult` (BIT011) | W |
| CHK-M7-055 | CODE | `formatVersion` `1.1`, `1.00`, `` → BIT016; absent and `1.0` → `1.0` | W |
| CHK-M7-056 | CODE | BIT002 + BIT003 file → only BIT002; BIT002 + bad `formatVersion` → only BIT002 | W |
| CHK-M7-057 | CODE | Comments anywhere (incl. inside `Execute` between CDATA parts) are ignored and never part of a value | W |

## TP-M7-06: validators (TASK-144, REQ-152 to REQ-155) — `test_bit_validate.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-065 | CODE | One fixture per content code (BIT003, 004, 005, 008, 010, 011, 012, 013, 014, 016, 017, 101, 103) gets exactly that code with its manifest line and path | W |
| CHK-M7-066 | CODE | SR §1.1 example: no finding | W |
| CHK-M7-067 | CODE | Bound table: each length at its limit accepted and +1 character refused (BIT017; BIT008 for `Execute`), with multi-byte characters (bytes ≠ characters); whitespace-only `PolicyName`, `FamilyName`, `PluginName`, `Execute` count as empty; `PolicyDescription`, `PluginDescription` 0 accepted | W |
| CHK-M7-068 | CODE | `ENABLED`, `Disabled` → lowercase; `on` → BIT003; `EQUALS` → `equals`; `equal` → BIT010 | W |
| CHK-M7-069 | CODE | BIT004 forms (#109); duplicate id → BIT005 on the second plugin, its `PluginId` line | W |
| CHK-M7-070 | CODE | Timeout table (REQ-152 (5)), `0600` → 600, absent → 60 | W |
| CHK-M7-071 | CODE | 5,000 plugins accepted; 5,001 → BIT017 | W |
| CHK-M7-072 | CODE | Missing `Operator` in plugin 2 → BIT010 for `Plugin[2]` plus that file's other content faults; missing `ExpectedResult` → BIT011 | W |
| CHK-M7-073 | CODE | BIT012 per #13 for each numeric operator; BIT013 for `regex` and `not_regex`; BIT014 both directions; `empty` with empty value no finding | W |
| CHK-M7-074 | CODE | Three faults on three lines → all three, in line order; findings sorted by line across the suite | W |
| CHK-M7-075 | CODE | Warnings-only file → no Reject; warnings have Warn severity | W |
| CHK-M7-076 | CODE | Messages: ≤ 64 characters of file content (16,384-char value never whole), C0, DEL, `\` escaped; four keys only | W |
| CHK-M7-077 | CODE | No retired code produced across all fixtures | W |

## TP-M7-07: lexer (TASK-145, REQ-156) — `test_bit102_lexer.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-100 | CODE | ≥ 60-input token table: quoting (`echo "rm -rf /"` one argument; `r''m`, `\rm`, `"r"m` → word `rm`), operators `; & | && || ( )` and newline, redirections with descriptor and target (`2>/dev/null`, `>|`, `>>`, `&>`, `2>&1`, `<`), comments (`# rm`, `a #b`, `a#b` is a word), assignments, `$( )` and backticks (nested script), `<( )`, `>( )`, `$(( ))`, here-documents quoted (data) and unquoted (`$(id)` found), reserved words kept | W |
| CHK-M7-101 | CODE | Unterminated `'`, `"`, `$(`, backtick, `${`, here-document without end; 9 nested substitutions → the fail-closed error; 8 nested accepted | W |
| CHK-M7-102 | CODE | The module imports no `subprocess`, `os.system`, `eval`/`exec` builtins, `shlex` (AST) | L |
| CHK-M7-112 | CODE | Property: random strings up to 16,384 chars never raise anything but the fail-closed error, each < 100 ms | W |

## TP-M7-08: BIT102 rules (TASK-146, REQ-157) — `test_bit102.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-115 | CODE | Every must-reject case → BIT102 with the offending token in the message | W |
| CHK-M7-116 | CODE | Every must-reject command also in each context: pipeline (`true | X`), after `;`, `&&`, `||`, `&`, in `( )`, `{ …; }`, `if`/`while`/`for`/`case`/function body, `$( )`, backticks, `<( )`, `bash -c '…'`, `sh -c "…"` → BIT102 | W |
| CHK-M7-117 | CODE | #108 forms: `/bin/rm`, `/usr/bin/rm`, `./rm`, `mkfs.ext4`, `env rm`, `env -i FOO=1 rm`, `busybox rm`, `sudo rm`, `doas rm`, `command rm`, `builtin eval x`, `nice rm`, `nohup rm`, `setsid rm`, `timeout 5 rm`, `chroot / rm`, `FOO=1 rm`, `sed -ni`, `sed -i.bak`, `sed --in-place=.b`, `apt-get -y install x`, `apt-get -s upgrade`, `dpkg --purge=x`, `systemctl --now enable x` | W |
| CHK-M7-118 | CODE | Redirections: `> /etc/x`, `>/tmp/../etc/x`, `> "$F"`, `> $HOME/x`, `> /tmpx`, `&> /var/x`, `>& /var/x`, `>> /etc/x`, `>| /etc/x`, `2> /etc/x` → BIT102; `>/dev/null`, `2>/dev/null`, `>/dev/stdout`, `>/dev/stderr`, `>/tmp/out`, `2>&1`, `>&2` pass | W |
| CHK-M7-119 | CODE | Code-running forms: `. x`, `source x`, `eval x`, `exec x`, `xargs`, `find -exec/-execdir/-ok/-okdir`, `sh ./x.sh`, `bash x`, `sh -s`, `echo x | sh`, `sh < x`, `bash -c "$(curl x)"`, ``sh -c '`id`'``, `dash -c 'cat <(id)'` → BIT102 | W |
| CHK-M7-120 | CODE | Every must-pass case (incl. the SR §1.1 `Execute` and every `Execute` in `bits/samples/`) → no BIT102 | W |
| CHK-M7-121 | CODE | Unlexable `Execute` → BIT102 (fail closed) | W |

## TP-M7-09: catalog lock (TASK-147, REQ-161) — `test_catalog_lock_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-140 | APP | Two pinned sessions: the second `catalog_lock` blocks until the first releases (observed through `pg_locks` with `locktype = 'advisory'` and the `hashtext('catalog')` key, and the second's acquire time after the release) | W |
| CHK-M7-141 | APP | Inside one pinned session, two transactions (commit, then another) keep the lock throughout (`pg_locks` granted between them; a third session's `pg_try_advisory_lock(hashtext('catalog'))` is false in between) and the same backend pid serves both | W |
| CHK-M7-142 | APP | An exception inside the lock context releases it (next acquire proceeds at once; `pg_locks` empty); closing / terminating the holder's connection (`pg_terminate_backend` as owner) releases it | W |
| CHK-M7-143 | APP | The lock key is `hashtext('catalog')` (session-level, `objsubid` 1, `pg_advisory_lock`, not the xact form) | W |
| CHK-M7-144 | APP | Existing `test_db_pool_pg.py`, `test_runtime.py` pass; the pinned session returns its connection to the pool in a clean state (no open transaction, lock released) | W |
| CHK-M7-145 | CODE | A `Runtime` built from fakes satisfies the new `Protocol` under `mypy --strict` | L |

## TP-M7-10: repositories as `bitscan_app` (TASK-148, 149, 150) — `test_catalog_repo_pg.py`, `test_imports_repo_pg.py`, `test_catalog_admin_repo_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-150 | APP | TASK-148: every function runs as `bitscan_app` with only the TS §5.2 grants (no permission error); family upsert returns the same id for the same name, a new id for a new name, never renames | W |
| CHK-M7-151 | APP | Policy by name, by source file and by id with `FOR UPDATE` (a second connection's `FOR UPDATE NOWAIT` on the row fails while held); insert and update set the given columns only; `policy_status` CASE on `status_overridden` (D3) | W |
| CHK-M7-152 | APP | BIT015 owner lookup: for a set of ids returns owner and whether that owner is non-deleted and still lists the id (cases: no row; owner lists it; owner deleted; owner dropped it; owner is the importer) | W |
| CHK-M7-153 | APP | Plugin upsert counts per #21: new uuid → added; identical values → neither; any changed column (name, description, execute + sha, operator, expected, timeout, control_ref, family, owner, `retired → active`) → updated, one case each | W |
| CHK-M7-154 | APP | `policy_plugin` replace: rows equal the given list with 1-based `sort_order` (reorder, remove, add) | W |
| CHK-M7-155 | APP | Retire: retires exactly the plugins listed by no non-deleted policy, returns them, skips those a non-deleted policy lists, does not touch already retired rows, never deletes | W |
| CHK-M7-156 | APP | Hostile and boundary values round-trip byte-identical (U+0000-free Unicode, 16,384-char execute, quotes, `'; DROP …`) through parameters | W |
| CHK-M7-157 | CODE | ruff S608 clean on `bm/repositories/catalog.py`; planted f-string red (CHK-M7-336) | L |
| CHK-M7-160 | APP | TASK-149: a `bit_import` insert in its own transaction survives a rollback of a sibling (catalog) transaction on another connection and inside the same pinned session | W |
| CHK-M7-161 | APP | Newest-first paging by `import_id`: N + 1 rows with limit N give each row once, newest first, `next_cursor` null at the end; every column returned as stored (`errors` JSON exactly) | W |
| CHK-M7-162 | APP | Task insert (`rebuild`, `running`, `requested_by` null or user), finish (`succeeded`/`failed`, `result`, `finished_at`), get (unknown → None); mark-failed changes only `running` rows, sets `finished_at`, returns the count | W |
| CHK-M7-163 | APP | `bitscan_app` still cannot UPDATE or DELETE `bit_import` (grant probe) | W |
| CHK-M7-164 | CODE | ruff S608 clean on `bm/repositories/imports.py` | L |
| CHK-M7-165 | APP | TASK-150: list excludes deleted, filters by status, carries the #98 (a) fields (`family_name`, `plugin_count` = rows in `policy_plugin`) in `policy_name`, `policy_id` order with keyset paging (N + 1 once each) | W |
| CHK-M7-166 | APP | Detail: deleted policies returned with `deleted_at`; plugins in `sort_order` from `v_plugin` with `display_name` = `<family> - <plugin>` and every #98 (b) field | W |
| CHK-M7-167 | APP | Status update (REQ-168 (1)): set `enabled`/`disabled` → `policy_status`, `status_overridden = true`; clear → `policy_status = file_status`, override false; returns before/after for the re-enable decision; `updated_at` changes | W |
| CHK-M7-168 | APP | Soft delete with owner-written fixture rows (scan with jobs `queued`, `dispatched`, `running`, and a `queued` job of another policy; two schedules of the policy and one of another): only the policy's queued compliance job → `cancelled` with `finished_at`; both its schedules `enabled = false`; others untouched; `deleted_at` set, `source_file` `deleted/<id>`; owned plugins `retired` (those another non-deleted policy lists stay active); `policy_plugin` rows kept (#104 (a)); no DELETE on `policy` (statement log / `pg_stat_user_tables.n_tup_del` = 0) | W |
| CHK-M7-169 | APP | Integrity reads return per non-deleted policy: `source_file`, `source_sha256`, `policy_plugin` count, and plugins not `active` or not owned | W |
| CHK-M7-170 | CODE | ruff S608 clean on `bm/repositories/catalog_admin.py` | L |

## TP-M7-11: store (TASK-151, REQ-158, REQ-159) — `test_import_store_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-173 | APP | REQ-158 (1): SR §1.1 example as `x.bit` → the exact rows (family, policy v1 enabled/enabled, `source_file` `x.bit`, sha of bytes, plugin execute `dpkg-query -W -f='${Status}' apparmor 2>/dev/null`, its sha, timeout 30, control_ref `1.3.1.1`, active, sort_order 1, `display_name` `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`) | W |
| CHK-M7-174 | APP | REQ-158 (2): identical re-import keeps version and ids, counts 0/0/0; changed bytes → version + 1 exactly | W |
| CHK-M7-175 | APP | REQ-158 (3): override true + disabled, file enabled → only `file_status`; override false → both | W |
| CHK-M7-176 | APP | REQ-158 (4): reorder → sort_order only (updated 0); remove → retired 1, row kept; one Execute changed → updated 1, new sha | W |
| CHK-M7-177 | APP | REQ-158 (5): fault after the third plugin's upsert → caller rollback leaves all catalog checksums unchanged | W |
| CHK-M7-178 | APP | REQ-158 (6) / #14: deleted policy re-imported → same id, `deleted_at` NULL, version + 1 even for identical bytes, plugins active, schedules still disabled, override kept | W |
| CHK-M7-179 | APP | REQ-159 (1), (2): BIT007 naming the other policy and nothing changed; after the old file is gone, the move keeps the id and writes one `policy.move` entry | W |
| CHK-M7-180 | APP | REQ-159 (3): server file with an uploaded policy's name → moves, uploaded copy reported for deletion, one move entry | W |
| CHK-M7-181 | APP | REQ-159 (4) / #106: rename in place keeps id, plugins, `scan` rows; collisions: `Y` in an existing server file → BIT007; `Y` uploaded → moves, `X` deleted; `Y` deleted → revived, `X` deleted | W |
| CHK-M7-182 | APP | REQ-159 (5): BIT015 naming the owner; after owner deleted or dropping the id, the file imports and `owner_policy_id` moves | W |
| CHK-M7-183 | APP | Returns counts, changed Executes (new + changed sha) and moved/deleted policies | W |
| CHK-M7-184 | APP | #104 (d), (e): `imported_at` set on success; `updated_at` changes only with a stored column; a family name change points to another family row (old row kept) and plugins follow | W |

## TP-M7-12 and -13: alerts (TASK-153) and delete service (TASK-152)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-185 | CODE | Every M7 kind exported, counters start at zero; `raise_alert` still refuses an unknown kind | W |
| CHK-M7-186 | CODE | `policy_imported` builder: the #100 entry shape; flags for each of the six words case-insensitively (`/etc/SHADOW`, `~/.ssh/id_rsa`, `x.PEM`, `x.key`, `/run/token`, `/etc/credentials`), none for `dpkg-query …` | W |
| CHK-M7-187 | CODE | Rejected, deleted, moved, rebuilt, re-enabled, integrity detail shapes per #101; no stdout, token or file body other than the Executes | W |
| CHK-M7-188 | CODE | `bitscan_import_failures_total{mode}` exists for `auto`, `manual`, `rebuild` | W |
| CHK-M7-224 | APP | REQ-167 (1), (2), (5), (6) through the delete service with a temporary bits folder; one `policy_deleted` alert | W |
| CHK-M7-225 | APP | A fault before commit leaves the row and the file; the no-lock core inside another transaction rolls back with it | W |

## TP-M7-14: pipeline (TASK-154) — `test_import_pipeline_pg.py`, `test_import_fuzz_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-190 | APP | SR §1.1 example → one `success` row (`policy_version` 1, counts 1/0/0) and one `policy_imported` alert | W |
| CHK-M7-191 | APP | Each rejecting fixture → `rejected` row with exactly its manifest codes, one rejected alert, metric +1, catalog checksums unchanged | W |
| CHK-M7-192 | APP | `auto` unchanged → only `skipped`, no audit entry; `manual` and `rebuild` → `success` | W |
| CHK-M7-193 | APP | Warnings-only → `success` with the warnings in `errors` (#110); rejected file lists warnings too | W |
| CHK-M7-194 | APP | Rolled-back import writes no success alert and no count; a fault in the record transaction leaves the committed catalog | W |
| CHK-M7-195 | APP | Read once: the buffer hashed is the buffer parsed (a file changed after the read is not re-read) | W |
| CHK-M7-196 | APP | Internal error (database) → no `bit_import` row (#98 (j)) | W |
| CHK-M7-197 | APP | 500 generated files: after each the catalog is the complete import or unchanged (G55 PG half) | W |

## TP-M7-15 to -20: uploads, folders, rebuild, start-up, watcher, service

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-200 | APP | REQ-163 (1): every hostile name → only `uploaded/policy-<id>.bit`, file-system snapshot before and after, `file_name` in the #99 (d) form | W |
| CHK-M7-201 | APP | REQ-163 (2): symlink at the temp path → write fails, import rolls back, target untouched | W |
| CHK-M7-202 | APP | REQ-163 (3), (4): rejected re-upload leaves the file byte-identical; fault after temp write before commit → no temp file; fault after commit before rename → finished at next start-up | W |
| CHK-M7-203 | APP | REQ-163 (5): server-folder name → 409 result, no row, no file, one `policy.import_refused` entry, no alert | W |
| CHK-M7-204 | APP | REQ-163 (6): mode 0600, service user | W |
| CHK-M7-208 | APP | REQ-164 (2): `n.txt`, `.n.bit`, `sub/n.bit`, FIFO `f.bit`, symlink `l.bit` never imported; unstorable names skipped with one log line, no row | W |
| CHK-M7-209 | APP | REQ-159 (2), (3), (6) through folders; #15 order | W |
| CHK-M7-210 | APP | Unchanged folder reconcile → only `skipped` rows | W |
| CHK-M7-216 | APP | REQ-166 (1): corrupted catalog restored, ids unchanged | W |
| CHK-M7-217 | APP | REQ-166 (2)–(6): one rejected of three; untouched tables; removed file deleted; DB error → unchanged and `failed`; alert counts | W |
| CHK-M7-230 | APP | REQ-165 (1)–(4), (6); order of steps (step log); clean catalog no alert | W |
| CHK-M7-237 | APP | REQ-164 (1), (3), (4) on Linux within 5 s; non-`.bit`, hidden, subfolder events ignored | W |
| CHK-M7-238 | APP | REQ-164 (5): without inotify one log line, manager runs | W |
| CHK-M7-242 | APP | Service: #102 refusal before start-up end, success after; rebuild on the worker ends `succeeded`; stop stops watcher and waits for the worker | W |
| CHK-M7-243 | APP | `serve` with a temporary bits folder imports at start-up; `/healthz` 200 with the database down | W |

## TP-M7-21 to -26: routes and CLI

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-250 | APP | REQ-168 (1)–(5) | W |
| CHK-M7-251 | APP | REQ-169 (1)–(5) | W |
| CHK-M7-258 | APP | REQ-173 (1)–(4) | W |
| CHK-M7-262 | APP | REQ-170 (1)–(5), REQ-163 (1), (5); nothing spooled (`tempfile` spy); other routes keep 1 MiB | W |
| CHK-M7-271 | APP | REQ-171 (1)–(4); REQ-167 (1) through the route | W |
| CHK-M7-276 | APP | REQ-172 (1)–(4) | W |
| CHK-M7-281 | APP | G34 route walk with exactly the eight M7 operations added | W |
| CHK-M7-282 | APP | `bsa_` and `bse_` → 401 on each M7 route; problem+json; 600/min user limit applies | W |
| CHK-M7-283 | APP | REQ-174 (3): G30 and G35 agent contract suites unchanged (lead may run G35) | W |
| CHK-M7-285 | APP | `test_security_m7.py` (REQ-177): every TS §8.3 importer Security item | W |
| CHK-M7-286 | APP | `test_catalog_alerts_pg.py` (G60): every M7 alert entry, kind, sink, counter | W |
| CHK-M7-290 | APP | REQ-175 (1)–(6) and #107 | W |

## TP-M7-27 to -29: samples, README, web

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-300 | APP | G59: all `bits/samples/*.bit` together in one fresh catalog → each `success`, no Reject, no BIT102; distinct names and ids | W |
| CHK-M7-301 | APP | The SR §1.1 example alone in another fresh catalog → `success` | W |
| CHK-M7-302 | CODE | The 24.04 sample's first `Plugin` is byte-identical to the SR §1.1 plugin; each `PolicyDescription` ends with the #111 note; `PolicyStatus` `enabled` | W |
| CHK-M7-303 | CODE | Per-plugin script-rule rows (read-only, prints the value, CDATA, `findmnt --task 1` or `/proc/1/mountinfo` for mounts, no `xargs`/`find -exec`, no uid-0 commands, no user-writable exec, no redaction-hidden comparisons) | L |
| CHK-M7-305 | APP | README walk (REQ-184) against a WSL manager | W |
| CHK-M7-310 | APP | Web batch (REQ-181 to REQ-183) | L |

## Gate rows

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M7-315 | CODE | G1–G4 clean | L |
| CHK-M7-316 | APP | G5 ≥ 85 % with `services/importer`; red on the plant | W |
| CHK-M7-317 | CODE | G6, G16 | L |
| CHK-M7-318 | APP | G18 full suite, 0 skipped, `-n auto` | W |
| CHK-M7-319 | CODE | G12–G15 | L |

## Mutation table

CHK-M7-320 to -371 exactly as in `work/tasks.md` "M7 mutation table" (each red in its named gate). Extra plants for the W1 high-risk tasks (made in throwaway copies; each must turn the named check red):

| Check | Plant | Red in | Target |
| --- | --- | --- | --- |
| CHK-M7-372 | `pg_advisory_unlock` not in a `finally` (skipped on exception) | CHK-M7-142 | TASK-147 |
| CHK-M7-373 | `pg_advisory_xact_lock` instead of the session lock | CHK-M7-141 | TASK-147 |
| CHK-M7-374 | A different lock key (`hashtext('catalog2')`) | CHK-M7-143 | TASK-147 |
| CHK-M7-375 | Plugin upsert counts an unchanged row as updated (no `IS DISTINCT FROM`) | CHK-M7-153 | TASK-148 |
| CHK-M7-376 | Retire ignores the `deleted_at` filter (a deleted policy's rows keep plugins active) | CHK-M7-155 | TASK-148 |
| CHK-M7-377 | BIT015 lookup ignores "still lists it" | CHK-M7-152 | TASK-148 |
| CHK-M7-378 | `bit_import` insert on the caller's transaction | CHK-M7-160 | TASK-149 |
| CHK-M7-379 | Mark-failed without the `state = 'running'` filter | CHK-M7-162 | TASK-149 |
| CHK-M7-380 | Import paging off by one (`>=` cursor) | CHK-M7-161 | TASK-149 |
| CHK-M7-381 | Soft delete cancels `dispatched` jobs too, or other policies' jobs | CHK-M7-168 | TASK-150 |
| CHK-M7-382 | Soft delete skips the schedule disable or the retire | CHK-M7-168 | TASK-150 |
| CHK-M7-383 | List includes deleted policies | CHK-M7-165 | TASK-150 |
| CHK-M7-384 | Clear override leaves `policy_status` unchanged | CHK-M7-167 | TASK-150 |
| CHK-M7-385 | A retired code (BIT006) added to the table, or BIT101 made Reject | CHK-M7-010 | TASK-140 |
| CHK-M7-386 | A limit off by one (`PolicyName` 129) | CHK-M7-011 | TASK-140 |
| CHK-M7-387 | The lexer drops `$(` recursion (a substitution's script not lexed) | CHK-M7-100, -116 | TASK-145 (plan TASK-145) |

The design plans `work/plans/TASK-141.md`, `TASK-145.md`, `TASK-151.md`, `TASK-154.md` and `TASK-162.md` (PD-36) each name the plants of their task and the plan rows they must turn red: TASK-141 → 320, 321, 322, 323, 347; TASK-145 → 332, 387; TASK-151 → 335, 338, 369; TASK-154 → 333, 339, 340, 349, 350, 369; TASK-162 → 324, 345, 358. Each task's TEST also runs every row of its plan's own test table, mapped to the CHK ids above when the task is handed off.

## NOT RUN at the M7 gate (with reasons)

- TS §8.3 Sandbox "full CIS plugin set passes under the sandbox" (no runner until M10; the BIT102 half is G59).
- End-to-end import step on VMs (M11 nightly); load tests (deferred by the user).
