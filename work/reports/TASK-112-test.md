# TASK-112 TEST: serve the built UI

Verdict: **PASS** (one observation open for main: trailing-slash 307). REQ-118 (1)-(6). Commands: W run m5-t113a (tests/test_webui_serving.py incl. two real-serve tests over TLS; tests/test_invariants_m3.py with the TP-M5-05 allow-list edit), re-run 1/1 of test_no_code_reads_an_inventory_switch (test bug: lone surrogate literal). Plants CHK-M5-337 (a, b), 338, 339, 340, 341 and a G34 query-parameter plant: all red; control 460/460.

AC: (1) types and exact headers CHK-M5-100, -101; (2) every listed traversal, encoded, backslash, absolute, sub-folder, late-added, unknown-extension and /index.html probe 404 with no content CHK-M5-102, -103, -104; (3) no Access-Control-* incl. OPTIONS with Origin CHK-M5-105; (4) document unchanged CHK-M5-109; (5) no build: serve logs one line, / 404, API unchanged CHK-M5-108, -110; (6) route walk allows exactly GET / and GET /assets/{name}, no input CHK-M5-111.

Observation: `GET /assets/<file>/` answers 307 to the slash-less path with `Location: https://<Host>/...` (Starlette redirect_slashes, app-wide since M2; API routes behave the same). No file content is sent and headers are present. The tests accept 307/308 with an empty body until main rules.

## Revision 1 (user ruling 2026-10-25: trailing-slash redirects off app-wide): PASS

- Change under test: `manager/bitscan_manager/app.py`, `redirect_slashes=False` on the app (impl report "Revision 1").
- Tests changed (tester): `manager/tests/test_webui_serving.py`: the 307/308 acceptance in the CHK-M5-102 probe test replaced by the 404 expectation; new CHK-M5-113 test (17 slashed static, health, user and agent paths, Host: evil.example: problem+json 404, TS §6.3 headers, no Location, no CORS), a control test, and the real-serve test checks slashed paths and that no answer has a Location.
- Run (WSL, CI=true, -n 4): the webui suite plus 11 M2/M3 route suites: 521/522 passed, 1 failed (my control test expected 401 on an app without a runtime; it answers 503), 0 errors, 0 skipped. Re-run of that node id: 1/1 passed.
- Plant CHK-M5-364: the kwarg removed, and set to True: both red (307 for the slashed paths). Control 115/115.
- The reviewer's 4 points: (1) slashed /assets/x.js/, a slashed /api/v1/... path and a slashed agent path each give problem+json 404 with the headers and no Location: yes; (2) the plant is red: yes; (3) the M2/M3 route suites re-run: yes, green; (4) the 307/308 acceptance replaced by the 404 expectation: yes.
