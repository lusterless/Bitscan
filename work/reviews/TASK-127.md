# TASK-127 REVIEW: web CI build and G42 bundle check

Verdict: APPROVED (round 2)

Reviewer: reviewer, 2026-10-25. One review round (CI). Not a two-approval task.

Scope reviewed: `.github/workflows/web.yml`, the two steps added at the end of `gates` (`work/reports/TASK-127-impl.md`, rounds 1, 1b and 2). Sources:
- REQ-134, REQ-119 (2) and G42;
- TS §6.3 (CSP `default-src 'self'; … object-src 'none'; base-uri 'none'; form-action 'self'`);
- PD-28;
- decisions 2026-10-25 (the check stays inline; `on<event>=` and `srcdoc=` are refused in built HTML).

TEST:
- Round 1 FAIL (CHK-M5-291): `<meta http-equiv="refresh" content="0;url=//evil.example/">` passed.
- Round 2 PASS (tester-m5): the extracted step is 36/36 as expected, every round 1b rule is red, and the meta-refresh `//host` gap is closed. The controls stay green: `<meta name=description content="a // b">` and a refresh to `/login`. actionlint 1.7.7 is clean.
- The PR run is NOT RUN until the branch is pushed.

## Checks
1. G42 rules, checked against what a browser would load under the TS §6.3 CSP:
   - an inline `<script>`, or a `<script>` without `src` or with an empty `src`;
   - `<style>` and `style=`;
   - any scheme or `//` in the 13 URL attributes, checked on the whole value and on each `srcset`-style part, after browser normalisation (tabs and newlines dropped, C0 trimmed, `\` read as `/`);
   - `://` or a leading `//` in any other attribute;
   - a meta-refresh target, put through the same normalisation;
   - `on*=` and `srcdoc=`.
   - The rules also cover `<base href>`, `<form action>`, `<object data>`, `<embed src>` and SVG `xlink:href`.
   - The parser decodes entities and lowercases names, so encoded and upper-case forms are caught.
   - A missing `index.html`, or an `index.html` with no `<script src>`, fails, so an empty build cannot pass.
2. Every `.html` file in the build output is checked. Messages name the rule, tag and attribute, never the value.
3. Supply chain: no new action or tool. The Python is standard library only. The pins, `contents: read` and `persist-credentials: false` are unchanged. `npm run build` runs after `npm ci --ignore-scripts` and the existing gates. Nothing is lowered.
4. Python `re` rather than RE2: the input is our own build output in CI, not untrusted data reaching the manager, and the patterns are fixed and linear. I accept that.
5. Scope: one file, about 120 lines of inline Python. The lead ruled that it stays one task.

## Findings
1. nit, `web.yml`, bundle-check script. A meta refresh whose `content` has a delay and a bare relative target that is not `url=` (`0; foo=//x`) is read as the same-origin path `foo=//x`, as the browser does, so passing it is correct. No change; recorded so a later reader does not "fix" it.
