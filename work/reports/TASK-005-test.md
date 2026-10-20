# TASK-005 TEST report: web toolchain, strict TypeScript, ESLint guards, Prettier

Tester: tester. REQ-013, REQ-014. Date 2026-10-20. Impl report: `work/reports/TASK-005-impl.md` (round 2). Review: `work/reviews/TASK-005.md`. Node 24.22.0, npm 11.19.1.

## Verdict: PASS (revision 3)

Round 1 was PASS against the REQ-014 criteria, but the reviewer found four guard gaps (CHANGES_REQUESTED, findings 1 to 4). Round 2 (`web/eslint.config.js` only) closes all four, and every round-1 check still passes.

## Commands and counts

- Tree, from `web/`: `npm run lint`, `typecheck`, `format:check` and `test` all exit 0.
- Round 1: a fresh `npm ci` in a `mktemp -d` copy, with plants made in that copy (CHK-M0-090 to -105).
- Round 2: 62 probes linted from stdin with `node_modules/.bin/eslint --max-warnings 0 --stdin --stdin-filename <path under src/>`, so nothing was written to the tree. This covers the reviewer's misses and caught probes plus all of my round-1 plants. 53 were expected red and 9 green, with 0 mismatches.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-013 (1): `npm ci` from the committed lock (G11), and red when the lock is out of sync | CHK-M0-090, CHK-M0-091 | PASS |
| REQ-013 (2): `strict: true`; typecheck green, red on a type error and on an implicit `any` | CHK-M0-092, CHK-M0-093 | PASS |
| REQ-013 (3): lint green, red on an unused variable | CHK-M0-094, CHK-M0-095 | PASS |
| REQ-013 (4): format:check green, red on a misformatted file | CHK-M0-102, CHK-M0-103 | PASS |
| REQ-013 (5): `npm test` exits 0 with no test files; a failing test is red (G15) | CHK-M0-104, CHK-M0-105 | PASS |
| REQ-014 (1): `dangerouslySetInnerHTML` (JSX, spread, quoted key) | CHK-M0-096, CHK-M0-101 | PASS |
| REQ-014 (2): HTML sinks, including template keys, `window.document.write` and destructured `write` | CHK-M0-097 | PASS |
| REQ-014 (3): storage and cookie, including template keys, optional chaining, destructuring and built keys | CHK-M0-098 | PASS |
| REQ-014 (4): `fetch(` and `new XMLHttpRequest(` outside `src/api/` are red; revision 3 also bans them in `src/api/` except `client.ts` | CHK-M0-099, CHK-M0-100, CHK-M0-100-r3 | PASS |
| Review finding 1: inline disable comments ignored | CHK-M0-101-r2 | PASS |
| Review finding 2: template-literal keys | CHK-M0-097, CHK-M0-098, CHK-M0-099 | PASS |
| Review finding 3: `window.document.write`, destructured `cookie` | CHK-M0-097, CHK-M0-098 | PASS |
| Review finding 4: `.mts`, `.cts`, `.mjs`, `.cjs` | CHK-M0-100, CHK-M0-101 | PASS |

## Info

- The guard against built keys flags any computed member whose key is a template literal with substitutions, or a `+` with a string literal. Ordinary index arithmetic (`a[i + 1]`) and variable keys (`m[k]`) stay green. A key passed through a variable cannot be caught statically, and the reviewer accepts that.
- Review nit 5 (srcdoc, indexedDB, WebSocket, eval and others) is outside REQ-014 and was not tested.
