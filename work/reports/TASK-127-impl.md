# TASK-127 IMPL: web CI build and G42 bundle check

This task covers REQ-134 and gate G42 (REQ-119 (2)). Sources: TS §6.3 (the CSP `default-src 'self'`, which G42 protects), §8.2; PD-28 (Vite builds into `manager/bitscan_manager/webui/`, gitignored); `work/reports/TASK-115-impl.md` (the bundle check belongs to this task). One review round (CI).

No tests were run (that is the tester's job). The local smoke runs below exercise my own step.

## Files

`.github/workflows/web.yml` only (111 lines added after round 1b, nothing else changed). That is over the 40-line estimate, because the bundle check is about 90 lines of inline Python. Lead ruling: the check stays inline, and TASK-127 stays one task.

## What changed

Two steps were appended to `gates`, after the existing npm ci, lint, typecheck, format:check, test, OpenAPI export, client regeneration and diff steps (REQ-134 order):

1. **`npm run build`** (working directory `web`). Vite writes `index.html` and `assets/` into `manager/bitscan_manager/webui/` (PD-28, `emptyOutDir`). A failing build fails the step.
2. **`Bundle check (G42) on the built HTML`**. This runs `python - manager/bitscan_manager/webui` (round 1b; it was `…/index.html` before), using the job's existing setup-python 3.12, with a quoted heredoc script that uses only the standard library. `html.parser` decodes entities and lowercases tag and attribute names. The script fails (exit 1, one `G42 FAIL <file> line N: <rule>` line per finding) on:
   - a `<script>` without `src` (the first `src` attribute is the one used, as in a browser, and an empty `src` counts as none), or any non-blank text inside a `<script>`;
   - a `<style>` element, in any case;
   - a `style=` attribute on any element;
   - a URL with a scheme or `//`. In URL attributes (`href`, `src`, `srcset`, `imagesrcset`, `action`, `formaction`, `poster`, `data`, `cite`, `background`, `ping`, `manifest`, `xlink:href`), the whole value and each space- or comma-separated part is checked, after the browser's normalisation: tabs and newlines removed, C0 controls and spaces trimmed, `\` read as `/`. Any scheme counts, so `https:`, `data:` and `javascript:` all fail. In every other attribute, a value that contains `://` or starts with `//` fails (for example a `<meta http-equiv="refresh" content="0;url=https://…">`);
   - a missing `index.html`, or one with no `<script src=…>` at all, so an empty or broken build cannot pass.

   It prints `G42 OK <file>` otherwise. The messages name the rule, the tag and the attribute, never the value.

Unchanged: the three action pins (checkout v7.0.1, setup-node v7.1.0, setup-python v7.0.0, by commit), `permissions: contents: read`, `persist-credentials: false`. No action or tool was added. The workflow has no path filter, so the steps run on every PR, including those touching `web/`.

Built JS and CSS are not scanned (CHK-M5-175 is a TASK-115 check, and React's bundle holds `http://www.w3.org/…` namespace strings).

### Round 1b (lead ruling, before the first TEST: G42 tightened, nothing lowered)

- **Two more rules, on built HTML only:** any event-handler attribute, and any `srcdoc=` attribute, with or without a value and in any case. The CSP blocks both as well. The JS bundle is not scanned for them, because React DOM holds `onClick` and `srcDoc` as plain strings.
  - The handler rule is a prefix rule: an attribute name of `on` followed by letters, digits, `_` or `-` fails. That is stricter than the list of real event names. It also refuses a custom attribute such as `one=`, and it cannot miss a new event name. No built page has such an attribute. `data-online=` passes.
- **Every `.html` file in the build output** (`manager/bitscan_manager/webui/`, searched recursively) now gets all the rules, not only `index.html`. `index.html` must exist and must still load at least one `<script src>`. The step now takes the build folder as its argument and prints one `G42 OK` or `G42 FAIL` line per file. It is renamed `Bundle check (G42) on the built HTML`.

For the reviewer: the regular expressions use Python `re`, not RE2. The input is our own build output, not untrusted data, and the patterns are fixed and linear (no nested quantifiers).

## Local smoke run (Windows, Node 24.22.0, Python 3.12.10)

- `npm run build` in `web/` exits 0 and writes `index.html` with one `<script type="module" crossorigin src="/assets/index-….js">`. `git status --ignored` shows the folder as ignored.
- The step script was taken from `web.yml` with a YAML parser (so the YAML parses and the heredoc survives the block-scalar indentation), passed `bash -n`, and was run from a scratch root holding a copy of the built `index.html`:
  - control (the real build): `G42 OK`, rc 0;
  - each plant gives rc 1 with the matching line: an inline `<script>alert(1)</script>`; `<style>`; `<STYLE>`; `style="color:red"` on `<div>`; an `https://` font `<link>`; `//cdn…`; `data:` icon; an entity-encoded `&#x68;ttps://`; `/\host` and `\\host` (built from character codes, so no shell rewrote them); a meta refresh to `https://`; the entry `src` pointed at `https://`; a page with no `<script src>`; a missing `index.html`;
  - a single `\host…` passes, which is right: a browser reads it as the same-origin path `/host…`.
- Round 1b, the same way, from a copy of the whole build folder:
  - control: `G42 OK`, rc 0;
  - rc 1 for each of: `onload="go()"` on `<body>`, `ONCLICK=` on `<div>`, a bare `onerror` on `<img>`, `<iframe srcdoc="hi">`;
  - a clean second file `assets/extra.html`: OK for both files, rc 0;
  - the same file with `onmouseover=` and `style=`: both reported for `extra.html`, rc 1, even though `index.html` is OK;
  - the inline-script plant is still red;
  - `one="1"` is refused (the prefix rule) and `data-online="1"` passes.

## For the tester (TP-M5-20)

- CHK-M5-290: read the step order in `gates`. The new steps are the last two.
- CHK-M5-291: to replay locally, copy the `run:` block of the bundle-check step (from `python -` to `EOF`, without the YAML indentation) into a file. Run it with bash from a root that holds `manager/bitscan_manager/webui/` (the real repo after `npm run build`, or a throwaway copy with the plant). The round 1b rules need their own plants: an `on<event>=` attribute and a `srcdoc=` attribute in `index.html`, and one plant in a second `.html` file in the build folder. A failing build: break a source file in a copy, and `npm run build` exits non-zero. The PR run is NOT RUN until the branch is pushed.
- I left a local build in `manager/bitscan_manager/webui/` (gitignored). The next build empties it.

## Round 2 (TEST round 1 FAIL, CHK-M5-291; lead ruling 2026-10-25)

Finding: `<meta http-equiv="refresh" content="0;url=//evil.example/">` passed, because non-URL attributes were only checked for `://` or a leading `//`, and here the `//` sits after `url=` inside `content`.

Fix (only `.github/workflows/web.yml`, 10 lines added in the bundle-check script; the `://` rule for every other attribute is unchanged):
- New `REFRESH` pattern: optional delay digits, an optional `;` or `,`, an optional `url=` (any case, spaces around `=`), and an optional opening quote; the rest is the target. A trailing quote is stripped.
- For a `<meta>` whose `http-equiv` is `refresh` (trimmed, any case), the target from `content` goes through the same `external()` rule as `URL_ATTRS`: tabs and newlines removed, C0 controls and spaces trimmed, `\` read as `/`, then any scheme or a leading `//` fails with `a refresh URL with a scheme or // in content= on <meta>`.

Local smoke run (Python 3.12, script extracted from `web.yml` and dedented, on a copy of the real build; `bash -n` passes on the `run:` block; LF only):
- red (rc 1): refresh to `//evil.example/`; to `https://…` (both rules report it); `URL='//…'` (upper case, quoted, delay 5); `0; //…` without `url=`; `url=\evil.example/`; `url=javascript:alert(1)`;
- green (rc 0): the real build; `data-online="1"`; refresh to `/login`; refresh `30` with no URL; `<meta name="description" content="a // b">`.

For the tester: re-run the same 29 cases (`%TEMP%\m5_g42_plants.py`); the meta-refresh-to-`//` case should now be RED and the controls green.
