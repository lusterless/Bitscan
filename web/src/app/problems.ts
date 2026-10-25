/** An RFC 9457 problem answer, reduced to what the UI shows (TS §6.3). */
export interface ProblemInfo {
  readonly status: number;
  /** "about:blank" when the body is not a problem. */
  readonly type: string;
  /** Server text: shown as a text node only, never as HTML. */
  readonly detail: string | null;
  readonly retryAfterS: number | null;
}

export type ProblemAction = "sign-in-again" | "totp-enrol" | "wait" | null;

export interface ProblemMessage {
  /** Fixed text; never built from response text. */
  readonly text: string;
  readonly action: ProblemAction;
}

interface BodyFields {
  readonly type: string | null;
  readonly detail: string | null;
}

/** Only string `type` and `detail` count; any other body shape gives nulls. */
function bodyFields(body: unknown): BodyFields {
  if (typeof body !== "object" || body === null) {
    return { type: null, detail: null };
  }
  return {
    type: "type" in body && typeof body.type === "string" ? body.type : null,
    detail:
      "detail" in body && typeof body.detail === "string" ? body.detail : null,
  };
}

/** Seconds as a non-negative integer; an HTTP date or anything else gives null. */
function retryAfterSeconds(value: string | null): number | null {
  if (value === null || value.length === 0 || value.length > 9) {
    return null;
  }
  for (const ch of value) {
    if (ch < "0" || ch > "9") {
      return null;
    }
  }
  return Number(value);
}

/** `error` is the parsed body openapi-fetch returns for a non-2xx answer. */
export function toProblem(error: unknown, response: Response): ProblemInfo {
  const fields = bodyFields(error);
  return {
    status: response.status,
    type: fields.type ?? "about:blank",
    detail: fields.detail,
    retryAfterS: retryAfterSeconds(response.headers.get("Retry-After")),
  };
}

function waitText(seconds: number | null): string {
  if (seconds === null) {
    return "Too many requests. Wait a moment.";
  }
  return seconds === 1
    ? "Too many requests. Wait 1 second."
    : "Too many requests. Wait " + String(seconds) + " seconds.";
}

/** REQ-126: fixed messages. Screen-specific texts (409, 404) stay in the screens. */
export function messageFor(problem: ProblemInfo): ProblemMessage {
  switch (problem.type) {
    case "totp_session_required":
      // #85 (b): no step-up route; the only way to a TOTP-verified session is
      // to sign in again with password and code. Never ask for an API token.
      return {
        text: "This action needs a sign-in with your TOTP code. Sign in again with your password and code.",
        action: "sign-in-again",
      };
    case "audit_sink_unavailable":
      return {
        text: "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
        action: null,
      };
    case "forbidden":
      return { text: "Your role does not allow this.", action: null };
    case "totp_enrolment_required":
      return { text: "Set up TOTP to continue.", action: "totp-enrol" };
  }
  switch (problem.status) {
    case 401:
      return { text: "Your session has ended. Sign in again.", action: null };
    case 429:
      return { text: waitText(problem.retryAfterS), action: "wait" };
    case 503:
      return {
        text: "The manager is unavailable. Try again later.",
        action: null,
      };
    default:
      return {
        text: "Request failed (status " + String(problem.status) + ").",
        action: null,
      };
  }
}
