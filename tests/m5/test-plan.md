# M5 test plan (minimal host UI and package search)

Owner: tester (`tester-m5`). Written 2026-10-24 from `work/tasks.md` "M5 minimal host UI and package search" (acceptance tests of TASK-108 to TASK-128, TP-M5-00 to TP-M5-22, gates G1 to G6, G12 to G16, G18, G42 to G46, the mutation table CHK-M5-320 to -354), `work/requirements.md` REQ-113 to REQ-136, the plans `work/plans/TASK-110.md`, `TASK-112.md`, `TASK-113.md`, `TASK-116.md`, the TS sections they cite (§2.3, §3.2, §5.2 L712–L815, §6.2 L1076–L1127, §6.3 L1130–L1142, §7 to §7.3, §8.1, §8.3) and the user's approval "M5 breakdown approved" (`work/decisions.md` 2026-10-24: the recommended answers to #83 to #89, #32, PD-28 to PD-30 apply; `hold ok installed` counts as installed; static UI files are served without a token, a recorded deviation from TS §2.3 L118), before any M5 implementation was read. Results go to [report.md](report.md) (written by `main` from the tester's messages, because the harness blocks the tester there).

`bm/` means `manager/bitscan_manager/`; `w/` means `web/`.

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = the real app: `create_app(...)` served by the ASGI test client against a real PostgreSQL, the real `bitscan-manager serve` process, or the built bundle.
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m5` (`manager/.venv` for ruff, mypy and the OpenAPI export; `npm` from `web/` for every web check). **W** = WSL2 Ubuntu 24.04 with Docker, tester-m5 only: working copy `/root/bstest-m5-<run>` (tree copied without `.venv`, `node_modules`, `__pycache__`), venv `/root/venv-m5` built with `pip install --require-hashes -r manager/requirements-dev.txt` plus `pip install --no-deps --no-build-isolation -e .`, `CI=true`, `BSTEST_RUN_LABEL=m5-<run>` (so only M5 containers are created and removed), pytest-xdist `-n auto` with one PostgreSQL 16 container per worker, every run under `timeout`. Python tests never run on L. **CI** = GitHub Actions only.
- PostgreSQL checks use the M1 harness: Bootstrap from the spec, `db migrate` through the CLI, then connections only as `bitscan_app`. **As owner** (`bitscan_migrate` + `SET ROLE bitscan_owner`) only to build a state the app cannot.
- **Fixture fleet** (`manager/tests/package_fleet.py`, tester-owned): at least 20 hosts built through the M3 inventory ingestion (or as `bitscan_app` where ingestion cannot express a case), with: two OS versions (`ubuntu:22.04`, `ubuntu:24.04`) plus a `debian:12` host, host tags (`prod-web`, `db`, untagged hosts), multi-arch packages (`amd64`, `i386`, `all`), an epoch version (`1:1.0`), a `~` version (`1.0~rc1`), `1.0` and `1.0-0` (equal in Debian order, different text), statuses `install ok installed`, `hold ok installed`, `deinstall ok config-files`, a `decommissioned` host and an `awaiting_approval` host holding rows, hostnames with `_`, `%` and mixed case, a 255-character non-ASCII package name and hostname, and hostile text (`<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `=HYPERLINK("http://x")`). Every expected answer is computed in Python from the fleet description, never by SQL, and never from the implementation.
- **Debian order oracle** = `manager/tests/fixtures/debversion_pairs.tsv` (M1, dpkg 1.22.6), never a text comparison.
- **Refused** on a package route = 400 `application/problem+json`, `type` `invalid_request`, `detail` naming `query.<param>` and not containing the sent value (REQ-038 (2)).
- **UI test** = Vitest + jsdom + Testing Library (PD-28); the HTTP answers come from `vi.stubGlobal("fetch", …)` installed before the first import of `src/api/client.ts` (TASK-116 tester note), never from a running manager. Storage, cookie and console spies go through `Storage.prototype`, `Object.getOwnPropertyDescriptor(Document.prototype, "cookie")`, `indexedDB.open` and every `console` method, because the lint bans the direct identifiers in test files too.
- **Hostile text** check on a screen = the literal text is found with `getByText` and `container.querySelectorAll("script, img")` finds no element created from it.
- **Planted violations** are made in a throwaway copy (`$TEMP/m5-mut-<id>` on L, `/root/bstest-m5-mut` on W), never in the tree; the unmodified copy is green first; "red" = non-zero exit **and** the named test fails for the planted reason.
- **Results are reported as totals** (`passed/total`, plus failed, errors, skipped). A failing test is re-run alone by node id after the fix, as its own row.
- Every manager route task's TEST re-runs the OpenAPI export (G6, CHK-M5-302), the OpenAPI error contract and the M3 route walk (G34, CHK-M5-300).

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Search parameters | exactly `q`, `name`, `version`, `version_op`, `arch`, `status`, `os`, `tag`, `host`, `agent_id`, `group_by`, plus `limit` and `cursor`; unknown parameters ignored | TS §7.1; REQ-113 |
| Enums | `version_op` ∈ {`lt`,`le`,`eq`,`ge`,`gt`}; `status` ∈ {`installed` (default), `any`}; `group_by` ∈ {`package`,`host`} or absent; values exact (upper case refused) | TS §7.1; plan TASK-110 rule 2 |
| Lengths (#83 (h)) | `q`, `name`, `version`, `host` 255; `arch` 16; `tag` 64; `os` 49 (`os_id` ≤ 32, version ≤ 16); characters | #83 (h) |
| Refusals | `q` < 3 characters; `q` with `name`; `version_op` without `version`; enum value outside its set; `os` not `<id>` or `<id>:<version>` (empty side, second `:`); `agent_id` not a hyphenated UUID (braces, `urn:uuid:`, 32-digit form refused; either case accepted); over-length; empty value; U+0000; `version` not a Debian version (dpkg syntax); a cursor from another query, tampered, or whose anchor is gone; `limit` outside 1–500 | REQ-113; #83 (b), (c), (g); #88 |
| `q` matching | contains `q` case-insensitively (`ILIKE`, `%`, `_`, `\` literal) **or** `pg_trgm` similar at the default threshold (0.3) | #83 (a) |
| `host` | case-insensitive substring, wildcards literal | #83 (d) |
| `status` | `installed` = {`install ok installed`, `hold ok installed`, `deinstall ok installed`}; `any` = every status (so `deinstall ok config-files`, `install ok unpacked` only with `any`) | TS §7.1; #83 (f) as answered by the user 2026-10-24 (`hold`), plus the later user ruling relayed by the lead 2026-10-24 (`deinstall ok installed`) |
| Agent scope | every agent except `decommissioned`; no parameter to include them | #83 (e) |
| `os` | `ubuntu` = `os_info.os_id = 'ubuntu'` (every version); `ubuntu:24.04` = both columns; exact, case as given | #83 (c) |
| Shapes | rows `{name, version, architecture, status, agent_id, hostname}`; `group_by=package` `{name, version, architecture, host_count}`; `group_by=host` `{agent_id, hostname, package_count}`; exactly these keys; response `{items, next_cursor}`; empty = `{"items": [], "next_cursor": null}` | TS §7.1 L1213–L1215 |
| Order (#83 (b)) | rows: name, version (Debian), version text, architecture, hostname, agent_id; package: name, version (Debian), version text, architecture; host: hostname, agent_id | #83 (b) |
| Cursor | holds only ids; length independent of stored text; scope bound to `group_by` and every filter | #83 (b), #89 |
| CSV (#84) | whole result set, no `limit`/`cursor` (ignored); cap 100,000 data rows, over it 400 before any byte; header row = JSON field names in TS §7.1 order; UTF-8 no BOM, CRLF, RFC 4180 quoting; `Content-Type: text/csv; charset=utf-8`; `Content-Disposition: attachment; filename="packages.csv"` | #84 |
| Formula escape | prefix `'` when a cell starts with `=`, `+`, `-`, `@`, tab, CR, or any run of `str.isspace()` whitespace followed by `=`, `+`, `-`, `@`, tab or CR (so a leading whitespace run that holds a tab or CR is prefixed: `" \tabc"`, `" \rabc"`, `"\n\tx"`; a tab or CR after other text is not a trigger: `"a\tb"`); header cells too; escape before quoting | TS §6.3 L1142; #84 (d) as tightened by the lead's TASK-111 revision 1 ruling (`work/decisions.md` 2026-10-25, the literal TS §6.3 reading) |
| Trailing slash | a path with a trailing slash that matches no route (`/assets/<file>/`, `/api/v1/agents/`, `/healthz/`, slashed agent paths) → the standard problem+json 404 with the TS §6.3 headers and no `Location`; never a 307/308 | REQ-118; user ruling 2026-10-25 "Trailing-slash redirects turned off app-wide" (TASK-112 r1) |
| Version drill-down | the version click sends `name`, `version`, `arch` plus the search's `status`, `os`, `tag`, `host` and `agent_id` filters that were sent, without `group_by`, `q` or `version_op` | REQ-129 (3); lead ruling 2026-10-25 "TASK-124 version drill-down carries the active filters" (impl-web also carries `agent_id`) |
| G42 HTML rules (r1b) | every `.html` file in the build folder: also no `on<event>=` attribute and no `srcdoc=` attribute (any case, with or without a value); the JS bundle is not scanned for them | lead ruling 2026-10-25 "TASK-127 G42 bundle check" |
| Static UI | `GET /` → `index.html` `text/html; charset=utf-8`; `GET /assets/<file>` → files present at app creation, by extension: `.js` `text/javascript; charset=utf-8`, `.css` `text/css; charset=utf-8`, `.svg` `image/svg+xml`, `.png` `image/png`, `.ico` `image/x-icon`, `.woff2` `font/woff2`; no token; not in OpenAPI; no CORS; else problem+json 404 | #6 (M5 half); plan TASK-112; REQ-118 |
| TS §6.3 headers | `Strict-Transport-Security`, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` on every response | TS §6.3 L1140 |
| Token groups | user routes: `bsu_`, `bsk_` only; no token, `bsa_`, `bse_` → 401; viewer is the minimum role; restricted admin session (no TOTP) → 403 `totp_enrolment_required` | TS §6, §6.2 L1089, L1117 |
| User rate limit | 600 requests per minute per user; 601st → 429 | TS §6.3 L1136 |
| Agent status enum | `awaiting_approval`, `enrolled`, `online`, `stale`, `offline`, `decommissioned`; `RequestItem.kind` ∈ {`new`,`reenrol`}; `decision` ∈ {`approved`,`rejected`, null} | TS §5.2 L710; PD-29 (a) |
| UI session | `bsu_` only in one module variable; bearer on every call after sign-in; 401 carrying the current token clears the session; sign-out clears even if logout fails; reload starts signed out | REQ-120; plan TASK-116; #85 (c) |
| Problem messages | the plan TASK-116 table (403 `totp_session_required` → sign in again, never an API token; 503 `audit_sink_unavailable` → paused; 403 `forbidden` → role; 403 `totp_enrolment_required` → TOTP; 401; 429 with wait; 503 other; default with status) | REQ-126; #85 (b) |
| Hash routes | `#/hosts` (also `""`, `#`, `#/`), `#/hosts/<uuid>`, `#/packages`, `#/enrolment/requests`, `#/enrolment/tokens`, `#/account/totp`, `#/account/password`; anything else → hosts | plan TASK-116 |
| Navigation by role | viewer, operator: hosts, package search, account; admin: also enrolment requests, enrolment tokens; admin without TOTP: only TOTP and sign-out; non-admin without TOTP: offer after every sign-in, "Not now" → hosts | REQ-133; #85 (a) |
| Type-ahead (#32) | from 3 characters, 300 ms debounce, one `GET /api/v1/packages/search?q=<input>&group_by=package&limit=500`, at most 10 distinct names in response order; choosing sets `name`, clears `q`; stale responses ignored | REQ-130; #32 |
| Enrolment token form defaults | `{max_uses: 1, expires_in_hours: 24, allowed_cidrs: null, auto_approve: false}`; ranges 1–10,000 and 1–720 | REQ-124; TS §3.2 |
| Bundle (G42) | built `index.html`: no `<script>` without `src`, no `<style>`, no `style=`, no URL with a scheme or `//` | REQ-119; TS §6.3 L1140 |

## Gate map

| Gate | Checks |
| --- | --- |
| G1 ruff (S608, `re` ban) | CHK-M5-306 |
| G2 ruff format | CHK-M5-307 |
| G3 mypy --strict | CHK-M5-308 |
| G4 pip --require-hashes | CHK-M5-309 |
| G5 coverage of `bm/services` ≥ 85 % (W) | CHK-M5-310 |
| G6 OpenAPI export diff | CHK-M5-302 (and the last row of every manager route task) |
| G12 web lint | CHK-M5-311 |
| G13 web typecheck | CHK-M5-312 |
| G14 web format:check | CHK-M5-313 |
| G15 web tests | CHK-M5-314 |
| G16 client regeneration | CHK-M5-245, CHK-M5-262, CHK-M5-315 |
| G18 full W run, 0 skipped | CHK-M5-316 |
| G42 build and bundle check | CHK-M5-170 to -173, CHK-M5-317 |
| G43 search query, repository, route | CHK-M5-010 to -079, CHK-M5-120 to -149 |
| G44 CSV escape and route | CHK-M5-080 to -099, CHK-M5-150 to -169 |
| G45 static serving | CHK-M5-100 to -119 |
| G46 M5 security suite and route walk | CHK-M5-300, -301, -303 to -305 |

## TP-M5-01: enum types (TASK-108, REQ-117) — `manager/tests/test_user_enums.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-001 | CODE | In the exported document (`manager/openapi.json` and `create_app().openapi()`), `AgentItem.status`, `AgentDetailItem.status` and the enrolment `MatchItem.status` each resolve to an `enum` of exactly the six `agent_status` values (set equality, no extra, none missing); the values equal the CHECK constraint of `agent.status` in TS §5.2 L710 (parsed from the spec text by the test) | W |
| CHK-M5-002 | CODE | `RequestItem.kind` enum is exactly {`new`, `reenrol`}; `RequestItem.decision` is exactly {`approved`, `rejected`} or null (nullable in the schema), matching the TS §5.2 CHECK constraints | W |
| CHK-M5-003 | APP | The M3 suites `test_agents_api_pg.py`, `test_agents_admin_api_pg.py`, `test_enrolment_requests_api_pg.py` pass unchanged (no file in them edited) | W |
| CHK-M5-004 | CODE | G6 after the re-export is byte-identical; `LoginResponse.role` and `UserItem.role` stay plain strings (PD-29 (a)) | L |
| CHK-M5-005 | APP | A response whose agent row holds each of the six statuses serialises; the response model refuses a seventh value (unit, model level) | W |

## TP-M5-02: query parsing (TASK-109, REQ-113) — `manager/tests/test_package_query.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-010 | CODE | `q=ab` refused naming `q`; `q=abc` accepted; `q` of three spaces accepted; `q=%%%` (3 raw characters) accepted | W |
| CHK-M5-011 | CODE | `q` with `name` refused naming both (`name`, `q`) | W |
| CHK-M5-012 | CODE | `version_op=lt` without `version` refused naming `version` and `version_op`; every one of the five ops with a valid `version` accepted with the right `VersionOp` | W |
| CHK-M5-013 | CODE | `version_op=ne`, `LT`, `status=removed`, `status=Installed`, `group_by=name`, `group_by=PACKAGE` each refused naming that parameter; `status` absent and `installed` give the installed statuses, `any` gives none (status=any) | W |
| CHK-M5-014 | CODE | `status=installed` statuses are exactly {`install ok installed`, `hold ok installed`, `deinstall ok installed`} (user answers to #83 (f)) | W |
| CHK-M5-015 | CODE | `os=ubuntu` → `os_id=ubuntu`, no version; `os=ubuntu:24.04` → both; refused: `:24.04`, `ubuntu:`, `a:b:c`, a 33-character `os_id`, a 17-character version; at limits (32 and 16, total 49) accepted | W |
| CHK-M5-016 | CODE | `agent_id`: lower and upper-case hyphenated UUID accepted (normalised to a `UUID`); refused: `not-a-uuid`, braces, `urn:uuid:…`, the 32-digit form, hyphens misplaced, a non-hex letter, 35 and 37 characters, a non-ASCII digit | W |
| CHK-M5-017 | CODE | Each text parameter at its #83 (h) limit accepted and one character over refused naming it: `q` 255/256, `name` 255/256, `version` 255/256 (valid Debian version at 255), `host` 255/256, `arch` 16/17, `tag` 64/65, `os` 49/50; limits are characters, so a 255-character non-ASCII `name` is accepted | W |
| CHK-M5-018 | CODE | Empty value refused for each of `q`, `name`, `version`, `version_op`, `arch`, `status`, `os`, `tag`, `host`, `agent_id`, `group_by` (#88 (a)) | W |
| CHK-M5-019 | CODE | U+0000 refused in each text parameter (`q=abc\x00`, `name`, `version`, `arch`, `os`, `tag`, `host`) (#88 (b)) | W |
| CHK-M5-020 | CODE | Every distinct version in `debversion_pairs.tsv` is accepted as `version` (with and without `version_op`) | W |
| CHK-M5-021 | CODE | Malformed versions refused naming `version`: `1.0 beta`, `a1`, `1:`, `:1.0`, `1.0-`, `-1`, `1:a1`, `x:1.0`, `99999999999:1.0` (epoch > 2,147,483,647), `1.0-a_b`, `1.0\t`, `١.0` (non-ASCII digit), `1.0-ü`; accepted edge forms: `0:1.0`, `2147483647:1`, `1.0-1-2` (revision after the last `-`), `1:1.0:2` (`:` in upstream with an epoch), `1.0+dfsg~rc1-0ubuntu1` | W |
| CHK-M5-022 | CODE | Unknown parameters ignored; refusal messages carry parameter names only (sorted), never the value (a canary value never appears in `str(exc)` or `exc.args`) | W |
| CHK-M5-023 | CODE | `cursor_scope()` equal for equal queries; different when any single `SearchFilter` field or `group_by` changes (one case per field); fixed length, below 512 | W |
| CHK-M5-024 | CODE | Normalised fields: `q`, `name`, `version`, `arch`, `tag`, `host` unchanged (case kept); `os` split; `agent_id` a `UUID` | W |
| CHK-M5-025 | CODE | No `re` import in `bm/services/packages/query.py` (G1 ban) | L |

## TP-M5-03: repository on PostgreSQL (TASK-110, REQ-114, REQ-115) — `manager/tests/test_package_repo_pg.py`, `manager/tests/package_fleet.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-040 | APP | Fleet builds as specified (≥ 20 hosts, two Ubuntu versions and Debian 12, tags, multi-arch, epoch, `~`, `1.0`/`1.0-0`, three statuses, a decommissioned and an awaiting-approval host holding rows, hostile names, 255-character non-ASCII name and hostname) | W |
| CHK-M5-041 | APP | Each filter alone (`q`, `name`, `version` exact, `version`+each op, `arch`, `statuses` installed and any, `os_id`, `os_id`+version, `tag`, `host`, `agent_id`) returns exactly the oracle set for rows, package groups and host groups | W |
| CHK-M5-042 | APP | Every pair of the filter kinds returns exactly the oracle set (rows shape; package and host shapes on a sample of pairs that includes every filter) | W |
| CHK-M5-043 | APP | One five-filter combination (`q`, `version`+`ge`, `arch`, `os`, `tag`) equals the oracle for all three shapes | W |
| CHK-M5-044 | APP | `version_op` with each of the five operators over ≥ 50 pairs from `debversion_pairs.tsv` agrees with dpkg (including `1:1.0 > 2.0`, `1.0~rc1 < 1.0`, `1.0 = 1.0-0` under `eq`) | W |
| CHK-M5-045 | APP | `version` alone is an exact text match (`1.0` does not return `1.0-0`), while `version_op=eq` is Debian equality (returns both) | W |
| CHK-M5-046 | APP | `statuses` installed excludes `deinstall ok config-files` and `install ok unpacked` and includes `hold ok installed` and `deinstall ok installed`; any includes all five | W |
| CHK-M5-047 | APP | `decommissioned` host's rows never appear (also with `agent_id` of that host → empty); `awaiting_approval` and the other statuses appear | W |
| CHK-M5-048 | APP | `q` matches case-insensitive substrings (`SSL` finds `openssl`) and trigram-similar names at the default threshold (oracle uses the `pg_trgm` similarity rule computed in Python, or the threshold value read from `show pg_trgm.similarity_threshold` and the similarity from the oracle's own trigram function) | W |
| CHK-M5-049 | APP | Literal wildcards: `q=%_\'";--` matches only names containing that text, no SQL error; `q=a_c` does not match `abc`; `q=10%` does not match `100`; `host=_` matches only hostnames with `_`; `host=%` matches only hostnames with `%`; a backslash in `q` matches literally | W |
| CHK-M5-050 | APP | `host` is case-insensitive (`WEB-0` finds `web-01`) | W |
| CHK-M5-051 | APP | `tag` exact (prefix does not match); `arch` exact; `name` exact (case-sensitive) | W |
| CHK-M5-052 | APP | Shapes: rows carry exactly the TS §7.1 fields plus the `package_id` anchor; `host_count` = distinct hosts holding that (name, version, architecture) under the same filters; `package_count` = matching rows of that host | W |
| CHK-M5-053 | APP | Order: each shape's full list (walked by paging) equals the oracle sorted by the #83 (b) keys with the Debian comparator from the corpus rules | W |
| CHK-M5-054 | APP | Keyset paging N + 1 items with `limit=N` (several N, including 1) returns each item exactly once in order, all three shapes, including across `1.0`/`1.0-0` and with the 255-character non-ASCII name and hostname on a page boundary | W |
| CHK-M5-055 | APP | `AnchorGone` when the anchor's package row (package shape and rows shape) or agent row (host shape, rows shape) no longer exists | W |
| CHK-M5-056 | APP | Read-only: table row counts and contents of `package`, `agent_package`, `agent`, `agent_tag`, `os_info`, `inventory_snapshot`, `audit_log` unchanged after a full query sweep | W |
| CHK-M5-057 | CODE | G1 (ruff S608) passes on `bm/repositories/packages.py` | L |
| CHK-M5-058 | APP | Hostile names come back byte for byte (`<script>…`, `=HYPERLINK(…)`, the 255-character non-ASCII name) | W |
| CHK-M5-059 | APP | **#87 probe (finding, reported to `main`, not a TASK-110 failure):** as `bitscan_app` insert `package` rows with versions `1.0 beta`, `a1`, `1:`, `1.0-`, `:1`, `1.0-ü` next to `1.0` of the same name; record whether the INSERT (with the `ix_package_name_debver` expression index), `ORDER BY version::debversion`, `version::debversion < '2.0'` and the repository rows/package queries raise | W |

## TP-M5-04: CSV escaping and quoting (TASK-111, REQ-116) — `manager/tests/test_csv_export.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-080 | CODE | One leading `'` for each trigger: `=1`, `+1`, `-1`, `@a`, `\t1`, `\r1` | W |
| CHK-M5-081 | CODE | Whitespace then trigger, for each of `=`, `+`, `-`, `@` and each whitespace kind (`" "`, `"  "`, `"\t "`, `"\n"`, U+00A0, U+2003, U+3000, `\x0b`, `\x0c`, `\x1c`): exactly one `'` prefixed to the whole cell | W |
| CHK-M5-082 | CODE | Unchanged: `a=b`, `1-2`, `'=x`, `""`, `plain`, `  plain`, `x@y`, a lone space | W |
| CHK-M5-083 | CODE | RFC 4180: a cell with `,`, `"`, CR or LF is double-quoted with `"` doubled, after the prefix; `=HYPERLINK("http://x")` → `"'=HYPERLINK(""http://x"")"`; `-1,2` → `"'-1,2"` | W |
| CHK-M5-084 | CODE | Line ends CRLF, no BOM, UTF-8; header row escaped like data; non-string cells (ints, UUIDs) written as text | W |
| CHK-M5-085 | CODE | Round trip: Python `csv.reader` reads back the escaped cells exactly (prefix kept) for a corpus including hostile and non-ASCII values | W |
| CHK-M5-086 | CODE | The escape is one public function the writer calls (a plant removing the `-` trigger from that function turns CHK-M5-080 red: CHK-M5-331) | W |

## TP-M5-05: static UI serving (TASK-112, REQ-118) — `manager/tests/test_webui_serving.py`, `manager/tests/test_invariants_m3.py` (allow-list, after the M3 gate verdict)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-100 | APP | Fixture build folder (`tmp_path`: `index.html`, `assets/app-1a2b.js`, `assets/app-1a2b.css`, `.svg`, `.png`, `.ico`, `.woff2`): `/` → 200 `text/html; charset=utf-8` with the exact bytes; each asset → 200 with the exact bytes and its map content type | W |
| CHK-M5-101 | APP | Every static response, the 404s included, carries exactly the four TS §6.3 headers with the spec values | W |
| CHK-M5-102 | APP | 404 problem+json, no fixture byte in the body, for: `/assets/../app.py`, `/assets/..%2Fapp.py`, `/assets/%2e%2e%2fapp.py`, `/assets/%2e%2e/app.py`, `/assets/%2Fetc%2Fpasswd`, `/assets/a%5Cb.js`, `/assets/..\app.py`, an absolute path, `/assets/sub/x.js` (a real sub-folder file), `/assets/`, `/assets`, `/index.html`, `/favicon.ico`, `/assets/x.map`, `/assets/x.txt`, `/assets/.hidden.js`, `/assets/app-1a2b.JS` (case), a 129-character name | W |
| CHK-M5-103 | APP | A file added to `assets/` after `create_app`, and an existing file rewritten after it, are not served / still serve the original bytes | W |
| CHK-M5-104 | APP | A symlink in `assets/` (to a file outside the build) and a symlinked `index.html` are not served (Linux) | W |
| CHK-M5-105 | APP | No response holds an `Access-Control-Allow-*` header: `GET /`, an asset, a 404, and `OPTIONS /` and `OPTIONS /assets/x.js` with an `Origin` header (405 or 404, problem body) | W |
| CHK-M5-106 | APP | No token needed on `/` and assets; a bad `Authorization` header (garbage, `bsa_`) on them changes nothing and is not counted as a failed token check | W |
| CHK-M5-107 | APP | `/api/v1/unknown`, `/api/v1/`, `/unknown`, `/hosts` → the normal problem+json 404, never `index.html` | W |
| CHK-M5-108 | APP | With an empty build folder or a missing one: `/` and `/assets/x.js` → 404; `/healthz` and an authenticated API route still answer as before | W |
| CHK-M5-109 | CODE | `create_app().openapi()` has no `/` or `/assets/{name}` path; G6 byte-identical with and without a build folder present | L, W |
| CHK-M5-110 | APP | `serve` with no build folder starts, logs exactly one line that the UI is not built, and `/` answers 404 (real process, W) | W |
| CHK-M5-111 | APP | Route walk (G34): the only operations beyond the TS §6.1/§6.2, health and #70 routes are `GET /` and `GET /assets/{name}`, both `GET`, neither reads a query parameter (allow-list edit in `test_invariants_m3.py` after the M3 gate verdict) | W |
| CHK-M5-112 | APP | Query strings on `/` and assets are ignored (same bytes) and `HEAD /` is not a registered route | W |
| CHK-M5-113 | APP | TASK-112 r1 (user ruling 2026-10-25): a trailing-slash path that matches no route (`/assets/<file>/`, `/assets/`, `//`, `/healthz/`, `/readyz/`, slashed user and agent API paths incl. `POST /api/v1/auth/login/` and `POST /api/v1/agent/enroll/`) sent with `Host: evil.example` → problem+json 404 with the four TS §6.3 headers, no `Location`, no CORS; every CHK-M5-102 probe is the 404 (no 307/308 any more); the real `serve` gives 404 and no `Location` for `/assets/<file>/`, `/api/v1/agents/`, `/healthz/` | W |

## TP-M5-06: search route integration (TASK-113, REQ-113 to REQ-115) — `manager/tests/test_package_search_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-120 | APP | Every REQ-113 (1) refusal through the API: 400 problem+json, `type` `invalid_request`, `detail` names `query.<param>`, and the sent value (a canary) is not in the body | W |
| CHK-M5-121 | APP | `limit=0`, `limit=501`, `limit=abc` refused; omitted gives 50 items when ≥ 51 exist; `limit=500` accepted | W |
| CHK-M5-122 | APP | The three shapes have exactly their keys (no `package_id`), on the fixture fleet, and equal the oracle sets for a representative filter set | W |
| CHK-M5-123 | APP | Paging N + 1 with `limit=N` through the API for all three shapes returns each item once in order, including `1.0`/`1.0-0` and the 255-character non-ASCII name and hostname on a boundary; each `next_cursor` length is independent of stored text (≤ the fixed maximum) | W |
| CHK-M5-124 | APP | A cursor reused with one filter changed (one case per filter), with another `group_by`, and a tampered cursor → 400 `query.cursor`; a cursor whose anchor package or agent was removed → 400 | W |
| CHK-M5-125 | APP | Empty result → exactly `{"items": [], "next_cursor": null}`; last page `next_cursor` null; unknown `agent_id` → empty, not 404 | W |
| CHK-M5-126 | APP | Token groups: no token, `bsa_`, `bse_`, garbage → 401; viewer `bsk_`, viewer session, operator and admin sessions → 200; a restricted admin session (no TOTP) → 403 `totp_enrolment_required` | W |
| CHK-M5-127 | APP | Hostile package names and hostnames come back byte for byte as JSON strings | W |
| CHK-M5-128 | APP | After 50 searches (mixed shapes, filters, pages and refusals) `audit_log` and every inventory table are unchanged | W |
| CHK-M5-129 | APP | The 601st request of one user within a minute (fake clock) → 429 with `Retry-After` | W |
| CHK-M5-130 | APP | `q=%_\'";--` and `host=_` through the API: literal match, 200, no SQL error | W |
| CHK-M5-131 | APP | An invalid `version` (with and without `version_op`) answers 400, never 500 | W |
| CHK-M5-132 | APP | U+0000 (`%00`) in any text parameter answers 400, never 500 | W |
| CHK-M5-133 | CODE | The document lists the eleven parameters (plus `limit`, `cursor`) with their enums and the #83 (h) max lengths, and the 200 response is the three-page union; contract and error-contract tests pass; G6 | L, W |
| CHK-M5-134 | APP | Route walk (G34) passes with the package route | W |

## TP-M5-07: CSV route integration (TASK-114, REQ-116, REQ-115) — `manager/tests/test_package_search_csv_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-150 | APP | For all three shapes and several filter sets, the CSV data rows equal the concatenated JSON items of every page in the same order (cells as text: UUID lower-case, counts decimal), after un-escaping nothing: the expected rows are the JSON values passed through an independent escape oracle | W |
| CHK-M5-151 | APP | Header row = `name,version,architecture,status,agent_id,hostname`, `name,version,architecture,host_count`, `agent_id,hostname,package_count` | W |
| CHK-M5-152 | APP | A package named `=HYPERLINK("http://x")` appears as `"'=HYPERLINK(""http://x"")"`; `-x`, `@x`, `+x`, tab and CR names escaped; CRLF line ends, no BOM | W |
| CHK-M5-153 | APP | Over the cap: 400 problem+json (not `text/csv`), no CSV header in the body; at the cap exactly: 200 (cap lowered through the service's `cap` argument with a fake `ExportStore` in a unit test; the 100,000 constant asserted once) | W |
| CHK-M5-154 | APP | Headers exactly `Content-Type: text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="packages.csv"`, plus the TS §6.3 headers | W |
| CHK-M5-155 | APP | `limit` and `cursor` are ignored (same body with and without them) | W |
| CHK-M5-156 | APP | Same refusals as REQ-113 (one case per rule) answer 400 problem+json | W |
| CHK-M5-157 | APP | Token groups as CHK-M5-126 on `/packages/search.csv` | W |
| CHK-M5-158 | APP | Nothing written (tables and `audit_log` unchanged); counts as one request in the 600/min limit | W |
| CHK-M5-159 | CODE | The document gives the 200 as `text/csv` with a string schema and no `application/json`; G6 | L |
| CHK-M5-160 | APP | Empty result → header row only | W |

## TP-M5-08: build (TASK-115, REQ-119) — evidence only

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-170 | CODE | `npm ci --ignore-scripts && npm run build` exits 0 and writes `index.html` and its assets into the PD-28 (b) folder (`bm/webui/`) | L (and W/CI Linux) |
| CHK-M5-171 | CODE | Bundle check on the built `index.html`: no inline `<script>`, `<style>`, `style=`, scheme or `//` URL | L |
| CHK-M5-172 | CODE | The check turns red on each plant in a copy: inline `<script>`, `<style>`, `style=` attribute, `https://` font link | L |
| CHK-M5-173 | CODE | `npm ls --omit=dev --all` lists only React, React DOM, `openapi-fetch`, their dependencies and the PD-28 (e) QR library; Vite, Vitest, jsdom, Testing Library are dev-only and pinned in the lock | L |
| CHK-M5-174 | CODE | `npm run lint`, `typecheck`, `format:check`, `test` pass | L |
| CHK-M5-175 | CODE | Built JS and CSS also hold no `http://` / `https://` URL loading another origin (fetch, import, `url(...)`) | L |

## TP-M5-09: session core (TASK-116, REQ-120, REQ-126) — `w/src/app/session.test.ts`, `problems.test.ts`, `router.test.ts`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-180 | CODE | No request before `setSession` carries `Authorization`; after it, every request (GET, POST, DELETE, several paths) carries `Bearer <token>`; a second `setSession` swaps the token for the next request | L |
| CHK-M5-181 | CODE | A 401 carrying the current token clears the session; a 401 for a request sent with an older token does not clear the new session; a 401 with no session changes nothing; a 403 or 500 does not clear | L |
| CHK-M5-182 | CODE | `signOut()` with logout answering 204, 401, 500 and a network error: the session is cleared each time, logout called once | L |
| CHK-M5-183 | CODE | Spies on `Storage.prototype.setItem`, the cookie setter, `indexedDB.open` and every `console` method never receive the token (or any argument containing it) across set, requests, 401 and sign-out; `location.href` never contains it | L |
| CHK-M5-184 | CODE | `nextScreen` for each role × `totpEnrolled` (admin false → `totp-required`, viewer/operator false → `totp-offer`, true → `hosts`); `toRole` on `viewer`, `operator`, `admin`, `Admin`, `root`, `""` | L |
| CHK-M5-185 | CODE | `messageFor` for every row of the plan table; an unknown `type` gives the generic message with the status; no message text includes response text; the `totp_session_required` message does not mention an API token and its action is `sign-in-again` | L |
| CHK-M5-186 | CODE | `toProblem`: non-string `type`/`detail` → `about:blank`/null; non-problem body; `Retry-After` `7`, `0`, `-1`, `1.5`, an HTTP date, absent | L |
| CHK-M5-187 | CODE | `parseHash` for every row of the hash table plus unknown paths, extra segments, a non-UUID host id, a query part, an upper-case UUID (lower-cased); `formatHash(parseHash(formatHash(r)))` = `formatHash(r)` for every route; `isUuid` boundaries (35/36/37 characters, hyphen positions, non-hex, non-ASCII) | L |

## TP-M5-10: shared components (TASK-117) — `w/src/components/components.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-190 | CODE | `Pager` walks N + 1 items with page size N forwards and back, each item shown once, using only returned cursors; previous disabled on the first page, next on the last | L |
| CHK-M5-191 | CODE | `ProblemBanner` shows the REQ-126 message per `type` and a hostile `detail` as literal text (no element created) | L |
| CHK-M5-192 | CODE | `Confirm` calls its action only after confirmation, never on cancel, once per confirmation | L |
| CHK-M5-193 | CODE | Time format: null → "never"; an RFC 3339 value renders deterministically | L |

## TP-M5-11: sign-in (TASK-118, REQ-121) — `w/src/screens/SignIn.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-200 | CODE | Body is exactly `{username, password, totp_code}` with `totp_code: null` when empty and the string when filled; the TOTP field is shown | L |
| CHK-M5-201 | CODE | Two different 401 problems show the same message, which contains neither `detail` | L |
| CHK-M5-202 | CODE | 429 with `Retry-After: 7` shows a 7-second wait, button disabled until then (fake timers), enabled after | L |
| CHK-M5-203 | CODE | Password input `type="password"`; password and code cleared after each attempt (success and failure) | L |
| CHK-M5-204 | CODE | 503 shows "manager unavailable"; success calls `setSession` and `onSignedIn` with the REQ-133 next screen for each role/TOTP case | L |
| CHK-M5-205 | CODE | No request other than sign-in is sent before success; the password and token never reach storage or console | L |

## TP-M5-12: account (TASK-119, REQ-122, REQ-123) — `w/src/screens/Account.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-210 | CODE | Start posts `{}` to `/api/v1/auth/totp/enrol`; shows `secret` and `otpauth_uri` as text (and the QR if present) | L |
| CHK-M5-211 | CODE | Confirm with the right code posts `{totp_code}`; the next request carries the new token | L |
| CHK-M5-212 | CODE | 403 on confirm shows a wrong-code message and keeps the screen; 409 restarts enrolment | L |
| CHK-M5-213 | CODE | Replacement (`manage` mode with TOTP enrolled) sends exactly `{current_password, current_code}` first | L |
| CHK-M5-214 | CODE | After leaving the screen the secret is not in the DOM, any storage spy or console | L |
| CHK-M5-215 | CODE | Offer mode: "Not now" calls `onSkip` | L |
| CHK-M5-216 | CODE | Password change: mismatch or an 11-character new password sends nothing; a valid form sends the documented body once; 204 clears the session and calls `onChanged`; 403 shows the wrong-password message, keeps the form, clears password fields | L |

## TP-M5-13: enrolment tokens (TASK-120, REQ-124, REQ-126) — `w/src/screens/EnrolmentTokens.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-220 | CODE | Untouched form posts exactly `{max_uses: 1, expires_in_hours: 24, allowed_cidrs: null, auto_approve: false}` | L |
| CHK-M5-221 | CODE | The TS §3.2 hint (expected host count, `allowed_cidrs`) and the alert note (`auto_approve`, more than 100 uses) are present | L |
| CHK-M5-222 | CODE | The `bse_` token is in the DOM only on the creation result, with a copy button; after closing it is in neither DOM nor any storage spy; the list never shows a token | L |
| CHK-M5-223 | CODE | Revoke calls `DELETE /api/v1/enrollment-tokens/{token_id}` once after confirmation, none on cancel; the row then shows `revoked_at` | L |
| CHK-M5-224 | CODE | A 400 shows its `detail` as text; `totp_session_required` shows the sign-in-again prompt and no field asks for a token; `audit_sink_unavailable` shows the paused message | L |
| CHK-M5-225 | CODE | List pagination shows each token once; hostile text in fields renders as text | L |

## TP-M5-14: enrolment approval (TASK-121, REQ-125, REQ-126) — `w/src/screens/EnrolmentRequests.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-230 | CODE | Pending by default; decided on request (`state=decided`); each item shows hostname, source IP, `os_pretty_name`, kind, agent version, request time | L |
| CHK-M5-231 | CODE | A request with two matches shows both, with hostname, machine-id and status, flagged | L |
| CHK-M5-232 | CODE | Hostile hostname, match hostname and `os_pretty_name` render as literal text | L |
| CHK-M5-233 | CODE | Approve and reject call `POST …/{request_id}/approve` / `reject` once after confirmation, none on cancel; the list refreshes and the item leaves pending | L |
| CHK-M5-234 | CODE | 409 shows "already decided" and refreshes; `totp_session_required` and `audit_sink_unavailable` show their messages with no token field | L |

## TP-M5-15: host list (TASK-122, REQ-127, REQ-136) — `w/src/screens/Hosts.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-240 | CODE | N + 1 hosts with page size N: next and previous show each host once | L |
| CHK-M5-241 | CODE | Each of the six statuses shows its own distinct label; each row shows hostname, status, OS pretty name, agent version, last heartbeat, last inventory, tags, runner helpers | L |
| CHK-M5-242 | CODE | Removing one label from the status map fails `npm run typecheck` (plant in a copy) | L |
| CHK-M5-243 | CODE | Hostile hostnames and tags render as text; null `last_heartbeat_at` shows "never" | L |
| CHK-M5-244 | CODE | Clicking a row navigates to `{name: "host", agentId}` | L |
| CHK-M5-245 | CODE | G16 at that time: `npm run gen:api` gives no diff; `status` typed as the six-value union (type-level test) | L |

## TP-M5-16: host detail (TASK-123, REQ-128) — `w/src/screens/HostDetail.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-250 | CODE | Every REQ-128 field shown (identity, status, enrolment, last seen IP, token issue/expiry/revocation times, tags, helpers, every `os_info` field, IP addresses as a list, `raw` as indented JSON text, `collected_at`); no token value anywhere | L |
| CHK-M5-251 | CODE | Null `os_info` shows "No inventory yet"; null `last_snapshot` shows no change list | L |
| CHK-M5-252 | CODE | Added and removed lists equal the snapshot items | L |
| CHK-M5-253 | CODE | Hostile `raw` key and value shown as text inside the JSON | L |
| CHK-M5-254 | CODE | 404 shows "Host not found" | L |
| CHK-M5-255 | CODE | Package paging (`/agents/{id}/packages`) shows each package once with name, version, architecture, status, source, size, first and last seen | L |

## TP-M5-17: package search screen (TASK-124, REQ-129, REQ-136) — `w/src/screens/PackageSearch.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-260 | CODE | The form sends exactly the filled parameters (none empty); `version_op` only with a version; `q` and `name` not both | L |
| CHK-M5-261 | CODE | A `group_by=package` answer with two names and three versions renders as two name groups holding their versions and host counts | L |
| CHK-M5-262 | CODE | G16: `gen:api` no diff; `UserPathsArePrefixed` passes with both package paths; type-level calls to both routes | L |
| CHK-M5-263 | CODE | Clicking a version requests `name`, `version`, `arch` without `group_by` and lists those hosts; clicking a host navigates to `#/hosts/<agent_id>` | L |
| CHK-M5-264 | CODE | Hostile package names render as text; a 400 shows its `detail` | L |
| CHK-M5-265 | CODE | Paging shows each group once; per-host view (`group_by=host`) renders | L |

## TP-M5-18: type-ahead and CSV download (TASK-125, REQ-130, REQ-131) — `w/src/components/TypeAhead.test.tsx`, `w/src/app/download.test.ts`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-270 | CODE | Fake timers: 2 characters send nothing; 5 characters typed quickly send one request, after 300 ms, exactly `q=<input>&group_by=package&limit=500` | L |
| CHK-M5-271 | CODE | At most 10 distinct names, in response order | L |
| CHK-M5-272 | CODE | A slower earlier response arriving after a later one is ignored | L |
| CHK-M5-273 | CODE | Choosing a suggestion sets `name` and clears `q` | L |
| CHK-M5-274 | CODE | Export fetches `/api/v1/packages/search.csv` through the client with the bearer header and the visible filters, without `limit` or `cursor` | L |
| CHK-M5-275 | CODE | The saved Blob's bytes equal the response body; the Blob URL is revoked after the download | L |
| CHK-M5-276 | CODE | A 400 shows its `detail` as text | L |

## TP-M5-19: app shell (TASK-126, REQ-133, REQ-120, REQ-122) — `w/src/app/App.test.tsx`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-280 | CODE | Per role the navigation shows exactly the REQ-133 entries | L |
| CHK-M5-281 | CODE | A viewer opening `#/enrolment/requests` and `#/enrolment/tokens` sees "not available for your role" and no request to those routes is sent | L |
| CHK-M5-282 | CODE | Admin with `totp_enrolled: false` reaches only TOTP and sign-out (every other hash shows the TOTP screen; no request to other routes) | L |
| CHK-M5-283 | CODE | Viewer with `totp_enrolled: false` sees the offer after sign-in; "Not now" leads to the host list | L |
| CHK-M5-284 | CODE | Sign-out clears the session even when logout fails; a 401 on any screen shows sign-in | L |
| CHK-M5-285 | CODE | Reload (fresh module state, `vi.resetModules`) starts at sign-in | L |
| CHK-M5-286 | CODE | Sign-in → three screens → sign-out with the storage, cookie, IndexedDB and console spies: the token never reaches any of them; `location.href` never contains it (REQ-120 (1)) | L |
| CHK-M5-287 | CODE | Hostile text in every displayed string field of host list, host detail, approval, token and package screens renders literally, no `script`/`img` element (REQ-132 (1)) | L |

## TP-M5-20: web CI (TASK-127, REQ-134) — evidence only

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-290 | CODE | `.github/workflows/web.yml` runs build and the G42 check after lint, typecheck, format, test and client regeneration, on PRs touching `web/` | L (static read), CI |
| CHK-M5-291 | CODE | Each G42 plant and a failing build turn the job red (CI run on a throwaway branch, or the same step script run locally on the plants) | CI / L |
| CHK-M5-292 | CODE | Every action pinned to a full commit SHA as in M0; actionlint clean | L |

## TP-M5-21: README walk (TASK-128, REQ-135) — evidence only

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-295 | APP | Each new README section followed against a WSL manager serving the built UI behaves as written (build, open, first sign-in and TOTP, token, approval, host pages, search parameters, CSV and escaping) | W |
| CHK-M5-296 | CODE | No real token or secret, task id or process note in the README | L |

## TP-M5-22: M5 security and invariants suite (G46) and gate checks — `manager/tests/test_security_m5.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M5-300 | APP | Route walk (G34) with the package and static routes: no route queues a command or disables inventory; static routes `GET` only, no query input | W |
| CHK-M5-301 | APP | Token groups on both package routes: no token, `bsa_`, `bse_` → 401; viewer `bsk_` → 200 | W |
| CHK-M5-302 | CODE | G6: export then `git diff --exit-code -- manager/openapi.json` plus untracked check | L |
| CHK-M5-303 | APP | Canary sweep: hostile package names, CSV cells and tokens used in M5 tests never appear in any application log record or journald line captured by the run | W |
| CHK-M5-304 | APP | Served-bundle check against a real `serve` in WSL with the TASK-115 build: `/` 200, every asset `index.html` references answers 200 with the TS §6.3 headers and its content type | W |
| CHK-M5-305 | APP | PD-28 (f) browser walk-through by the user (sign-in, TOTP, token, approve, hosts, search, CSV) recorded by `main` | user |
| CHK-M5-306 | CODE | G1 `ruff check manager`; plants: f-string query in `bm/repositories/packages.py`, `import re` in `bm/services/packages/query.py` | L |
| CHK-M5-307 | CODE | G2 `ruff format --check manager`; plant: misformatted line in `bm/api/webui.py` | L |
| CHK-M5-308 | CODE | G3 `mypy --strict`; plant: untyped function in `bm/services/packages/csv_export.py` | L |
| CHK-M5-309 | CODE | G4 `pip install --require-hashes` of both locks; plant: every hash of one dev package altered | L |
| CHK-M5-310 | CODE | G5 coverage of `bm/services` ≥ 85.00 % (precision 2) on the W run; plant: an untested function in `bm/services/packages/search.py` sized from the clean report | W |
| CHK-M5-311 | CODE | G12 `npm run lint`; plants: `dangerouslySetInnerHTML` in `Hosts.tsx`, `sessionStorage.setItem` in `session.ts`, a `fetch(` in `download.ts` | L |
| CHK-M5-312 | CODE | G13 `npm run typecheck`; plant: a status label removed from `StatusBadge.tsx` | L |
| CHK-M5-313 | CODE | G14 `npm run format:check`; plant: misformatted line in `PackageSearch.tsx` | L |
| CHK-M5-314 | CODE | G15 `npm test` (every M5 UI suite) green; web rows of the mutation table red | L |
| CHK-M5-315 | CODE | G16 G6 + `npm run gen:api` + diff and untracked check on `manager/openapi.json web/src/api/`; plant: `openapi.json` changed without regenerating | L |
| CHK-M5-316 | APP | G18 full W run `CI=true pytest -n auto --cov=bitscan_manager/services --cov-fail-under=85`: all pass, 0 skipped | W |
| CHK-M5-317 | CODE | G42 at the gate on the clean tree | L |

## Mutation table (CHK-M5-320 to -354)

As `work/tasks.md` "M5 mutation table". Each is planted in a throwaway copy and must turn the named gate red for the planted reason; the named test is the one expected to fail.

| CHK | Plant | Red in | Expected failing checks |
| --- | --- | --- | --- |
| CHK-M5-320 | `version_op` compared as text | G43 | CHK-M5-044 |
| CHK-M5-321 | `status` defaults to `any` | G43 | CHK-M5-013, -046 |
| CHK-M5-322 | `q` with `name` accepted | G43 | CHK-M5-011 |
| CHK-M5-323 | `version_op` without `version` accepted | G43 | CHK-M5-012 |
| CHK-M5-324 | 2-character `q` accepted | G43 | CHK-M5-010 |
| CHK-M5-325 | `%`/`_` in `q` not escaped | G43 | CHK-M5-049 |
| CHK-M5-326 | `%`/`_` in `host` not escaped | G43 | CHK-M5-049 |
| CHK-M5-327 | text tie-breaker dropped | G43 | CHK-M5-054 |
| CHK-M5-328 | cursor scope ignores filters | G43 | CHK-M5-124 |
| CHK-M5-329 | #83 (e) agent scope removed | G43 | CHK-M5-047 |
| CHK-M5-330 | invalid `version` reaches the cast (500) | G43 | CHK-M5-021, -131 |
| CHK-M5-331 | `-` trigger removed | G44 | CHK-M5-080 |
| CHK-M5-332 | whitespace-then-trigger not escaped | G44 | CHK-M5-081 |
| CHK-M5-333 | CSV route bypasses the shared escape | G44 | CHK-M5-152 |
| CHK-M5-334 | CSV cap removed or checked after streaming | G44 | CHK-M5-153 |
| CHK-M5-335 | `/packages/search` needs no role or no token | G46 | CHK-M5-126, -301 |
| CHK-M5-336 | `bsa_` accepted on `/packages/search.csv` | G46 | CHK-M5-157, -301 |
| CHK-M5-337 | `/assets/{name}` resolves `..` or an encoded slash | G45 | CHK-M5-102 |
| CHK-M5-338 | static route outside the header middleware | G45 | CHK-M5-101 |
| CHK-M5-339 | catch-all returns `index.html` | G45 | CHK-M5-102, -107 |
| CHK-M5-340 | `Access-Control-Allow-Origin` on static responses | G45 | CHK-M5-105 |
| CHK-M5-341 | static routes in the OpenAPI document | G6 | CHK-M5-109 |
| CHK-M5-342 | token in `sessionStorage` (variable key) | G15 | CHK-M5-183 |
| CHK-M5-343 | bearer omitted on one route | G15 | CHK-M5-180 |
| CHK-M5-344 | 401 does not clear the session | G15 | CHK-M5-181 |
| CHK-M5-345 | hostname via `dangerouslySetInnerHTML` | G12, G15 | CHK-M5-243, -311 |
| CHK-M5-346 | created `bse_` kept after close | G15 | CHK-M5-222 |
| CHK-M5-347 | `totp_session_required` → API-token prompt | G15 | CHK-M5-185, -224 |
| CHK-M5-348 | TOTP secret logged to the console | G15 | CHK-M5-214 |
| CHK-M5-349 | admin without TOTP opens the host list | G15 | CHK-M5-282 |
| CHK-M5-350 | inline `<script>` in `w/index.html` | G42 | CHK-M5-171 |
| CHK-M5-351 | CSV download as a link without the bearer | G15 | CHK-M5-274 |
| CHK-M5-352 | cursor carries sort values | G43 | CHK-M5-123 |
| CHK-M5-353 | U+0000 reaches the database (500) | G43 | CHK-M5-019, -132 |
| CHK-M5-354 | 401 for an older token clears the current session | G15 | CHK-M5-181 |
| CHK-M5-361 (extra) | the export streams in another order than the pages | G44 | CHK-M5-150 |
| CHK-M5-362 (extra) | `Content-Disposition` dropped from the CSV answer | G44 | CHK-M5-154 |
| CHK-M5-363 (extra) | the CSV route honours a `limit` parameter | G44 | CHK-M5-155 |
| CHK-M5-364 (extra) | `redirect_slashes` back on (kwarg removed, or `True`) | G45 | CHK-M5-113 |

Extra plants for the top risks (one review round, speed rules): **SQL injection** on TASK-110/113 (a filter value interpolated with `sql.SQL(value)` or an f-string: CHK-M5-049, -130 with `q=a' OR '1'='1` and `host=x'--` must stay literal, and G1 red), **CSV formula** on TASK-111/114 (escape applied after quoting, so `"=…` passes: CHK-M5-083), **auth bypass** on TASK-112 (the static router gains a path converter `{name:path}` serving from disk: CHK-M5-102, -103).
