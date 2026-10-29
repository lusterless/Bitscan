# TP-M7-30 TEST (M7 importer security suite): PASS

Tester: tester-m7d, 2026-10-28. REQ-177 (1), (2); CHK-M7-285. Spec: TS §8.3 Security L1283 (importer half), §8.1 L1241, L1251, L1253; §4.1 L522, L530; §6 L1056; §6.2 L1084, L1104, L1105; §5.3 L1051; §8.4 L1289 to L1291; SR §4.1 BIT001, BIT015, BIT102; #1, #99 (b), (d), #100, #101, #102 (b). BIT102 uses only the cases settled before TASK-146 r2 (lead, 2026-10-28): `rm x` is rejected and the shipped samples pass.

**New tester file:** `manager/tests/test_security_m7.py` (16 test functions, 38 cases).
- It runs end to end through the real routes, the real `CatalogService`, start-up sequence, rebuild worker, sink gate and auth.
- It uses a database of the module's own and a temporary bits folder, with the `bits/tests/` fixtures (BIT001 XML set, `db/bit015-*`, `hostile_names` forms) and `bits/samples/*.bit`.

**Helper change:** `manager/tests/catalog_api.py` gained `RecordingSink` and an optional `sink=` argument on `make_env`, so a test can check that alerts reach the sink. Nothing else changed, and the three route suites were re-run on it.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| d0 (W, `/root/bstest-m7d`, `CI=true`, `-n 0`, `PYTHONPATH` pinned) | `pytest tests/test_security_m7.py` | 37/38 passed, 1 failed, 0 errors, 0 skipped |
| d0 failure (test bug) | `test_agent_tokens_are_refused_on_every_m7_route`. Expected 401; actual 429 `rate_limited`: 24 failed token checks from one IP within a minute crossed the 20/min limit (TS §6.3). Fix: the test clock moves 61 s between token kinds, so at most 8 checks fall in a minute | fixed in the test |
| d1 (W) | that node id | 1/1 passed |
| plants (W, `-n 0`, throwaway copy `/root/bstest-m7d-mut`, every edited file restored after each, copy deleted after) | `pytest tests/test_security_m7.py -k <rows>` | 24/24 plants red |
| r0 (W, clean tree re-synced) | `pytest tests/test_security_m7.py tests/test_policy_import_api_pg.py tests/test_policy_delete_api_pg.py tests/test_rebuild_api_pg.py tests/test_openapi.py tests/test_invariants_m3.py` | 236/236 passed, 0 failed, 0 errors, 0 skipped |
| static (L, whole tree) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 312 files formatted; no issues in 312 source files |

- **Product files under test** (sha256 prefix): `openapi.json` 2eacec4e800031e4, `parse.py` 509307590fc318d5, `folders.py` 2fd4a1340dbabac1, `uploads.py` 4acc0e2d09cc385c, `pipeline.py` 2cc75d132d4f0fa3, `alerts.py` 3bbf0e48cc0d0c24, `bit102.py` fee8ac5e396ad920, `store_decide.py` 4db7c583f00a3dfd, `auth/dependencies.py` 1dfc6ef504308e33.
- **Subprocess imports:** every run and plant set `PYTHONPATH` to the tree under test, so the `db migrate` console-script subprocess never used the shared venv's editable install.
- **Containers:** none of mine are left (`docker ps -a`).

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-285 XML upload | APP | W | r0 | PASS | Eleven fixtures, each uploaded by an admin `bsk_`: `xxe-file`, `xxe-url`, `parameter-entity`, `parameter-entity-internal`, `external-dtd-file`, `external-dtd-url`, `billion-laughs`, `quadratic-blowup`, `dtd-only`, `dtd-element-decl`, `undefined-entity`. Each gives 200 `rejected` with exactly `[BIT001]`. Nothing is stored (empty bits tree) and no policy of the fixture's name exists. A process-wide audit hook saw no `open` of the canary file, from any thread. A local TCP listener on the fixture's port saw no connection. The canary text is in neither the response, the stored `errors` nor any log record. Each finishes in under 10 s | 2026-10-28 |
| CHK-M7-285 oversize | APP | W | r0 | PASS | A 5,242,881-byte upload gives 413 `too_large` with no `bit_import` row and nothing on disk (#99 (b)). A 5,242,881-byte server-folder file is a `rejected` BIT001 row at start-up (`auto`) and again in a rebuild (`rebuild`), and its policy never exists | 2026-10-28 |
| CHK-M7-285 XML folder | APP | W | r0 | PASS | `xxe`, `laughs`, `blowup`, `dtd` and `big` placed in the server folder. The start-up reconcile and then `POST /policies/rebuild` each write one `rejected` row per file with exactly `[BIT001]`, and the task result lists all five as `rejected`. The canary is never opened and is in no stored finding | 2026-10-28 |
| CHK-M7-285 symlink/FIFO | APP | W | r0 | PASS | Symlinks `link.bit`, `uploaded/link.bit` and `uploaded/policy-999999.bit` point at valid policy files outside the folder; FIFOs `fifo.bit` and `uploaded/fifo.bit` sit in the folders. A restart finishes its start-up, so a FIFO never blocks it, and a rebuild ends `succeeded`. None of the target policies is imported, no `bit_import` row is written (not even a rejected one), and no skipped path is in the task's `files`. The links are unchanged, and the targets keep their bytes and mtime | 2026-10-28 |
| CHK-M7-285 upload paths | APP | W | r0 | PASS | A symlink at `uploaded/.tmp-<id>-<sha>` makes the upload 503 with no row; its target keeps `keep`, and the stored v1 is unchanged (REQ-163 (2)). A symlink at `uploaded/policy-<id>.bit` is replaced by a regular file holding v3; its target keeps `keep` | 2026-10-28 |
| CHK-M7-285 client path | APP | W | r0 | PASS | Nine client names: `../../etc/passwd`, `/abs.bit`, `a/b.bit`, `..`, `../outside.bit`, `.tmp-1-<64 zeros>`, `policy-1.bit`, `uploaded/policy-1.bit`, `C:\Windows\x.bit`. A snapshot of the whole test directory before and after shows exactly one new file, `bits/uploaded/policy-<id>.bit` with the uploaded bytes, and no other file changed | 2026-10-28 |
| CHK-M7-285 route group | APP | W | r0 | PASS | The walk equals the OpenAPI document's eight M7 operations: `GET /policies`, `GET`, `PATCH` and `DELETE /policies/{id}`, `POST /policies/import`, `POST /policies/rebuild`, `GET /tasks/{id}`, `GET /imports`. On each of them, a random `bsa_`, the `bsa_` of an enrolled `online` agent (hash stored) and a `bse_` get 401 `unauthorized`. Catalog, `bit_import`, task, job, schedule and bits-tree state is unchanged, and the policy stays `enabled` | 2026-10-28 |
| CHK-M7-285 API tokens | APP | W | r0 | PASS | An admin `bsk_` gets 403 `totp_session_required` on `DELETE /policies/{id}` and on `POST /policies/rebuild`, with nothing changed. The same admin's TOTP session then gets 204 and 202 | 2026-10-28 |
| CHK-M7-285 non-admins | APP | W | r0 | PASS | Operator and viewer, with a session and with `bsk_`: upload gets 403 `forbidden`, and delete gets 403 (`forbidden` for sessions). Nothing changed | 2026-10-28 |
| CHK-M7-285 sink gate | APP | W | r0 | PASS | At 15:00 into a sink outage, delete and rebuild get 503 `audit_sink_unavailable` with nothing changed. After the queue drains, the delete gives 204 (#1) | 2026-10-28 |
| CHK-M7-285 logs | APP | W | r0 | PASS | Canaries placed in an `Execute`, a `PolicyDescription`, a `PluginDescription` and an `ExpectedResult`, plus a rejected `rm <canary>`. Then: upload, `GET /policies/{id}` (which does show the `Execute`, #98 (b)), PATCH disable and enable, rebuild, delete, and a failed check with a `bsa_`. None of the four canaries, the admin `bsk_`, the session token or the agent token appears in any log record (DEBUG) or on fd-level stdout/stderr. Log records exist, so the sweep has input | 2026-10-28 |
| CHK-M7-285 alerts | APP | W | r0 | PASS | The sequence upload, rejected upload, PATCH re-enable, rebuild, delete writes `policy_imported`, `policy_import_rejected`, `policy_reenabled`, `policy_rebuilt` and `policy_deleted` entries (`alert: true`). `bitscan_alerts_total{kind}` rises by exactly the number of entries of each kind. The `policy.import` entry has actor `user:<id>` and one `changed_executes` item with the full command, reason `new` and flags `[".ssh"]` (#100). Every kind reaches the sink (`RecordingSink` through the real shipper) | 2026-10-28 |
| CHK-M7-285 BIT102 | APP | W | r0 | PASS | `rm x` is rejected with BIT102 by upload (`manual`), at start-up (`auto`) and by rebuild (`rebuild`), and its policy never exists. Both `bits/samples/*.bit` upload as `success` with no BIT102 | 2026-10-28 |
| CHK-M7-285 BIT015 | APP | W | r0 | PASS | `db/bit015-owner.bit` succeeds. `db/bit015-claimer.bit` is rejected with BIT015, and the catalog, tasks, jobs, schedules and files are unchanged apart from its one `bit_import` row | 2026-10-28 |
| CHK-M7-320 | APP | W | plant: `parse.py` with every forbid off and an `ExternalEntityRefHandler` that reads `file://` paths (only the test's own temporary canary) | PASS (red) | 6 failed, among them `xxe-file`, `external-dtd-file`, `dtd-only`, `dtd-element-decl`. The other 5 (billion laughs, quadratic blow-up and others) stay refused by expat's own limits, a second layer | 2026-10-28 |
| CHK-M7-321 | APP | W | plant: `forbid_dtd=False` | PASS (red) | 5 failed: `external-dtd-file`, `external-dtd-url`, `dtd-only`, `dtd-element-decl`, the folder row | 2026-10-28 |
| CHK-M7-285-failopen | APP | W | plant: the DTD, entity and external-reference refusals return no finding | PASS (red) | 11 failed: ten XML upload cases and the folder row | 2026-10-28 |
| CHK-M7-323 | APP | W | plant: parser and folder read caps + 1 byte | PASS (red) | 1 failed: the folder row (`big.bit` not rejected) | 2026-10-28 |
| CHK-M7-324 | APP | W | plant: `bit` class 6 MiB and part cap + 1 | PASS (red) | 1 failed: `test_an_oversize_upload_is_413_with_no_row` | 2026-10-28 |
| CHK-M7-363 | APP | W | plant: discovery follows symlinks and `O_NOFOLLOW` dropped | PASS (red) | 1 failed: the symlink/FIFO row | 2026-10-28 |
| CHK-M7-285-fifo | APP | W | plant: discovery keeps any non-directory and the `S_ISREG` check dropped (O_NONBLOCK kept, so nothing hangs) | PASS (red) | 1 failed: the symlink/FIFO row | 2026-10-28 |
| CHK-M7-357 | APP | W | plant: the temp file opened `O_CREAT \| O_TRUNC`, no `O_EXCL` or `O_NOFOLLOW` | PASS (red) | 1 failed: the temp/final symlink row | 2026-10-28 |
| CHK-M7-358 | APP | W | plant: the stored file named after the client name (kept inside the folder) | PASS (red) | 8 failed: every client path except `..` | 2026-10-28 |
| CHK-M7-285-group | APP | W | plant: `current_principal` accepts a `bsa_` or `bse_` as an admin | PASS (red) | 1 failed: the route-group row | 2026-10-28 |
| CHK-M7-341, -342 | APP | W | plant: `_gate`'s TOTP-session check passes API tokens | PASS (red) | 1 failed: the API-token row (delete and rebuild) | 2026-10-28 |
| CHK-M7-343, -344 | APP | W | plant: the sink gate off in `_gate` | PASS (red) | 1 failed: the sink-gate row | 2026-10-28 |
| CHK-M7-345 | APP | W | plant: upload `require_role("operator")` | PASS (red) | 2 failed: operator session and `bsk_` | 2026-10-28 |
| CHK-M7-346 | APP | W | plant: delete `require_totp_session("operator")` | PASS (red) | 1 failed: operator session | 2026-10-28 |
| CHK-M7-285-logtext | APP | W | plant: the route logs the first 4 KiB of the file | PASS (red) | 1 failed: the log row | 2026-10-28 |
| CHK-M7-285-logtoken | APP | W | plant: a failed token check logs the raw token | PASS (red) | 1 failed: the log row | 2026-10-28 |
| CHK-M7-349 to -353 | APP | W | plants (one each): `policy_imported`, `policy_import_rejected`, `policy_deleted`, `policy_rebuilt`, `policy_reenabled` written as plain entries (`kind=None`) | PASS (red) | 1 failed each (5 plants): the alert row | 2026-10-28 |
| CHK-M7-354 | APP | W | plant: `flags` always `[]` | PASS (red) | 1 failed: the alert row | 2026-10-28 |
| CHK-M7-285-bit102 | APP | W | plant: `bit102.check_execute` returns no finding | PASS (red) | 1 failed: the `rm x` row. The samples rows stay green, as they should | 2026-10-28 |
| CHK-M7-335 | APP | W | plant: `check_ownership` returns no finding | PASS (red) | 1 failed: the BIT015 row | 2026-10-28 |

## Acceptance

REQ-177 (1): `manager/tests/test_security_m7.py` covers each importer item of TS §8.3 Security L1283, and it runs in CI, which runs the whole pytest suite.
- Non-admins refused for upload and delete.
- API tokens refused on delete and rebuild.
- Tokens on the wrong route group, on every M7 operation.
- Hostile upload file names stored safely.
- BIT015 and BIT102 rejections.
- XXE, entity expansion and oversize rejected.
- Also covered: symlinks and FIFOs never followed, the sink gate, no plugin text or token in logs, and every catalog alert written and shipped.

REQ-177 (2): every security plant of the M7 mutation table aimed at this suite went red: 320, 321, 323, 324, 335, 341 to 346, 349 to 354, 357, 358 and 363, plus the fail-open, FIFO, route-group, log and BIT102 plants (24/24).

## Notes (no defect)

- **The XXE-resolver plant shows defence in depth.** With defusedxml's guards off, billion laughs and quadratic blow-up are still refused by expat's own amplification limit. The fail-open plant, which takes away defusedxml's refusal outright, turns every XML case red.
- **An oversize upload is a 413 with no row (#99 (b)), not a BIT001 row.** The brief said BIT001 for oversize uploads; the suite asserts #99 (b) for uploads and BIT001 for folder files.
- **BIT102 coverage is deliberately narrow:** only `rm x` and the two samples. The TASK-146 r2 cases (su/runuser, time -o, flock, and the rest) belong to TASK-146 r2's own test and are not here.
- **The suite is Linux-only,** like every PostgreSQL suite (FIFOs and symlinks). `mkfifo` is guarded for the Windows type check, and nothing is skipped on Linux.
