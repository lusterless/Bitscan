# TASK-005 REVIEW: web toolchain (package, strict tsconfig, ESLint guards, Prettier)

Reviewer: reviewer. Date: 2026-10-20. REQ-013, REQ-014. Spec: TS §6.3 L1140-1141, TS §8.1 L1254 ("Stolen web session (XSS)"), TS §8.2; `.claude/rules/web-ui.md` line 10. Inputs: `work/reports/TASK-005-impl.md` (revision 3), `work/reports/TASK-005-test.md` (PASS, revision 3), `tests/m0/report.md` CHK-M0-090 to -105, CHK-M0-100-r3 and CHK-M0-101-r2; `work/decisions.md` 2026-10-20 (exemption narrowed).

Verdict: APPROVED

Revision 3. One approval is enough for this task (TS §8.2 L1268).

## Revision 3 re-review

- **The change:** in `web/eslint.config.js` (107 lines), the constant `CLIENT = "src/api/client.ts"` replaces the `src/api/**` glob in both the guarded block's `ignores` and the exempt block's `files`, and the message now names `src/api/client.ts`. Nothing else changed. This closes the TASK-009 review nit 2: a hand-written `src/api/other.ts` could call `fetch`.
- **Probes, linted from stdin with `--stdin-filename`** (nothing written to the tree):

  | Probe | Exit | Guard that fires |
  | --- | --- | --- |
  | `fetch` and `new XMLHttpRequest()` in `src/api/client.ts` | 0 | none (allowed) |
  | `fetch` in `src/api/other.ts`, `src/api/client.mts`, `src/api/sub/client.ts`, `src/x/client.ts` and `src/p.ts`; `typeof fetch` in `src/api/schema.d.ts` | 1 each | generated client |
  | `localStorage` in `client.ts` | 1 | memory only |
  | `innerHTML =` in `client.ts` | 1 | plain text |
  | built key `window["local" + "Storage"]` in `client.ts` | 1 | static key |
  | `eslint-disable-next-line` over `localStorage` in `client.ts` | 1 | memory only (inline config off) |

  The generated `schema.d.ts` is now linted with every guard. The tester showed that generated output with operations still lints clean (CHK-M0-100-r3).
- **Tree:** `npm run lint`, `typecheck` and `format:check` exit 0.

## Findings (revision 3)

1. **nit (from round 2, still open; no change needed).** Destructuring from `window.document` (`const { write } = window.document`) is not caught. Fix if wanted: add the twin selector `VariableDeclarator[init.property.name='document'] > ObjectPattern > Property`.
2. **nit (from round 2).** The built-key rule also flags ordinary dynamic keys such as ``m[`row-${id}`]`` and `m["row-" + id]`; the workaround is a variable key. M7 should know.
3. **nit (from round 1).** Sinks outside REQ-014 (`srcdoc`, `setHTMLUnsafe`, `DOMParser`, `indexedDB`, `WebSocket`, `EventSource`, `sendBeacon`, `eval`) stay with code review. They are listed in the impl report.

## History

- **Round 1: CHANGES_REQUESTED.** Four should-fix findings, all fixed in round 2:
  1. inline `eslint-disable` comments silenced every guard;
  2. template-literal keys bypassed the computed-key guards;
  3. `window.document.write` and `const { cookie } = document` were not caught;
  4. `.mts` and `.cts` files were outside the guard globs.

  Round-1 nits: sinks outside REQ-014; the TypeScript pin reason (since recorded; TypeScript is 5.9.3 since TASK-006); `npm ci --ignore-scripts` for TASK-009 (done).
- **Round 2: APPROVED,** with nits 1 and 2 above.
- **Revision 3:** the `fetch`/`XMLHttpRequest` exemption is narrowed from `src/api/**` to `src/api/client.ts`. Approved here.
