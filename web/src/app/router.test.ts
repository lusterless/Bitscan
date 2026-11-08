// TASK-116 TEST (TP-M5-09): CHK-M5-187.
// Expected values: the plan TASK-116 hash table (PD-28 (d) hash routes;
// anything else is the host list; host ids are hyphenated UUIDs, lower-cased).
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  formatHash,
  isPolicyId,
  isUuid,
  navigate,
  parseHash,
  useRoute,
  type Route,
} from "./router";

const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const UPPER = ID.toUpperCase();

afterEach(() => {
  window.location.hash = "";
});

describe("parseHash, every row of the plan table", () => {
  it.each([
    ["#/hosts", { name: "hosts" }],
    ["", { name: "hosts" }],
    ["#", { name: "hosts" }],
    ["#/", { name: "hosts" }],
    ["#/hosts/" + ID, { name: "host", agentId: ID }],
    ["#/hosts/" + UPPER, { name: "host", agentId: ID }],
    ["#/packages", { name: "packages" }],
    ["#/enrolment/requests", { name: "enrolment-requests" }],
    ["#/enrolment/tokens", { name: "enrolment-tokens" }],
    ["#/account/totp", { name: "totp" }],
    ["#/account/password", { name: "password" }],
  ] as const)("%j", (hash, route) => {
    expect(parseHash(hash)).toEqual(route);
  });

  it.each([
    "#/nope",
    "#/hosts/",
    "#/hosts/not-a-uuid",
    "#/hosts/" + ID + "/packages",
    "#/hosts/" + ID + "?x=1",
    "#/hosts/" + ID.slice(0, 35),
    "#/hosts/" + ID + "0",
    "#/hosts/{" + ID + "}",
    "#/hosts/" + ID.replaceAll("-", ""),
    "#/packages?q=ssl",
    "#/packages/",
    "#/enrolment",
    "#/enrolment/requests/x",
    "#/account",
    "#/Packages",
    "#/HOSTS",
    "#hosts",
    "#//packages",
    "#/hosts/" + ID.replace("0f8f", "0g8f"),
    "#/../packages",
    "#/hosts/%30f8fad5b-d9cb-469f-a165-70867728950e",
  ])("anything else (%j) is the host list", (hash) => {
    expect(parseHash(hash)).toEqual({ name: "hosts" });
  });
});

const ROUTES: Route[] = [
  { name: "hosts" },
  { name: "host", agentId: ID },
  { name: "packages" },
  { name: "profiles" },
  { name: "profile", policyId: "7" },
  { name: "policy-upload" },
  { name: "imports" },
  { name: "rebuild" },
  { name: "enrolment-requests" },
  { name: "enrolment-tokens" },
  { name: "totp" },
  { name: "password" },
];

describe("formatHash", () => {
  it("gives the table's hashes", () => {
    expect(ROUTES.map(formatHash)).toEqual([
      "#/hosts",
      "#/hosts/" + ID,
      "#/packages",
      "#/profiles",
      "#/profiles/7",
      "#/catalog/upload",
      "#/catalog/imports",
      "#/catalog/rebuild",
      "#/enrolment/requests",
      "#/enrolment/tokens",
      "#/account/totp",
      "#/account/password",
    ]);
  });

  it.each(ROUTES)("round-trips %j", (route) => {
    expect(parseHash(formatHash(route))).toEqual(route);
    expect(formatHash(parseHash(formatHash(route)))).toBe(formatHash(route));
  });
});

describe("isUuid boundaries", () => {
  it.each([
    [ID, true],
    [UPPER, true],
    ["00000000-0000-0000-0000-000000000000", true],
    ["ffffffff-ffff-ffff-ffff-ffffffffffff", true],
    [ID.slice(0, 35), false],
    [ID + "a", false],
    ["", false],
    [ID.replaceAll("-", ""), false],
    ["0f8fad5b0d9cb-469f-a165-70867728950e".slice(0, 36), false],
    ["0f8fad5-bd9cb-469f-a165-70867728950e", false],
    ["0f8fad5bd-9cb-469f-a165-70867728950e", false],
    ["0f8fad5b-d9cb-469fa-165-70867728950e", false],
    ["0f8fad5b-d9cb-469f-a16570867728-950e", false],
    ["0f8fad5b-d9cb-469f-a165-70867728950g", false],
    ["0f8fad5b-d9cb-469f-a165-70867728950 ", false],
    ["0f8fad5b-d9cb-469f-a165-7086772895١٢", false],
    ["0f8fad5b-d9cb-469f-a165-7086772895０e", false],
    ["{0f8fad5b-d9cb-469f-a165-70867728950}", false],
  ])("%j -> %s", (value, want) => {
    expect(isUuid(value)).toBe(want);
  });
});

describe("navigate and useRoute", () => {
  it("navigate sets the hash; useRoute follows hashchange", () => {
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "hosts" });
    act(() => {
      navigate({ name: "host", agentId: ID });
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(window.location.hash).toBe("#/hosts/" + ID);
    expect(result.current).toEqual({ name: "host", agentId: ID });
    act(() => {
      window.location.hash = "#/packages";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current).toEqual({ name: "packages" });
  });
});

// TASK-173 TEST (TP-M7-29): CHK-M7-390 (router part).
// Expected values: the TASK-173 row (every new route parses and prints back to
// the same hash) and the impl report's hash table; the API path pattern of
// `/policies/{id}` is `^[0-9]{1,20}$` (manager/openapi.json); TS §6.3 L1139
// (catalog keys are integers, kept as a digit string so no id is rounded).
const MAX_ID = "9".repeat(20);

describe("CHK-M7-390 the M7 hashes", () => {
  it.each([
    ["#/profiles", { name: "profiles" }],
    ["#/profiles/7", { name: "profile", policyId: "7" }],
    ["#/profiles/0", { name: "profile", policyId: "0" }],
    ["#/profiles/007", { name: "profile", policyId: "007" }],
    ["#/profiles/" + MAX_ID, { name: "profile", policyId: MAX_ID }],
    [
      "#/profiles/9007199254740993",
      { name: "profile", policyId: "9007199254740993" },
    ],
    ["#/catalog/upload", { name: "policy-upload" }],
    ["#/catalog/imports", { name: "imports" }],
    ["#/catalog/rebuild", { name: "rebuild" }],
  ] as const)("%j", (hash, route) => {
    expect(parseHash(hash)).toEqual(route);
    expect(formatHash(parseHash(hash))).toBe(hash);
  });

  it.each([
    "#/profiles/",
    "#/profiles/" + MAX_ID + "9",
    "#/profiles/-1",
    "#/profiles/+1",
    "#/profiles/1.0",
    "#/profiles/1e3",
    "#/profiles/0x1",
    "#/profiles/ 1",
    "#/profiles/1 ",
    "#/profiles/7/x",
    "#/profiles/7?x=1",
    "#/profiles/%37",
    "#/profiles/١",
    "#/profiles/７",
    "#/profiles/" + ID,
    "#/Profiles",
    "#/profiles/../catalog/rebuild",
    "#/catalog",
    "#/catalog/",
    "#/catalog/upload/",
    "#/catalog/Upload",
    "#/catalog/rebuild?now=1",
    "#/policies",
    "#/imports",
    "#/rebuild",
  ])("anything else (%j) is the host list", (hash) => {
    expect(parseHash(hash)).toEqual({ name: "hosts" });
  });

  it.each([
    ["7", true],
    ["0", true],
    [MAX_ID, true],
    [MAX_ID + "0", false],
    ["", false],
    ["a", false],
    ["1a", false],
    ["١", false],
    ["１", false],
    ["¹", false],
    [" 1", false],
  ])("isPolicyId(%j) -> %s", (value, want) => {
    expect(isPolicyId(value)).toBe(want);
  });
});

// ------------------------------------------------------------ CHK-M11-271
// TASK-251 TEST (TP-M11-14): the M11 hashes. Expected values: the TASK-251
// acceptance test (parse and format every new hash; malformed ids fall back
// to the host list); scan ids are hyphenated UUIDs lower-cased as host ids
// are (PD-28 (d)); a profile id for Run scan follows the M7 profile id rule.

const SCAN_ID = "1b4e28ba-2fa1-41d2-883f-0016d3cca427";

describe("CHK-M11-271 the M11 hashes", () => {
  it.each([
    ["#/scans", { name: "scans" }],
    ["#/scans/" + SCAN_ID, { name: "scan", scanId: SCAN_ID }],
    [
      "#/scans/" + SCAN_ID + "/results",
      { name: "scan-results", scanId: SCAN_ID },
    ],
    ["#/scans/run", { name: "run-scan", policyId: null }],
    ["#/scans/run/7", { name: "run-scan", policyId: "7" }],
    ["#/scans/run/" + MAX_ID, { name: "run-scan", policyId: MAX_ID }],
    ["#/schedules", { name: "schedules" }],
  ] as const)("%j parses and formats back", (hash, route) => {
    expect(parseHash(hash)).toEqual(route);
    expect(formatHash(parseHash(hash))).toBe(hash);
  });

  it("an upper-case scan id is lower-cased (detail and results)", () => {
    const upper = SCAN_ID.toUpperCase();
    expect(parseHash("#/scans/" + upper)).toEqual({
      name: "scan",
      scanId: SCAN_ID,
    });
    expect(parseHash("#/scans/" + upper + "/results")).toEqual({
      name: "scan-results",
      scanId: SCAN_ID,
    });
  });

  it("formatHash gives each route's hash", () => {
    const routes: [Route, string][] = [
      [{ name: "scans" }, "#/scans"],
      [{ name: "scan", scanId: SCAN_ID }, "#/scans/" + SCAN_ID],
      [
        { name: "scan-results", scanId: SCAN_ID },
        "#/scans/" + SCAN_ID + "/results",
      ],
      [{ name: "run-scan", policyId: null }, "#/scans/run"],
      [{ name: "run-scan", policyId: "12" }, "#/scans/run/12"],
      [{ name: "schedules" }, "#/schedules"],
    ];
    for (const [route, hash] of routes) {
      expect(formatHash(route)).toBe(hash);
      expect(parseHash(hash)).toEqual(route);
    }
  });

  it.each([
    "#/scans/",
    "#/scans/x",
    "#/scans/" + SCAN_ID.replace(/-/g, ""),
    "#/scans/" + SCAN_ID.slice(0, -1),
    "#/scans/" + SCAN_ID + "0",
    "#/scans/" + SCAN_ID.replace("1b4e", "gb4e"),
    "#/scans/" + SCAN_ID + "/",
    "#/scans/" + SCAN_ID + "/other",
    "#/scans/" + SCAN_ID + "/results/",
    "#/scans/" + SCAN_ID + "/results/x",
    "#/scans/" + SCAN_ID + "/results/results",
    "#/scans/" + SCAN_ID + "/Results",
    "#/scans/" + SCAN_ID + "/results.csv",
    "#/scans/" + SCAN_ID + "?x=1",
    "#/scans/%31b4e28ba-2fa1-41d2-883f-0016d3cca427",
    "#/scans/../hosts",
    "#/scans/run/",
    "#/scans/run/x",
    "#/scans/run/-1",
    "#/scans/run/1.0",
    "#/scans/run/" + MAX_ID + "9",
    "#/scans/run/7/x",
    "#/scans/run/７",
    "#/scans/run/" + SCAN_ID,
    "#/Scans",
    "#/scan/" + SCAN_ID,
    "#/schedules/",
    "#/schedules/1",
    "#/Schedules",
    "#/run-scan",
  ])("%j falls back to the host list", (hash) => {
    expect(parseHash(hash)).toEqual({ name: "hosts" });
  });
});
