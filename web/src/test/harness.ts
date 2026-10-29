// Test double for the generated client (tester-owned; M5 TP-M5-09 to -19).
//
// openapi-fetch captures globalThis.Request and globalThis.fetch when
// src/api/client.ts is evaluated, so every test file imports this module
// FIRST: evaluating it stubs both before the client exists. No request ever
// leaves the test; each one is recorded and answered by the current handler.
// The lint bans the `fetch` identifier and the storage identifiers in test
// files too, so stubs go through vi.stubGlobal("fetch", ...) and prototypes.
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

export const ORIGIN = "https://manager.test";

export interface Call {
  readonly method: string;
  readonly path: string;
  readonly query: URLSearchParams;
  /** path plus query string, as sent */
  readonly url: string;
  readonly authorization: string | null;
  /** The Content-Type header as sent (M7: the multipart upload). */
  readonly contentType: string | null;
  readonly body: string;
  /**
   * The FormData given to `new Request` (M7 upload). undici serialises a
   * jsdom FormData without its file names and bytes, so tests read the
   * entries here instead of `body`.
   */
  readonly form: FormData | null;
}

export type Handler = (call: Call) => Response | Promise<Response>;

const forms = new WeakMap<Request, FormData>();

class ResolvingRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (input instanceof Request) {
      super(input, init);
    } else {
      super(new URL(String(input), ORIGIN), init);
    }
    const body = init?.body;
    if (body instanceof FormData) {
      forms.set(this, body);
    } else if (input instanceof Request && forms.has(input)) {
      forms.set(this, forms.get(input) as FormData);
    }
  }
}

export const calls: Call[] = [];

function unanswered(call: Call): Response {
  return json(599, {
    type: "test_unanswered",
    title: "unanswered",
    status: 599,
    detail: call.method + " " + call.url,
  });
}

let handler: Handler = unanswered;

/** Every later request is answered by `next` (until the next answer()). */
export function answer(next: Handler): void {
  handler = next;
}

export function resetHttp(): void {
  calls.length = 0;
  handler = unanswered;
}

async function fakeNetwork(input: Request | string | URL): Promise<Response> {
  const request =
    input instanceof Request ? input : new ResolvingRequest(String(input));
  const url = new URL(request.url);
  const call: Call = {
    method: request.method,
    path: url.pathname,
    query: url.searchParams,
    url: url.pathname + url.search,
    authorization: request.headers.get("Authorization"),
    contentType: request.headers.get("Content-Type"),
    body: await request.clone().text(),
    form: forms.get(request) ?? null,
  };
  calls.push(call);
  return handler(call);
}

vi.stubGlobal("Request", ResolvingRequest);
vi.stubGlobal("fetch", vi.fn(fakeNetwork));

afterEach(() => {
  cleanup();
});

export function json(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function problem(
  status: number,
  type: string,
  detail: string | null = null,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ type, title: "t", status, detail }), {
    status,
    headers: { "Content-Type": "application/problem+json", ...headers },
  });
}

export function noContent(): Response {
  return new Response(null, { status: 204 });
}

/** A response whose arrival the test controls. */
export interface Deferred {
  readonly promise: Promise<Response>;
  resolve(response: Response): void;
}

export function deferred(): Deferred {
  let resolve: (r: Response) => void = () => undefined;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve: (r) => resolve(r) };
}

/** Requests whose path is `path` (any query), in order. */
export function callsTo(path: string, method = "GET"): Call[] {
  return calls.filter((c) => c.path === path && c.method === method);
}

/** Query as a plain object (each key once; the tests send none twice). */
export function queryOf(call: Call): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of call.query) {
    out[k] = v;
  }
  return out;
}

export function loginResponse(
  role: string,
  totpEnrolled: boolean,
  token: string,
  totpVerified = totpEnrolled,
): {
  token: string;
  role: string;
  expires_at: string;
  totp_enrolled: boolean;
  totp_verified: boolean;
} {
  return {
    token,
    role,
    expires_at: "2026-10-25T20:00:00.000000Z",
    totp_enrolled: totpEnrolled,
    totp_verified: totpVerified,
  };
}

export function bsu(fill: string): string {
  return "bsu_" + fill.repeat(43).slice(0, 43);
}

// ------------------------------------------------------------ secret watch

/**
 * Records every value written to Web Storage, document.cookie, IndexedDB
 * (open), every console method and the URL, so a test can assert a secret
 * never reached any of them (REQ-120 (1), TS §8.1).
 */
export interface Watch {
  /** Every recorded argument, stringified. */
  readonly seen: string[];
  /** Also checks location.href and history state now. */
  leaked(secret: string): string[];
  stop(): void;
}

function text(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

export function watchSecrets(): Watch {
  const seen: string[] = [];
  const record = (...args: unknown[]): void => {
    for (const a of args) {
      seen.push(text(a));
    }
  };
  const restore: (() => void)[] = [];

  for (const method of ["setItem", "getItem", "key", "removeItem"] as const) {
    const spy = vi
      .spyOn(Storage.prototype, method)
      .mockImplementation((...args: unknown[]) => {
        record("storage." + method, ...args);
        return null;
      });
    restore.push(() => spy.mockRestore());
  }

  const cookie = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
  if (cookie !== undefined) {
    Object.defineProperty(Document.prototype, "cookie", {
      configurable: true,
      get: () => "",
      set: (value: unknown) => record("cookie", value),
    });
    restore.push(() =>
      Object.defineProperty(Document.prototype, "cookie", cookie),
    );
  }

  const idb = {
    open: (...args: unknown[]) => {
      record("indexedDB.open", ...args);
      return {};
    },
    deleteDatabase: (...args: unknown[]) => {
      record("indexedDB.deleteDatabase", ...args);
      return {};
    },
  };
  vi.stubGlobal("indexedDB", idb);
  restore.push(() => vi.stubGlobal("indexedDB", undefined));

  const methods = Object.keys(console).filter(
    (k) =>
      typeof (console as unknown as Record<string, unknown>)[k] === "function",
  );
  for (const name of methods) {
    const spy = vi
      .spyOn(console, name as keyof Console)
      .mockImplementation((...args: unknown[]) => {
        record("console." + name, ...args);
      });
    restore.push(() => spy.mockRestore());
  }

  for (const method of ["pushState", "replaceState"] as const) {
    const original = History.prototype[method];
    const spy = vi
      .spyOn(History.prototype, method)
      .mockImplementation(function (this: History, ...args: unknown[]) {
        record("history." + method, ...args);
        return original.apply(this, args as Parameters<History["pushState"]>);
      });
    restore.push(() => spy.mockRestore());
  }

  return {
    seen,
    leaked(secret: string): string[] {
      const hits = seen.filter((s) => s.includes(secret));
      if (window.location.href.includes(secret)) {
        hits.push("location.href");
      }
      if (text(window.history.state).includes(secret)) {
        hits.push("history.state");
      }
      return hits;
    },
    stop(): void {
      for (const r of restore.reverse()) {
        r();
      }
    },
  };
}
