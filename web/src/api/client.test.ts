/// <reference types="vite/client" />
// TASK-047 TEST (REQ-059; tests/m2/test-plan.md CHK-M2-281, CHK-M2-282).
// TS §6: one API under /api/v1; TS §6.3: same origin only (no CORS, CSP
// 'self'); #5: /healthz and /readyz sit outside /api/v1.
//
// The client is the product's own `api` object. Request is stubbed before it
// is imported (openapi-fetch reads globalThis.Request in createClient), so
// the raw URL the client builds is recorded before any origin is applied, and
// a middleware answers every call, so nothing leaves the test.
import { beforeAll, describe, expect, expectTypeOf, it, vi } from "vitest";

import source from "./client.ts?raw";
import type { components, paths } from "./schema";

type LoginResponse = components["schemas"]["LoginResponse"];
type Client = (typeof import("./client"))["api"];

const ORIGIN = "https://manager.test";
const built: string[] = [];
const sent: { method: string; url: string; body: string }[] = [];

class RecordingRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const raw = input instanceof Request ? input.url : String(input);
    built.push(raw);
    super(input instanceof Request ? input : new URL(raw, ORIGIN), init);
  }
}

const LOGIN_OK: LoginResponse = {
  token: "bsu_" + "T".repeat(43),
  role: "viewer",
  expires_at: "2026-10-22T08:00:00.000000Z",
  totp_enrolled: false,
  totp_verified: false,
};

let api: Client;

beforeAll(async () => {
  vi.stubGlobal("Request", RecordingRequest);
  ({ api } = await import("./client"));
  api.use({
    async onRequest({ request }) {
      sent.push({
        method: request.method,
        url: request.url,
        body: await request.clone().text(),
      });
      return new Response(JSON.stringify(LOGIN_OK), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });
});

describe("client.ts source (CHK-M2-282)", () => {
  it("names no absolute origin", () => {
    expect(source).not.toMatch(/https?:/i);
    expect(source).not.toMatch(/["'`]\/\/[^"'`\s]/);
    expect(source).not.toMatch(/\bwss?:/i);
  });

  it("creates the client with an empty baseUrl", () => {
    expect(source).toMatch(/createClient<paths>\(\{\s*baseUrl:\s*""\s*\}\)/);
  });
});

describe("requests stay on the page's origin with one /api/v1 prefix", () => {
  it("sends sign-in to /api/v1/auth/login, typed end to end", async () => {
    const body = { username: "alice", password: "twelve chars!" };
    const { data, error } = await api.POST("/api/v1/auth/login", { body });
    expect(built.at(-1)).toBe("/api/v1/auth/login");
    expect(sent.at(-1)).toEqual({
      method: "POST",
      url: `${ORIGIN}/api/v1/auth/login`,
      body: JSON.stringify(body),
    });
    expect(error).toBeUndefined();
    expect(data?.token).toBe(LOGIN_OK.token);
    expectTypeOf(data).toEqualTypeOf<LoginResponse | undefined>();
  });

  it("fills path parameters under the prefix", async () => {
    await api.GET("/api/v1/users/{user_id}", {
      params: { path: { user_id: 7 } },
    });
    expect(built.at(-1)).toBe("/api/v1/users/7");
    await api.DELETE("/api/v1/api-tokens/{token_id}", {
      params: { path: { token_id: 12 } },
    });
    expect(built.at(-1)).toBe("/api/v1/api-tokens/12");
  });

  it("keeps the health routes at the root (#5)", async () => {
    await api.GET("/healthz");
    expect(built.at(-1)).toBe("/healthz");
    await api.GET("/readyz");
    expect(built.at(-1)).toBe("/readyz");
  });

  it("refuses unknown paths, wrong methods and incomplete bodies at compile time", async () => {
    const u = "alice";
    const p = "twelve chars!";
    // @ts-expect-error -- the prefix is part of every user path
    await api.POST("/auth/login", { body: { username: u, password: p } });
    // @ts-expect-error -- the password is required
    await api.POST("/api/v1/auth/login", { body: { username: u } });
    // @ts-expect-error -- sign-in has no GET
    await api.GET("/api/v1/auth/login");
    expect(built.slice(-3)).toEqual([
      "/auth/login",
      "/api/v1/auth/login",
      "/api/v1/auth/login",
    ]);
  });
});

describe("generated paths (CHK-M2-281)", () => {
  it("has exactly the two health routes outside /api/v1", () => {
    expectTypeOf<Exclude<keyof paths, `/api/v1/${string}`>>().toEqualTypeOf<
      "/healthz" | "/readyz"
    >();
  });

  it("has every M2 user route", () => {
    type M2UserPaths =
      | "/api/v1/auth/login"
      | "/api/v1/auth/logout"
      | "/api/v1/auth/password"
      | "/api/v1/auth/totp/enrol"
      | "/api/v1/api-tokens"
      | "/api/v1/api-tokens/{token_id}"
      | "/api/v1/users"
      | "/api/v1/users/{user_id}";
    expectTypeOf<M2UserPaths>().toExtend<keyof paths>();
  });
});
