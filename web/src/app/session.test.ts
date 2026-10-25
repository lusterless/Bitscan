// TASK-116 TEST (TP-M5-09): CHK-M5-180 to CHK-M5-184.
// Expected values: TS §6.2 L1076 (every call sends Authorization: Bearer),
// L1080 (bsu_ held in memory, never in localStorage), L1089 (admins must
// enrol TOTP, others are offered it), §8.1 (stolen web session); REQ-120
// (1)-(4); #85 (a), (c); PD-29 (role is a plain string, unknown = least
// privilege); plan TASK-116 rules 1-7.
import {
  answer,
  bsu,
  calls,
  deferred,
  json,
  loginResponse,
  noContent,
  problem,
  resetHttp,
  watchSecrets,
  type Watch,
} from "../test/harness";

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import {
  clearSession,
  currentSession,
  nextScreen,
  setSession,
  signOut,
  toRole,
  useSession,
  type SessionView,
} from "./session";

const A = bsu("A");
const B = bsu("B");
const PAGE = { items: [], next_cursor: null };

let watch: Watch;

beforeEach(() => {
  resetHttp();
  clearSession();
  watch = watchSecrets();
  answer(() => json(200, PAGE));
});

afterEach(() => {
  const leaks = [...watch.leaked(A), ...watch.leaked(B)];
  watch.stop();
  clearSession();
  expect(leaks).toEqual([]);
});

async function anyCalls(): Promise<void> {
  await api.GET("/api/v1/agents", { params: { query: { limit: 50 } } });
  await api.POST("/api/v1/enrollment-tokens", {
    body: {
      max_uses: 1,
      expires_in_hours: 24,
      allowed_cidrs: null,
      auto_approve: false,
    },
  });
  await api.DELETE("/api/v1/enrollment-tokens/{token_id}", {
    params: { path: { token_id: 7 } },
  });
  await api.GET("/api/v1/packages/search", { params: { query: { q: "ssl" } } });
}

describe("CHK-M5-180 the bearer header", () => {
  it("is absent before setSession", async () => {
    await anyCalls();
    await api.POST("/api/v1/auth/login", {
      body: { username: "u", password: "p".repeat(12), totp_code: null },
    });
    expect(calls).toHaveLength(5);
    expect(calls.map((c) => c.authorization)).toEqual([
      null,
      null,
      null,
      null,
      null,
    ]);
  });

  it("is on every request after setSession, any method and path", async () => {
    setSession(loginResponse("viewer", true, A));
    await anyCalls();
    expect(calls.map((c) => c.method)).toEqual([
      "GET",
      "POST",
      "DELETE",
      "GET",
    ]);
    expect(calls.map((c) => c.authorization)).toEqual(
      Array(4).fill("Bearer " + A),
    );
  });

  it("is swapped by a second setSession for the next request", async () => {
    setSession(loginResponse("viewer", true, A));
    await api.GET("/api/v1/agents");
    setSession(loginResponse("admin", true, B));
    await api.GET("/api/v1/agents");
    expect(calls.map((c) => c.authorization)).toEqual([
      "Bearer " + A,
      "Bearer " + B,
    ]);
  });

  it("is gone after clearSession", async () => {
    setSession(loginResponse("viewer", true, A));
    clearSession();
    await api.GET("/api/v1/agents");
    expect(calls[0]?.authorization).toBeNull();
  });
});

describe("CHK-M5-181 a 401 ends only the session it was sent with", () => {
  it("clears the session when the 401 carried the current token", async () => {
    setSession(loginResponse("viewer", true, A));
    answer(() => problem(401, "unauthorized"));
    await api.GET("/api/v1/agents");
    expect(currentSession()).toBeNull();
    answer(() => json(200, PAGE));
    await api.GET("/api/v1/agents");
    expect(calls[1]?.authorization).toBeNull();
  });

  it("keeps the new session when a 401 for an older token arrives late", async () => {
    setSession(loginResponse("viewer", false, A));
    const late = deferred();
    answer(() => late.promise);
    const inFlight = api.GET("/api/v1/agents");
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    setSession(loginResponse("viewer", true, B));
    late.resolve(
      new Response(JSON.stringify({ type: "unauthorized" }), { status: 401 }),
    );
    await inFlight;
    expect(calls[0]?.authorization).toBe("Bearer " + A);
    expect(currentSession()?.totpEnrolled).toBe(true);
    answer(() => json(200, PAGE));
    await api.GET("/api/v1/agents");
    expect(calls[1]?.authorization).toBe("Bearer " + B);
  });

  it("changes nothing for a 401 with no session (sign-in refused)", async () => {
    const seen = vi.fn();
    const { result } = renderHook(() => {
      seen();
      return useSession();
    });
    const renders = seen.mock.calls.length;
    answer(() => problem(401, "unauthorized"));
    await api.POST("/api/v1/auth/login", {
      body: { username: "u", password: "p".repeat(12), totp_code: null },
    });
    expect(currentSession()).toBeNull();
    expect(result.current).toBeNull();
    expect(seen.mock.calls.length).toBe(renders);
  });

  it.each([403, 404, 409, 429, 500, 503])(
    "keeps the session on a %i",
    async (status) => {
      setSession(loginResponse("operator", true, A));
      answer(() => problem(status, "forbidden"));
      await api.GET("/api/v1/agents");
      expect(currentSession()?.role).toBe("operator");
      answer(() => json(200, PAGE));
      await api.GET("/api/v1/agents");
      expect(calls[1]?.authorization).toBe("Bearer " + A);
    },
  );
});

describe("CHK-M5-182 signOut always ends the session", () => {
  const replies: [string, () => Response | Promise<Response>][] = [
    ["204", () => noContent()],
    ["401", () => problem(401, "unauthorized")],
    ["500", () => problem(500, "about:blank")],
    ["a network error", () => Promise.reject(new TypeError("network down"))],
  ];

  it.each(replies)("with logout answering %s", async (_name, reply) => {
    setSession(loginResponse("admin", true, A));
    answer(reply);
    await expect(signOut()).resolves.toBeUndefined();
    expect(currentSession()).toBeNull();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/auth/logout",
      authorization: "Bearer " + A,
    });
    answer(() => json(200, PAGE));
    await api.GET("/api/v1/agents");
    expect(calls[1]?.authorization).toBeNull();
  });
});

describe("CHK-M5-183 the token reaches no storage, cookie, console or URL", () => {
  it("over set, swap, requests, 401, re-set and sign-out", async () => {
    setSession(loginResponse("admin", true, A));
    await anyCalls();
    setSession(loginResponse("admin", true, B));
    answer(() => problem(401, "unauthorized", "token " + B));
    await api.GET("/api/v1/agents");
    setSession(loginResponse("viewer", true, A));
    answer(() => Promise.reject(new TypeError("down " + A)));
    await signOut();
    // The afterEach checks every recorded write and the URL for A and B.
    expect(calls.length).toBeGreaterThanOrEqual(6);
  });

  it("the view screens read holds no token", () => {
    setSession(loginResponse("admin", false, A, false));
    const view = currentSession();
    expect(view).not.toBeNull();
    expect(Object.keys(view as SessionView).sort()).toEqual(
      ["expiresAt", "role", "totpEnrolled", "totpVerified"].sort(),
    );
    expect(JSON.stringify(view)).not.toContain(A);
    expect(Object.isFrozen(view)).toBe(true);
    expect(view).toEqual({
      role: "admin",
      totpEnrolled: false,
      totpVerified: false,
      expiresAt: "2026-10-25T20:00:00.000000Z",
    });
  });

  it("useSession follows set and clear with a stable snapshot", () => {
    const { result, rerender } = renderHook(() => useSession());
    expect(result.current).toBeNull();
    act(() => setSession(loginResponse("operator", true, A)));
    const first = result.current;
    expect(first?.role).toBe("operator");
    rerender();
    expect(result.current).toBe(first);
    act(() => clearSession());
    expect(result.current).toBeNull();
  });

  it("a reload (fresh modules) starts signed out", async () => {
    setSession(loginResponse("admin", true, A));
    vi.resetModules();
    const fresh = await import("./session");
    expect(fresh.currentSession()).toBeNull();
    const client = await import("../api/client");
    await client.api.GET("/api/v1/agents");
    expect(calls.at(-1)?.authorization).toBeNull();
  });
});

describe("CHK-M5-184 nextScreen and toRole", () => {
  it.each([
    ["admin", false, "totp-required"],
    ["admin", true, "hosts"],
    ["operator", false, "totp-offer"],
    ["operator", true, "hosts"],
    ["viewer", false, "totp-offer"],
    ["viewer", true, "hosts"],
  ] as const)("%s with totp_enrolled %s -> %s", (role, enrolled, want) => {
    expect(
      nextScreen({
        role,
        totpEnrolled: enrolled,
        totpVerified: enrolled,
        expiresAt: "x",
      }),
    ).toBe(want);
  });

  it.each([
    ["viewer", "viewer"],
    ["operator", "operator"],
    ["admin", "admin"],
    ["Admin", "viewer"],
    ["ADMIN", "viewer"],
    ["root", "viewer"],
    ["", "viewer"],
    [" admin", "viewer"],
  ])("toRole(%j) is %s", (value, want) => {
    expect(toRole(value)).toBe(want);
  });

  it("an unknown role from the server becomes viewer in the view", () => {
    setSession(loginResponse("superuser", false, A));
    expect(currentSession()?.role).toBe("viewer");
    expect(nextScreen(currentSession() as SessionView)).toBe("totp-offer");
  });
});
