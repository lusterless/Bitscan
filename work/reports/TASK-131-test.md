# W1 low-risk batch TEST: TASK-129, TASK-130, TASK-131

**Verdict: PASS for all three** (round 1; one test run for the batch, plants for the security rows only, decisions 2026-10-25). Tester: tester-m6, 2026-10-26. Written by `main` from the tester's text (the harness blocks the tester on report files). The full manager suite (G18) at the end of the wave is reported in its own row, CHK-M6-315-w1.

Impl reports: `work/reports/TASK-129-impl.md`, `TASK-130-impl.md`, `TASK-131-impl.md`. Rows: `tests/m6/report.md` CHK-M6-020 to -027, CHK-M6-100 to -108, CHK-M6-120 to -126, and the plants CHK-M6-333 to -336.

## Tester fix list (done in this batch)

- `deploy/tests/check_debian_meta.py` (#90): VERSION_RE accepts a release `X.Y.Z-R` with no `~`. Two new checks: each changelog trailer's weekday matches its date, and the trailer dates strictly decrease down the file. Result: 78/78 on the tree, and three plants go red (CHK-M6-100).
- The four old-tuple cursor calls (`test_agent_repo_pg.py:487`; `test_inventory_repo_pg.py:384, 421, 453`) now pass ids. `mypy --strict manager` is clean on 234 files (CHK-M6-126).
- Lintian on the built 0.1.0-1 `.deb`: dropping `initial-upload-closes-no-bugs` leaves no unused override and no new error or warning (CHK-M6-102).

## TASK-129: manager wheel (REQ-137, G47) — PASS

New test `deploy/tests/test_manager_wheel.sh`, run in a fresh `ubuntu:24.04` container: **59/59 checks passed**. The UI was built with `npm ci --ignore-scripts && npm run build` (Node 24, which the Ubuntu archive does not have, so it was built on Windows into the git-ignored webui folder and copied in, with `WHEEL_PREBUILT_UI=1`).

| Criterion | Result | Row |
| --- | --- | --- |
| (1) the build exits 0; the wheel lists `webui/index.html`, every asset, every migration file, and no `tests/` | yes; UI and migration sets equal the tree, byte-identical; nothing extra | CHK-M6-020, -021, -022 |
| (2) fresh 24.04 venv, hashed runtime lock `--only-binary :all:`, wheel `--no-deps`; `--help` lists serve, users, db migrate, db maintain | yes; no sdist built; `pip check` clean | CHK-M6-023 |
| (3) `db migrate` to head on a freshly bootstrapped database; `serve` `GET /` byte-identical to the build's `index.html`; every asset 200 | head m0005, second run unchanged; `/` and the asset `cmp`-identical | CHK-M6-024, -025 |
| (4) G42 on the wheel's `index.html` | clean | CHK-M6-026 |
| (5) a no-UI wheel installs and `serve` logs `web ui not built; serving the API only` | yes; `/` 404 problem+json | CHK-M6-027 |

The wheel plants (CHK-M6-320 to -322) belong to the gate's mutation table.

## TASK-130: agent 0.1.0-1 (REQ-142, G37–G40) — PASS

| Criterion | Result | Row |
| --- | --- | --- |
| (1) `build-deb.sh` gives `bitscan-agent_0.1.0-1_amd64.deb`; the agent binary carries 0.1.0-1 | yes; sha256 3b5c98a0…3db, the same hash as tester-m6b's independent release run. The start-line check needs an enrolled agent and is in W4 and G41 | CHK-M6-101, -108 |
| (2) G37 lintian clean | 93/93 build-deb checks; no E/W; no unused override | CHK-M6-102 |
| (2) G38 install, reinstall, upgrade, purge twice each on 22.04 and 24.04 | 567/567 on each | CHK-M6-103 |
| (2) the upgrade from `0.1.0~pre1-1` keeps `agent_id`, `token` and `agent.yaml` byte-identical | 20/20 on each host (new `upgradefrom` subcommand in `deploy/tests/test_maintainer_scripts.sh`) | CHK-M6-104 |
| (2) G39 reproducible; G40 SBOM | 14/14 repro; SBOMs complete | CHK-M6-105 |
| (3) `dpkg --compare-versions 0.1.0~pre1-1 lt 0.1.0-1` | true | CHK-M6-106 |
| (4) runbook sections walked on a VM | in W4 (CHK-M6-213) | — |
| (5) no secret, task id or process note | none | CHK-M6-107 |

## TASK-131: id-only cursors (REQ-143, G53) — PASS

New suite `manager/tests/test_agent_cursors_pg.py`. The affected set passed **434/434**, with 0 failed, 0 errors, 0 skipped.

| Criterion | Result | Row |
| --- | --- | --- |
| (1) a 255-character non-ASCII hostname and package name on page boundaries; N + 1 items appear exactly once, in the unchanged order | yes, for limits 1, 2, 3, 4/5 and 500; the order comes from an independent oracle | CHK-M6-120, -121 |
| (2) every cursor ≤ 512 characters | yes; the payload holds only the id | CHK-M6-122 |
| (3) tampered, foreign-agent and vanished-anchor cursors give 400 `invalid_request`, never 500 | yes, plus 26 bad payloads and a missing agent or package | CHK-M6-123 |
| (4) the M3 and M5 suites pass; `openapi.json` byte-identical | yes | CHK-M6-124, -125 |
| (5) G1 S608 clean, and red on a planted f-string | yes | CHK-M6-126, -334 |
| Security plants | CHK-M6-333, -335, -336 red against a 74/74 control; CHK-M6-334 red | rows |

## Notes for the reviewer

- Behaviour change, as the acceptance text describes: an `/agents` cursor that names a missing agent is now 400, where it used to be 404. This is covered.
- By design, a signed `[package_id]` for a package the agent never had still works as an anchor. The scope, not the id, binds a cursor to its agent; that is plan TASK-131's "the anchor comes from `package`". Covered by `test_package_cursor_any_existing_package_id_anchors`.
- Environment notes, none of them product defects:
  - the corporate root was trusted inside the throwaway containers only;
  - the WSL PostgreSQL cluster must be UTF8, as on a stock 24.04 host;
  - the M5 tests need the UI build in the copy, as CI provides it.
