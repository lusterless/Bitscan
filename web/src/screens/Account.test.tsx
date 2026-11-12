// TASK-119 TEST (TP-M5-12): CHK-M5-210 to CHK-M5-216.
// Expected values: REQ-122 (1)-(6), REQ-123 (1)-(3); TS §6.2 L1085-L1089
// (POST /auth/totp/enrol: {} starts, {current_password, current_code}
// replaces, {totp_code} confirms and answers a new TOTP-verified session),
// L1086/L1097 (password change, at least 12 characters); #53 (a) (a changed
// password ends every session); #85 (a) (offer after sign-in, "Not now");
// lead ruling 2026-10-25 "TASK-119 REQ-122 (3) reading" (a 403 on confirm
// stays on the TOTP screen, returns to the start step, the old secret gone
// from memory and the QR element).
import {
  answer,
  bsu,
  calls,
  json,
  loginResponse,
  noContent,
  problem,
  resetHttp,
  watchSecrets,
  type Call,
  type Watch,
} from "../test/harness";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { clearSession, currentSession, setSession } from "../app/session";
import { PasswordChange } from "./PasswordChange";
import { TotpEnrol } from "./TotpEnrol";

const OLD = bsu("O");
const NEW = bsu("N");
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const URI =
  "otpauth://totp/Bitscan:alice?secret=" +
  SECRET +
  "&issuer=Bitscan&digits=6&period=30";
const CURRENT_PW = "Old-Password-Value-1";
const NEW_PW = "New-Password-Value-2";
const ENROL = "/api/v1/auth/totp/enrol";

let watch: Watch;

beforeEach(() => {
  resetHttp();
  clearSession();
  watch = watchSecrets();
});

afterEach(() => {
  const leaks = [SECRET, OLD, NEW, CURRENT_PW, NEW_PW].flatMap((s) =>
    watch.leaked(s),
  );
  watch.stop();
  clearSession();
  expect(leaks).toEqual([]);
});

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((r) => setTimeout(r, 0));
  }
}

async function submitVia(buttonName: string): Promise<void> {
  const b = screen.getByRole("button", { name: buttonName });
  const form = b.closest("form");
  if (form === null) {
    throw new Error("no form for " + buttonName);
  }
  const before = calls.length;
  await act(async () => {
    fireEvent.submit(form);
    await settle();
  });
  // Not every submit sends (local checks); callers assert on calls.
  void before;
}

function input(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

function bodyOf(call: Call | undefined): unknown {
  return JSON.parse(call?.body ?? "null");
}

/** Start answers the secret; confirm answers `confirmReply`. */
function enrolServer(confirmReply: () => Response): void {
  answer((call) => {
    if (call.path !== ENROL) {
      return json(200, { items: [], next_cursor: null });
    }
    const body = JSON.parse(call.body) as Record<string, unknown>;
    if ("totp_code" in body) {
      return confirmReply();
    }
    return json(200, { secret: SECRET, otpauth_uri: URI });
  });
}

function secretShown(): boolean {
  return document.body.textContent?.includes(SECRET) ?? false;
}

// ------------------------------------------------------------ CHK-M5-210

describe("CHK-M5-210 start shows the secret and URI as text", () => {
  it.each(["required", "offer", "manage"] as const)(
    "mode %s (no TOTP yet) posts {} and shows secret, URI and QR",
    async (mode) => {
      setSession(
        loginResponse(mode === "required" ? "admin" : "viewer", false, OLD),
      );
      enrolServer(() => problem(403, "forbidden"));
      const { container } = render(
        <TotpEnrol mode={mode} onDone={vi.fn()} onSkip={vi.fn()} />,
      );
      await submitVia("Start");
      expect(calls).toHaveLength(1);
      expect(calls[0]).toMatchObject({
        method: "POST",
        path: ENROL,
        authorization: null,
        csrf: "1",
      });
      expect(bodyOf(calls[0])).toEqual({});
      const codes = Array.from(container.querySelectorAll("code")).map(
        (c) => c.textContent,
      );
      expect(codes).toEqual([SECRET, URI]);
      const qr = screen.getByRole("img", {
        name: "QR code of the TOTP secret",
      });
      expect(qr.tagName.toLowerCase()).toBe("svg");
      expect(
        qr.querySelector("path")?.getAttribute("d")?.length,
      ).toBeGreaterThan(100);
      // Drawn as SVG elements only: no image, HTML or data: URL inside.
      expect(
        container.querySelectorAll("img, image, foreignObject, script"),
      ).toHaveLength(0);
      expect(container.innerHTML).not.toContain("data:");
      expect(qr.hasAttribute("style")).toBe(false);
    },
  );

  it("a different URI draws a different QR code", async () => {
    setSession(loginResponse("viewer", false, OLD));
    enrolServer(() => problem(403, "forbidden"));
    const { container, unmount } = render(
      <TotpEnrol mode="manage" onDone={vi.fn()} />,
    );
    await submitVia("Start");
    const first = container.querySelector("svg path")?.getAttribute("d");
    unmount();
    answer(() =>
      json(200, {
        secret: "ABCDEFGH",
        otpauth_uri: URI.replace(SECRET, "ABCDEFGH"),
      }),
    );
    const second = render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    await submitVia("Start");
    expect(
      second.container.querySelector("svg path")?.getAttribute("d"),
    ).not.toBe(first);
  });

  it("hostile secret text renders literally", async () => {
    setSession(loginResponse("viewer", false, OLD));
    const hostile = "<img src=x onerror=alert(1)>";
    answer(() =>
      json(200, {
        secret: hostile,
        otpauth_uri: "otpauth://totp/x?secret=" + hostile,
      }),
    );
    const { container } = render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    await submitVia("Start");
    expect(screen.getByText(hostile)).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M5-211

describe("CHK-M5-211 confirm replaces the session", () => {
  it("posts {totp_code}; the new view is set; no token is ever sent; onDone", async () => {
    setSession(loginResponse("admin", false, OLD, false));
    enrolServer(() => json(200, loginResponse("admin", true, NEW, true)));
    const onDone = vi.fn();
    render(<TotpEnrol mode="required" onDone={onDone} />);
    await submitVia("Start");
    const confirm = screen.getByRole("button", {
      name: "Confirm",
    }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true); // no empty code is ever sent
    fireEvent.change(input("Code"), { target: { value: "654321" } });
    expect(confirm.disabled).toBe(false);
    await submitVia("Confirm");
    expect(calls).toHaveLength(2);
    expect(bodyOf(calls[1])).toEqual({ totp_code: "654321" });
    expect(calls[1]?.authorization).toBeNull();
    expect(calls[1]?.csrf).toBe("1");
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(currentSession()).toMatchObject({
      totpEnrolled: true,
      totpVerified: true,
    });
    expect(secretShown()).toBe(false);
    await api.GET("/api/v1/agents");
    expect(calls[2]?.authorization).toBeNull();
    expect(calls[2]?.url).not.toContain(NEW);
  });
});

// ------------------------------------------------------------ CHK-M5-212

describe("CHK-M5-212 a refused confirm", () => {
  it("403: wrong-code message, still the TOTP screen, back at start, secret and QR gone", async () => {
    setSession(loginResponse("admin", false, OLD, false));
    enrolServer(() => problem(403, "forbidden", "wrong code"));
    const onDone = vi.fn();
    const { container } = render(<TotpEnrol mode="required" onDone={onDone} />);
    await submitVia("Start");
    expect(secretShown()).toBe(true);
    fireEvent.change(input("Code"), { target: { value: "000000" } });
    await submitVia("Confirm");
    expect(screen.getByRole("alert").textContent).toBe(
      "The code was not accepted. Start again to get a new secret.",
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Set up TOTP",
    );
    expect(screen.getByRole("button", { name: "Start" })).toBeTruthy();
    expect(secretShown()).toBe(false);
    expect(container.innerHTML).not.toContain(SECRET);
    expect(container.querySelector("svg")).toBeNull();
    expect(onDone).not.toHaveBeenCalled();
    expect(currentSession()?.totpEnrolled).toBe(false);
    await api.GET("/api/v1/agents");
    expect(calls.at(-1)?.authorization).toBeNull();
  });

  it("409: enrolment restarts (start step; Start posts {} again)", async () => {
    setSession(loginResponse("viewer", false, OLD));
    enrolServer(() => problem(409, "conflict", "expired"));
    const { container } = render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    await submitVia("Start");
    fireEvent.change(input("Code"), { target: { value: "111111" } });
    await submitVia("Confirm");
    expect(screen.getByRole("alert").textContent).toBe(
      "The enrolment expired. Start again.",
    );
    expect(container.innerHTML).not.toContain(SECRET);
    await submitVia("Start");
    expect(calls).toHaveLength(3);
    expect(bodyOf(calls[2])).toEqual({});
    expect(secretShown()).toBe(true);
  });

  it("other refusals go to the banner (429 with the wait)", async () => {
    setSession(loginResponse("viewer", false, OLD));
    answer(() => problem(429, "rate_limited", null, { "Retry-After": "9" }));
    render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    await submitVia("Start");
    expect(screen.getByRole("alert").textContent).toContain(
      "Too many requests. Wait 9 seconds.",
    );
  });
});

// ------------------------------------------------------------ CHK-M5-213

describe("CHK-M5-213 replacement", () => {
  it("sends exactly {current_password, current_code} first, fields emptied", async () => {
    setSession(loginResponse("operator", true, OLD));
    enrolServer(() => json(200, loginResponse("operator", true, NEW)));
    render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Replace TOTP",
    );
    expect(input("Current password").type).toBe("password");
    fireEvent.change(input("Current password"), {
      target: { value: CURRENT_PW },
    });
    fireEvent.change(input("Current code"), { target: { value: "222333" } });
    await submitVia("Start");
    expect(calls).toHaveLength(1);
    expect(bodyOf(calls[0])).toEqual({
      current_password: CURRENT_PW,
      current_code: "222333",
    });
    expect(Object.keys(bodyOf(calls[0]) as object)).toEqual([
      "current_password",
      "current_code",
    ]);
    expect(secretShown()).toBe(true);
    expect(document.body.innerHTML).not.toContain(CURRENT_PW);
  });

  it("403 forbidden on the replacement start: not valid, fields cleared", async () => {
    setSession(loginResponse("operator", true, OLD));
    answer(() => problem(403, "forbidden", "bad"));
    render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    fireEvent.change(input("Current password"), {
      target: { value: CURRENT_PW },
    });
    fireEvent.change(input("Current code"), { target: { value: "222333" } });
    await submitVia("Start");
    expect(screen.getByRole("alert").textContent).toBe(
      "The current password or code is not valid.",
    );
    expect(input("Current password").value).toBe("");
    expect(input("Current code").value).toBe("");
  });

  it("a first enrolment in manage mode has no password fields", () => {
    setSession(loginResponse("operator", false, OLD));
    render(<TotpEnrol mode="manage" onDone={vi.fn()} />);
    expect(screen.queryByLabelText("Current password")).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-214

describe("CHK-M5-214 leaving the screen drops the secret", () => {
  it("after unmount the secret is in no DOM, storage or console", async () => {
    setSession(loginResponse("admin", false, OLD, false));
    enrolServer(() => problem(403, "forbidden"));
    const { unmount } = render(<TotpEnrol mode="required" onDone={vi.fn()} />);
    await submitVia("Start");
    expect(secretShown()).toBe(true);
    unmount();
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(document.documentElement.outerHTML).not.toContain(SECRET);
    // The afterEach checks storage, cookie, IndexedDB, console and URL.
  });

  it("after a successful confirm the secret is gone too", async () => {
    setSession(loginResponse("viewer", false, OLD));
    enrolServer(() => json(200, loginResponse("viewer", true, NEW)));
    render(<TotpEnrol mode="offer" onDone={vi.fn()} onSkip={vi.fn()} />);
    await submitVia("Start");
    fireEvent.change(input("Code"), { target: { value: "123123" } });
    await submitVia("Confirm");
    expect(document.body.innerHTML).not.toContain(SECRET);
  });
});

// ------------------------------------------------------------ CHK-M5-215

describe("CHK-M5-215 the offer", () => {
  it('"Not now" calls onSkip and sends nothing', () => {
    setSession(loginResponse("viewer", false, OLD));
    const onSkip = vi.fn();
    render(<TotpEnrol mode="offer" onDone={vi.fn()} onSkip={onSkip} />);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(0);
  });

  it("required has no skip", () => {
    setSession(loginResponse("admin", false, OLD));
    render(<TotpEnrol mode="required" onDone={vi.fn()} onSkip={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Not now" })).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-216

function fillPasswords(current: string, next: string, repeat: string): void {
  fireEvent.change(input("Current password"), { target: { value: current } });
  fireEvent.change(input("New password"), { target: { value: next } });
  fireEvent.change(input("Repeat new password"), { target: { value: repeat } });
}

describe("CHK-M5-216 password change", () => {
  it.each([
    ["mismatch", NEW_PW, NEW_PW + "x", "The new passwords do not match."],
    [
      "11 characters",
      "abcdefghijk",
      "abcdefghijk",
      "The new password must be at least 12 characters.",
    ],
    [
      "11 code points in 22 UTF-16 units",
      "\u{1F600}".repeat(11),
      "\u{1F600}".repeat(11),
      "The new password must be at least 12 characters.",
    ],
  ])("%s sends nothing", async (_n, next, repeat, message) => {
    setSession(loginResponse("viewer", true, OLD));
    answer(() => noContent());
    render(<PasswordChange onChanged={vi.fn()} />);
    fillPasswords(CURRENT_PW, next, repeat);
    await submitVia("Change password");
    expect(calls).toHaveLength(0);
    expect(screen.getByRole("alert").textContent).toBe(message);
    expect(input("New password").value).toBe(next);
  });

  it("all three fields are type=password", () => {
    render(<PasswordChange onChanged={vi.fn()} />);
    for (const l of [
      "Current password",
      "New password",
      "Repeat new password",
    ]) {
      expect(input(l).type).toBe("password");
    }
  });

  it.each([
    ["12 characters", "abcdefghijkl"],
    ["12 code points (emoji)", "\u{1F600}".repeat(12)],
  ])(
    "a valid form (%s) sends the documented body once; 204 clears the session",
    async (_n, next) => {
      setSession(loginResponse("viewer", true, OLD));
      answer(() => noContent());
      const onChanged = vi.fn();
      render(<PasswordChange onChanged={onChanged} />);
      fillPasswords(CURRENT_PW, next, next);
      await submitVia("Change password");
      expect(calls).toHaveLength(1);
      expect(calls[0]).toMatchObject({
        method: "POST",
        path: "/api/v1/auth/password",
        authorization: null,
        csrf: "1",
      });
      expect(bodyOf(calls[0])).toEqual({
        current_password: CURRENT_PW,
        new_password: next,
      });
      expect(currentSession()).toBeNull();
      expect(onChanged).toHaveBeenCalledTimes(1);
      await api.GET("/api/v1/agents");
      expect(calls[1]?.authorization).toBeNull();
    },
  );

  it("403: wrong-password message, form kept, password fields cleared", async () => {
    setSession(loginResponse("viewer", true, OLD));
    answer(() => problem(403, "forbidden", "no"));
    const onChanged = vi.fn();
    render(<PasswordChange onChanged={onChanged} />);
    fillPasswords("wrong-current-pw", NEW_PW, NEW_PW);
    await submitVia("Change password");
    expect(calls).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toBe(
      "The current password is not correct.",
    );
    expect(
      screen.getByRole("button", { name: "Change password" }),
    ).toBeTruthy();
    for (const l of [
      "Current password",
      "New password",
      "Repeat new password",
    ]) {
      expect(input(l).value).toBe("");
    }
    expect(onChanged).not.toHaveBeenCalled();
    expect(currentSession()).not.toBeNull();
  });

  it("400 (the server's rules) shows its detail as text", async () => {
    setSession(loginResponse("viewer", true, OLD));
    const hostile = "<b>too common</b>";
    answer(() => problem(400, "invalid_request", hostile));
    const { container } = render(<PasswordChange onChanged={vi.fn()} />);
    fillPasswords(CURRENT_PW, NEW_PW, NEW_PW);
    await submitVia("Change password");
    expect(screen.getByText(hostile)).toBeTruthy();
    expect(container.querySelectorAll("b")).toHaveLength(0);
    expect(currentSession()).not.toBeNull();
  });
});
