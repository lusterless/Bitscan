// TASK-116 TEST (TP-M5-09): CHK-M5-185, CHK-M5-186.
// Expected values: the plan TASK-116 message table (REQ-126 (1), #85 (b)),
// TS §6.3 L1133 (RFC 9457 problem details), L1136 (429 with Retry-After),
// TS §8.1 / web-ui rule ("prompt for TOTP rather than fall back to an API
// token"), CHK-M5-347.
import { describe, expect, it } from "vitest";

import { messageFor, toProblem, type ProblemInfo } from "./problems";

const CANARY = "CANARY-<b>x</b>-9f2c";

function info(
  status: number,
  type = "about:blank",
  retryAfterS: number | null = null,
  detail: string | null = CANARY,
): ProblemInfo {
  return { status, type, detail, retryAfterS };
}

const SIGN_IN_AGAIN =
  "This action needs a sign-in with your TOTP code. Sign in again with your password and code.";
const PAUSED =
  "Sensitive actions are paused while the audit log cannot be shipped. Try again later.";

describe("CHK-M5-185 messageFor, one case per plan-table row", () => {
  it.each([
    [info(403, "totp_session_required"), SIGN_IN_AGAIN, "sign-in-again"],
    [info(503, "audit_sink_unavailable"), PAUSED, null],
    [info(403, "forbidden"), "Your role does not allow this.", null],
    [
      info(403, "totp_enrolment_required"),
      "Set up TOTP to continue.",
      "totp-enrol",
    ],
    [info(401, "unauthorized"), "Your session has ended. Sign in again.", null],
    [info(401, "about:blank"), "Your session has ended. Sign in again.", null],
    [
      info(429, "rate_limited", 7),
      "Too many requests. Wait 7 seconds.",
      "wait",
    ],
    [
      info(429, "rate_limited", 0),
      "Too many requests. Wait 0 seconds.",
      "wait",
    ],
    [
      info(429, "rate_limited", null),
      "Too many requests. Wait a moment.",
      "wait",
    ],
    [
      info(429, "about:blank", 30),
      "Too many requests. Wait 30 seconds.",
      "wait",
    ],
    [
      info(503, "about:blank"),
      "The manager is unavailable. Try again later.",
      null,
    ],
    [
      info(503, "unavailable"),
      "The manager is unavailable. Try again later.",
      null,
    ],
    [info(400, "invalid_request"), "Request failed (status 400).", null],
    [info(404, "not_found"), "Request failed (status 404).", null],
    [info(409, "conflict"), "Request failed (status 409).", null],
    [info(500, "about:blank"), "Request failed (status 500).", null],
  ] as const)("%j", (problem, text, action) => {
    expect(messageFor(problem)).toEqual({ text, action });
  });

  it("an unknown type falls back to the status text", () => {
    for (const status of [400, 403, 404, 418, 500, 502]) {
      expect(messageFor(info(status, "something_new")).text).toBe(
        "Request failed (status " + String(status) + ").",
      );
    }
    expect(messageFor(info(401, "something_new")).text).toBe(
      "Your session has ended. Sign in again.",
    );
  });

  it("the type decides before the status (the M2 dependency types)", () => {
    expect(messageFor(info(401, "totp_session_required")).action).toBe(
      "sign-in-again",
    );
    expect(messageFor(info(500, "audit_sink_unavailable")).text).toBe(PAUSED);
  });

  it("no message carries response text", () => {
    const types = [
      "totp_session_required",
      "audit_sink_unavailable",
      "forbidden",
      "totp_enrolment_required",
      "unauthorized",
      CANARY,
    ];
    for (const status of [400, 401, 403, 404, 409, 429, 500, 503]) {
      for (const type of types) {
        const m = messageFor(info(status, type, 5));
        expect(m.text).not.toContain("CANARY");
        expect(m.text).not.toContain("<");
      }
    }
  });

  it("the TOTP-session message never asks for an API token (CHK-M5-347)", () => {
    const m = messageFor(info(403, "totp_session_required"));
    expect(m.action).toBe("sign-in-again");
    expect(m.text.toLowerCase()).not.toMatch(/api|bsk_|token/);
    expect(m.text).toContain("TOTP");
  });
});

function response(
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(null, { status, headers });
}

describe("CHK-M5-186 toProblem", () => {
  it("reads string type and detail and the status from the response", () => {
    expect(
      toProblem(
        { type: "forbidden", title: "x", status: 999, detail: "No." },
        response(403),
      ),
    ).toEqual({
      status: 403,
      type: "forbidden",
      detail: "No.",
      retryAfterS: null,
    });
  });

  it.each([
    [{ type: 7, detail: 8 }],
    [{ type: null, detail: null }],
    [{ type: ["forbidden"], detail: { a: 1 } }],
    [{}],
    ["forbidden"],
    [null],
    [undefined],
    [42],
    [["type", "detail"]],
  ])("a non-problem body %j gives about:blank and null", (body) => {
    expect(toProblem(body, response(400))).toEqual({
      status: 400,
      type: "about:blank",
      detail: null,
      retryAfterS: null,
    });
  });

  it("keeps a string detail even when type is not a string", () => {
    const p = toProblem(
      { type: 1, detail: "<img src=x onerror=alert(1)>" },
      response(400),
    );
    expect(p.type).toBe("about:blank");
    expect(p.detail).toBe("<img src=x onerror=alert(1)>");
  });

  it.each([
    ["7", 7],
    ["0", 0],
    ["120", 120],
    ["-1", null],
    ["1.5", null],
    ["Wed, 21 Oct 2026 07:28:00 GMT", null],
    ["", null],
    // Headers drop surrounding whitespace (RFC 9110 OWS), so " 7" is 7.
    [" 7", 7],
    ["7 7", null],
    ["+7", null],
    ["1e3", null],
    ["0x10", null],
    // A header value holds only bytes up to 0xFF: a Latin-1 superscript digit.
    ["²", null],
    ["7¹", null],
  ])("Retry-After %j -> %j", (value, want) => {
    expect(
      toProblem(
        { type: "rate_limited" },
        response(429, { "Retry-After": value }),
      ).retryAfterS,
    ).toBe(want);
  });

  it("an absent Retry-After is null", () => {
    expect(
      toProblem({ type: "rate_limited" }, response(429)).retryAfterS,
    ).toBeNull();
  });
});

// TASK-168 TEST (TP-M7-29, CHK-M7-310): REQ-183 problem mapping.
// Expected values: the lead's 503 rule (work/decisions.md 2026-10-27 "Web: how
// the UI shows the #102 start-up 503"): a valid Retry-After gives "The manager
// is not ready yet. Try again in N seconds." with action "wait"; no, an
// invalid or an HTTP-date Retry-After gives the CHK-M5-185 generic text; the
// detail is never read. #98 (e) / TS §4.1 L522: policy_managed_on_server.
const NOT_READY = (n: string): string =>
  "The manager is not ready yet. Try again in " + n + ".";
const GENERIC_503 = "The manager is unavailable. Try again later.";
const SERVER_FOLDER =
  "This policy is managed in the server folder; change its file there.";

describe("CHK-M7-310 (TASK-168) policy_managed_on_server", () => {
  it.each([409, 400, 403, 404, 500, 503])(
    "status %i with the type gives the server-folder text, no action",
    (status) => {
      expect(messageFor(info(status, "policy_managed_on_server", 10))).toEqual({
        text: SERVER_FOLDER,
        action: null,
      });
    },
  );

  it("the text names neither an API token nor the detail", () => {
    const m = messageFor(info(409, "policy_managed_on_server"));
    expect(m.text).not.toContain("CANARY");
    expect(m.text.toLowerCase()).not.toMatch(/api|bsk_|token/);
  });

  it("a 409 without the type keeps the generic status text", () => {
    expect(messageFor(info(409, "about:blank")).text).toBe(
      "Request failed (status 409).",
    );
  });
});

describe("CHK-M7-310 (TASK-168) the #102 start-up 503", () => {
  it.each([
    [10, "10 seconds"],
    [1, "1 second"],
    [2, "2 seconds"],
    [0, "0 seconds"],
    [999999999, "999999999 seconds"],
  ] as const)("Retry-After %i -> not-ready text and wait", (s, words) => {
    expect(messageFor(info(503, "about:blank", s))).toEqual({
      text: NOT_READY(words),
      action: "wait",
    });
  });

  it("no Retry-After keeps the generic text (CHK-M5-185 unchanged)", () => {
    expect(messageFor(info(503, "about:blank", null))).toEqual({
      text: GENERIC_503,
      action: null,
    });
  });

  it.each([
    ["10", NOT_READY("10 seconds"), "wait"],
    ["1", NOT_READY("1 second"), "wait"],
    ["999999999", NOT_READY("999999999 seconds"), "wait"],
    ["Wed, 21 Oct 2026 07:28:00 GMT", GENERIC_503, null],
    ["-1", GENERIC_503, null],
    ["1.5", GENERIC_503, null],
    ["abc", GENERIC_503, null],
    ["", GENERIC_503, null],
    ["1e3", GENERIC_503, null],
  ] as const)("through toProblem: header %j -> %j", (header, text, action) => {
    const p = toProblem(
      { type: "about:blank", title: "t", status: 503, detail: CANARY },
      response(503, { "Retry-After": header }),
    );
    expect(messageFor(p)).toEqual({ text, action });
  });

  it("through toProblem: an absent header and a non-problem body", () => {
    expect(messageFor(toProblem(undefined, response(503)))).toEqual({
      text: GENERIC_503,
      action: null,
    });
    expect(
      messageFor(toProblem(null, response(503, { "Retry-After": "10" }))),
    ).toEqual({ text: NOT_READY("10 seconds"), action: "wait" });
  });

  it("the detail is never read: the text depends on the header only", () => {
    for (const detail of [
      null,
      CANARY,
      "The manager is starting",
      "Retry-After: 99",
      "starting up; try again in 5 seconds",
    ]) {
      expect(messageFor(info(503, "about:blank", null, detail))).toEqual({
        text: GENERIC_503,
        action: null,
      });
      expect(messageFor(info(503, "about:blank", 10, detail))).toEqual({
        text: NOT_READY("10 seconds"),
        action: "wait",
      });
    }
  });

  it("a typed 503 keeps its type's text even with Retry-After", () => {
    expect(messageFor(info(503, "audit_sink_unavailable", 10))).toEqual({
      text: PAUSED,
      action: null,
    });
  });

  it("an unknown type: header decides on 503, generic text elsewhere", () => {
    expect(messageFor(info(503, "something_new", 10))).toEqual({
      text: NOT_READY("10 seconds"),
      action: "wait",
    });
    expect(messageFor(info(503, "something_new", null))).toEqual({
      text: GENERIC_503,
      action: null,
    });
    for (const status of [400, 404, 409, 500, 502]) {
      expect(messageFor(info(status, "something_new", 10))).toEqual({
        text: "Request failed (status " + String(status) + ").",
        action: null,
      });
    }
  });

  it("Retry-After does not change the other statuses", () => {
    expect(messageFor(info(500, "about:blank", 10)).text).toBe(
      "Request failed (status 500).",
    );
    expect(messageFor(info(502, "about:blank", 10)).text).toBe(
      "Request failed (status 502).",
    );
    expect(messageFor(info(401, "about:blank", 10)).text).toBe(
      "Your session has ended. Sign in again.",
    );
  });
});
