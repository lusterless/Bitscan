// TASK-118 TEST (TP-M5-11): CHK-M5-200 to CHK-M5-205.
// Expected values: REQ-121 (1)-(5); TS §6.2 L1080 (bsu_ in memory), L1086-
// L1089 (login body, TOTP code, admins must enrol), §6.3 L1136 (429 with
// Retry-After); #48 (every refused sign-in looks the same); #85 (a), (e)
// (the TOTP field is shown to everyone; next screen per role and TOTP).
import {
  answer,
  bsu,
  calls,
  deferred,
  json,
  loginResponse,
  problem,
  resetHttp,
  watchSecrets,
  type Watch,
} from "../test/harness";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { clearSession, currentSession } from "../app/session";
import { SignIn } from "./SignIn";

const PASSWORD = "Correct-Horse-Battery-9";
const CODE = "123456";
const TOKEN = bsu("Q");
const CODE_LABEL = "TOTP code (required for admins and accounts with TOTP)";

let watch: Watch;

beforeEach(() => {
  resetHttp();
  clearSession();
  watch = watchSecrets();
});

afterEach(() => {
  const leaks = [
    ...watch.leaked(PASSWORD),
    ...watch.leaked(TOKEN),
    ...watch.leaked("Correct-Horse"),
  ];
  watch.stop();
  vi.useRealTimers();
  clearSession();
  expect(leaks).toEqual([]);
});

function field(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

function button(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Sign in" }) as HTMLButtonElement;
}

function fill(username: string, password: string, code: string): void {
  fireEvent.change(field("Username"), { target: { value: username } });
  fireEvent.change(field("Password"), { target: { value: password } });
  fireEvent.change(field(CODE_LABEL), { target: { value: code } });
}

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((r) => setTimeout(r, 0));
  }
}

/** Submit the form, wait for the request, then let the answer render. */
async function submit(): Promise<void> {
  const form = button().closest("form");
  if (form === null) {
    throw new Error("no form");
  }
  const before = calls.length;
  await act(async () => {
    fireEvent.submit(form);
    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(before));
    await settle();
  });
}

const submitAndSettle = submit;

describe("CHK-M5-200 the sign-in body", () => {
  it("is exactly {username, password, totp_code: null} for an empty code", async () => {
    answer(() => problem(401, "unauthorized"));
    render(<SignIn onSignedIn={vi.fn()} />);
    expect(field(CODE_LABEL)).toBeTruthy();
    fill(" alice ", PASSWORD, "");
    await submit();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.path).toBe("/api/v1/auth/login");
    expect(JSON.parse(calls[0]?.body ?? "")).toEqual({
      username: " alice ",
      password: PASSWORD,
      totp_code: null,
    });
    expect(Object.keys(JSON.parse(calls[0]?.body ?? ""))).toEqual([
      "username",
      "password",
      "totp_code",
    ]);
    expect(calls[0]?.authorization).toBeNull();
  });

  it("sends the code as the typed string", async () => {
    answer(() => problem(401, "unauthorized"));
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("bob", PASSWORD, "012345");
    await submit();
    expect(JSON.parse(calls[0]?.body ?? "").totp_code).toBe("012345");
  });
});

describe("CHK-M5-201 every 401 looks the same", () => {
  it("two different 401 problems show one message holding neither detail", async () => {
    const texts: string[] = [];
    for (const [type, detail] of [
      ["unauthorized", "DETAIL-ONE no such user"],
      ["totp_required", "DETAIL-TWO wrong TOTP code"],
    ] as const) {
      resetHttp();
      answer(() => problem(401, type, detail));
      const { unmount } = render(<SignIn onSignedIn={vi.fn()} />);
      fill("carol", PASSWORD, CODE);
      await submit();
      const alert = screen.getByRole("alert");
      texts.push(alert.textContent ?? "");
      expect(document.body.textContent).not.toContain("DETAIL-");
      unmount();
    }
    expect(texts[0]).toBe(texts[1]);
    expect(texts[0]).toBe(
      "Sign-in failed. Check your username, password and TOTP code.",
    );
    expect(currentSession()).toBeNull();
  });
});

describe("CHK-M5-202 a 429 holds the button for Retry-After", () => {
  it("Retry-After: 7 shows a 7-second wait and disables the button until then", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    answer(() =>
      problem(429, "rate_limited", "slow down", { "Retry-After": "7" }),
    );
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("dave", PASSWORD, CODE);
    const form = button().closest("form") as HTMLFormElement;
    await act(async () => {
      fireEvent.submit(form);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "Too many requests. Wait 7 seconds.",
    );
    expect(button().disabled).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_990);
    });
    expect(button().disabled).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(button().disabled).toBe(false);
    expect(calls).toHaveLength(1);
  });

  it("without Retry-After the button is not held", async () => {
    answer(() => problem(429, "rate_limited"));
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("dave", PASSWORD, CODE);
    await submit();
    expect(screen.getByRole("alert").textContent).toContain(
      "Too many requests. Wait a moment.",
    );
    expect(button().disabled).toBe(false);
  });
});

describe("CHK-M5-203 password field and clearing", () => {
  const outcomes: [string, () => Response | Promise<Response>][] = [
    ["success", () => json(200, loginResponse("viewer", true, TOKEN))],
    ["401", () => problem(401, "unauthorized")],
    ["429", () => problem(429, "rate_limited", null, { "Retry-After": "1" })],
    ["503", () => problem(503, "unavailable")],
    ["400", () => problem(400, "invalid_request", "bad")],
    ["network error", () => Promise.reject(new TypeError("down"))],
  ];

  it("the password input is type=password", () => {
    render(<SignIn onSignedIn={vi.fn()} />);
    expect(field("Password").type).toBe("password");
    expect(field(CODE_LABEL).type).not.toBe("password");
  });

  it.each(outcomes)(
    "password and code are empty after a %s",
    async (_n, reply) => {
      answer(reply);
      render(<SignIn onSignedIn={vi.fn()} />);
      fill("erin", PASSWORD, CODE);
      await submitAndSettle();
      expect(calls).toHaveLength(1);
      expect(field("Password").value).toBe("");
      expect(field(CODE_LABEL).value).toBe("");
      expect(field("Username").value).toBe("erin");
      expect(document.body.innerHTML).not.toContain(PASSWORD);
    },
  );

  it("they are empty while the request is still in flight, and the button is disabled", async () => {
    const pending = deferred();
    answer(() => pending.promise);
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("erin", PASSWORD, CODE);
    await act(async () => {
      fireEvent.submit(button().closest("form") as HTMLFormElement);
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(calls).toHaveLength(1);
    expect(field("Password").value).toBe("");
    expect(field(CODE_LABEL).value).toBe("");
    expect(button().disabled).toBe(true);
    await act(async () => {
      pending.resolve(problem(401, "unauthorized"));
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(button().disabled).toBe(false);
  });
});

describe("CHK-M5-204 503 and success", () => {
  it("503 says the manager is unavailable", async () => {
    answer(() => problem(503, "unavailable", "db down"));
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("frank", PASSWORD, CODE);
    await submit();
    expect(screen.getByRole("alert").textContent).toContain(
      "The manager is unavailable. Try again later.",
    );
  });

  it("a network failure says the same", async () => {
    answer(() => Promise.reject(new TypeError("down")));
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("frank", PASSWORD, CODE);
    await submit();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });

  it("a 400 shows its detail as text", async () => {
    const hostile = "<img src=x onerror=alert(1)>";
    answer(() => problem(400, "invalid_request", hostile));
    const { container } = render(<SignIn onSignedIn={vi.fn()} />);
    fill("frank", PASSWORD, CODE);
    await submit();
    expect(screen.getByText(hostile)).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
  });

  it.each([
    ["admin", false, "totp-required"],
    ["admin", true, "hosts"],
    ["operator", false, "totp-offer"],
    ["operator", true, "hosts"],
    ["viewer", false, "totp-offer"],
    ["viewer", true, "hosts"],
  ] as const)(
    "%s with totp_enrolled %s goes to %s and the session is set",
    async (role, enrolled, next) => {
      answer(() => json(200, loginResponse(role, enrolled, TOKEN)));
      const onSignedIn = vi.fn();
      render(<SignIn onSignedIn={onSignedIn} />);
      fill("gina", PASSWORD, enrolled ? CODE : "");
      await submit();
      expect(onSignedIn).toHaveBeenCalledTimes(1);
      expect(onSignedIn).toHaveBeenCalledWith(next);
      expect(currentSession()?.role).toBe(role);
      answer(() => json(200, { items: [], next_cursor: null }));
      await api.GET("/api/v1/agents");
      expect(calls.at(-1)?.authorization).toBe("Bearer " + TOKEN);
      expect(document.body.innerHTML).not.toContain(TOKEN);
    },
  );

  it("shows the password-changed notice", () => {
    render(<SignIn onSignedIn={vi.fn()} notice="password-changed" />);
    expect(screen.getByRole("status").textContent).toBe(
      "Your password was changed. Sign in again.",
    );
  });
});

describe("CHK-M5-205 nothing else is sent, nothing is stored", () => {
  it("no request before submit; the sign-in is the only request", async () => {
    answer(() => json(200, loginResponse("viewer", true, TOKEN)));
    render(<SignIn onSignedIn={vi.fn()} />);
    fill("hank", PASSWORD, CODE);
    expect(calls).toHaveLength(0);
    await submit();
    expect(calls.map((c) => c.method + " " + c.path)).toEqual([
      "POST /api/v1/auth/login",
    ]);
    // The afterEach checks storage, cookie, IndexedDB, console, URL and
    // history for the password and the token.
  });
});
