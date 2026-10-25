# TASK-115 TEST: web toolchain (Vite build, jsdom, Testing Library, QR library)

Verdict: **PASS**. Evidence-only task (TP-M5-08). Commands (Windows, Node 24.22.0, from web/): `npm ci --ignore-scripts`, `npm run build`, `npm ls --omit=dev --all`, `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm test` (154/154 passed, 0 failed, 0 skipped), the web.yml G42 script on the build and on 29 plants, a Vite build of web/index.html with an inline script.

- REQ-119 (1) build into manager/bitscan_manager/webui/: CHK-M5-170 PASS.
- REQ-119 (2) G42 on the built index.html, and red on inline script, style, style= and an https font link: CHK-M5-171, -172, -350 PASS (the one gap found is in TASK-127's check, see that report).
- Dependencies: only React, React DOM, openapi-fetch and qrcode-generator at runtime; Vite, Vitest, jsdom, Testing Library dev-only and pinned with integrity hashes: CHK-M5-173 PASS.
- lint, typecheck, format, test: CHK-M5-174 PASS. No other-origin load in the JS: CHK-M5-175 PASS.
