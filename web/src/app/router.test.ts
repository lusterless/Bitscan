// TASK-116 TEST (TP-M5-09): CHK-M5-187.
// Expected values: the plan TASK-116 hash table (PD-28 (d) hash routes;
// anything else is the host list; host ids are hyphenated UUIDs, lower-cased).
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  formatHash,
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
