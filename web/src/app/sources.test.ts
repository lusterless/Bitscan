/// <reference types="vite/client" />
// TASK-168 to 173 TEST (TP-M7-29): CHK-M7-391.
// Expected values: TS §6.3 L1141 (stored text is rendered as plain text only;
// the UI never injects HTML), TS §6.2 L1080 and §8.1 (the `bsu_` token is held
// in memory, never in storage), `.claude/rules/web-ui.md` (no
// `dangerouslySetInnerHTML`, `innerHTML` or HTML renderer on API data; call
// the API only through the generated client). The lint (G12) bans the same
// sinks by syntax; this scan also sees forms the lint selectors miss (a
// computed key, a string), on every product source file, including the M7
// screens.
import { describe, expect, it } from "vitest";

const sources = import.meta.glob<string>(
  [
    "/src/**/*.ts",
    "/src/**/*.tsx",
    "!/src/**/*.test.ts",
    "!/src/**/*.test.tsx",
    "!/src/test/**",
    "!/src/api/schema.d.ts",
  ],
  { query: "?raw", import: "default", eager: true },
);

const SINKS = [
  "dangerouslySetInnerHTML",
  "innerHTML",
  "outerHTML",
  "insertAdjacentHTML",
  "createContextualFragment",
  "DOMParser",
  "document.write",
  "srcdoc",
];
const STORAGE = [
  "localStorage",
  "sessionStorage",
  "document.cookie",
  "cookieStore",
  "indexedDB",
];

/** Source text without comments, so a rule written in a comment is no hit. */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'])\/\/.*$/gm, "$1");
}

describe("CHK-M7-391 product sources", () => {
  it("the scan sees the M7 screens and components", () => {
    const names = Object.keys(sources);
    for (const f of [
      "/src/screens/Profiles.tsx",
      "/src/screens/ProfileDetail.tsx",
      "/src/screens/PolicyUpload.tsx",
      "/src/screens/Imports.tsx",
      "/src/screens/Rebuild.tsx",
      "/src/components/Findings.tsx",
      "/src/app/problems.ts",
      "/src/app/router.ts",
      "/src/app/routes.tsx",
      "/src/app/App.tsx",
    ]) {
      expect(names).toContain(f);
    }
    expect(names.some((n) => n.includes(".test."))).toBe(false);
  });

  it.each(SINKS)("no source uses %s", (sink) => {
    const hits = Object.entries(sources)
      .filter(([, text]) => code(text).includes(sink))
      .map(([name]) => name);
    expect(hits).toEqual([]);
  });

  it.each(STORAGE)("no source touches %s", (store) => {
    const hits = Object.entries(sources)
      .filter(([, text]) => code(text).includes(store))
      .map(([name]) => name);
    expect(hits).toEqual([]);
  });

  it("only src/api/client.ts creates the HTTP client; no screen calls fetch", () => {
    const hits = Object.entries(sources)
      .filter(([name]) => name !== "/src/api/client.ts")
      .filter(([, text]) =>
        /\bfetch\s*\(|XMLHttpRequest|createClient/.test(code(text)),
      )
      .map(([name]) => name);
    expect(hits).toEqual([]);
  });
});
