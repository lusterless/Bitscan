// TASK-116 TEST (TP-M5-09): CHK-M5-180 to CHK-M5-184, revised for the
// session cookie (owner decision 2026-11-12).
// Expected values: TS §6.2 (the bsu_ token lives in the HttpOnly
// __Host-bitscan_session cookie, never readable by page scripts and never in
// localStorage or sessionStorage; the web UI restores itself from
// GET /auth/session; a restricted admin session may call only TOTP enrolment
// and logout), TS §6.3 (every cookie request sends X-Bitscan-Request: 1),
// L1089 (admins must enrol TOTP, others are offered it), §8.1; REQ-120
// (1)-(4); #85 (a); PD-29 (role is a plain string, unknown = least privilege).
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
  restoreSession,
  sessionStatus,
  setSession,
  signOut,
  toRole,
  useSession,
  useSessionStatus,
  type SessionView,
} from "./session";

const A = bsu("A");
const B = bsu("B");
const PAGE = { items: [], next_cursor: null };
const CURRENT = {
  role: "operator",
  totp_enrolled: true,
  totp_verified: true,
  expires_at: "2026-10-25T20:00:00.000000Z",
};

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

describe("CHK-M5-180 requests: no bearer, always the CSRF header", () => {
  it("before setSession: no Authorization, X-Bitscan-Request: 1", async () => {
    await anyCalls();
    await api.POST("/api/v1/auth/login", {
      body: { username: "u", password: "p".repeat(12), totp_code: null },
    });
    expect(calls).toHaveLength(5);
    expect(calls.map((c) => c.authorization)).toEqual(Array(5).fill(null));
    expect(calls.map((c) => c.csrf)).toEqual(Array(5).fill("1"));
  });

  it("after setSession: the same on every method and path", async () => {
    setSession(loginResponse("viewer", true, A));
    await anyCalls();
    expect(calls.map((c) => c.method)).toEqual([
      "GET",
      "POST",
      "DELETE",
      "GET",
    ]);
    expect(calls.map((c) => c.authorization)).toEqual(Array(4).fill(null));
    expect(calls.map((c) => c.csrf)).toEqual(Array(4).fill("1"));
  });

  it("the token in a sign-in body is never sent back", async () => {
    setSession(loginResponse("viewer", true, A));
    await api.GET("/api/v1/agents");
    setSession(loginResponse("admin", true, B));
    await api.GET("/api/v1/agents");
    for (const call of calls) {
      expect(call.authorization).toBeNull();
      expect(call.url).not.toContain(A);
      expect(call.body).not.toContain(B);
    }
  });
});

describe("CHK-M5-181 a 401 ends only the session it was sent under", () => {
  it("clears the session on a 401", async () => {
    setSession(loginResponse("viewer", true, A));
    answer(() => problem(401, "unauthorized"));
    await api.GET("/api/v1/agents");
    expect(currentSession()).toBeNull();
  });

  it("keeps the new session when a 401 from before it arrives late", async () => {
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
    expect(currentSession()?.totpEnrolled).toBe(true);
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
      authorization: null,
      csrf: "1",
    });
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
    // The afterEach checks every recorded write, document.cookie and the URL.
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
});

describe("restoreSession: a reload keeps the session (TS §6.2)", () => {
  it("200 from GET /auth/session restores the view", async () => {
    answer(() => json(200, CURRENT));
    const { result } = renderHook(() => useSessionStatus());
    const done = restoreSession();
    expect(sessionStatus()).toBe("restoring");
    await act(() => done);
    expect(result.current).toBe("ready");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "GET",
      path: "/api/v1/auth/session",
      authorization: null,
      csrf: "1",
    });
    expect(currentSession()).toEqual({
      role: "operator",
      totpEnrolled: true,
      totpVerified: true,
      expiresAt: CURRENT.expires_at,
    });
  });

  it("401 starts signed out", async () => {
    answer(() => problem(401, "unauthorized"));
    await restoreSession();
    expect(currentSession()).toBeNull();
    expect(sessionStatus()).toBe("ready");
  });

  it("403 totp_enrolment_required is an admin who must enrol TOTP", async () => {
    answer(() => problem(403, "totp_enrolment_required"));
    await restoreSession();
    const view = currentSession() as SessionView;
    expect(view.role).toBe("admin");
    expect(nextScreen(view)).toBe("totp-required");
  });

  it.each([
    ["another 403", () => problem(403, "forbidden")],
    ["a 500", () => problem(500, "about:blank")],
    ["a network error", () => Promise.reject(new TypeError("network down"))],
  ] as const)("%s starts signed out", async (_name, reply) => {
    answer(reply);
    await restoreSession();
    expect(currentSession()).toBeNull();
    expect(sessionStatus()).toBe("ready");
  });

  it("a sign-in while restoring wins over a late answer", async () => {
    const late = deferred();
    answer(() => late.promise);
    const done = restoreSession();
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    setSession(loginResponse("viewer", true, A));
    late.resolve(json(200, { ...CURRENT, role: "admin" }));
    await done;
    expect(currentSession()?.role).toBe("viewer");
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
