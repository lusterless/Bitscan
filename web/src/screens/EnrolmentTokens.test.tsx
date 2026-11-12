// TASK-120 TEST (TP-M5-13): CHK-M5-220 to CHK-M5-225.
// Expected values: REQ-124 (1)-(5), REQ-126, REQ-132; TS §3.2 L181 (max_uses
// 1-10,000, a required expiry, optional allowed_cidrs, auto_approve default
// off; the multi-use hint), §8.4 (alert on auto_approve or > 100 uses), §6.2
// L1084/L1116 (sensitive action: TOTP session, never an API token), §6.3
// L1134 (cursor pages), L1141 (plain text).
import {
  answer,
  bsu,
  calls,
  callsTo,
  json,
  loginResponse,
  noContent,
  problem,
  queryOf,
  resetHttp,
  watchSecrets,
  type Call,
  type Watch,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession } from "../app/session";
import { EnrolmentTokens } from "./EnrolmentTokens";

const LIST = "/api/v1/enrollment-tokens";
const BSE = "bse_" + "K".repeat(43);
const HOSTILE = "<img src=x onerror=alert(1)>";

interface Token {
  token_id: number;
  max_uses: number;
  uses: number;
  expires_at: string;
  allowed_cidrs: string[] | null;
  auto_approve: boolean;
  created_by: number;
  created_at: string;
  revoked_at: string | null;
}

function token(id: number, extra: Partial<Token> = {}): Token {
  return {
    token_id: id,
    max_uses: 5,
    uses: 1,
    expires_at: "2026-10-26T10:00:00Z",
    allowed_cidrs: null,
    auto_approve: false,
    created_by: 3,
    created_at: "2026-10-25T10:00:00Z",
    revoked_at: null,
    ...extra,
  };
}

/** An in-memory token store behind the three routes; `refuse` overrides. */
function tokenServer(
  initial: Token[],
  refuse?: (call: Call) => Response | null,
) {
  const tokens = [...initial];
  answer((call) => {
    const r = refuse?.(call);
    if (r) {
      return r;
    }
    if (call.path === LIST && call.method === "GET") {
      const q = queryOf(call);
      const limit = Number(q.limit);
      const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(1));
      const end = Math.min(start + limit, tokens.length);
      return json(200, {
        items: tokens.slice(start, end),
        next_cursor: end < tokens.length ? "c" + String(end) : null,
      });
    }
    if (call.path === LIST && call.method === "POST") {
      const b = JSON.parse(call.body) as Token;
      const t = token(900 + tokens.length, {
        max_uses: b.max_uses,
        allowed_cidrs: b.allowed_cidrs,
        auto_approve: b.auto_approve,
        uses: 0,
      });
      tokens.unshift(t);
      return json(201, { ...t, token: BSE });
    }
    if (call.path.startsWith(LIST + "/") && call.method === "DELETE") {
      const id = Number(call.path.slice(LIST.length + 1));
      const t = tokens.find((x) => x.token_id === id);
      if (t) {
        t.revoked_at = "2026-10-25T11:12:13Z";
      }
      return noContent();
    }
    return json(599, { type: "unexpected" });
  });
  return tokens;
}

let watch: Watch;

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("admin", true, bsu("A")));
  watch = watchSecrets();
});

afterEach(() => {
  const leaks = watch.leaked(BSE);
  watch.stop();
  clearSession();
  expect(leaks).toEqual([]);
});

async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 4; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

async function mount(): Promise<ReturnType<typeof render>> {
  const view = render(<EnrolmentTokens />);
  await settle();
  return view;
}

function form(): HTMLFormElement {
  return screen.getByRole("form", {
    name: "Create enrolment token",
  }) as HTMLFormElement;
}

async function create(): Promise<void> {
  fireEvent.submit(form());
  await settle();
}

function setField(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function posted(): unknown[] {
  return callsTo(LIST, "POST").map((c) => JSON.parse(c.body) as unknown);
}

// ------------------------------------------------------------ CHK-M5-220

describe("CHK-M5-220 the create form", () => {
  it("untouched, posts exactly the REQ-124 (1) defaults", async () => {
    tokenServer([]);
    await mount();
    expect(callsTo(LIST)).toHaveLength(1);
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({ limit: "50" });
    await create();
    expect(posted()).toEqual([
      {
        max_uses: 1,
        expires_in_hours: 24,
        allowed_cidrs: null,
        auto_approve: false,
      },
    ]);
    expect(Object.keys(posted()[0] as object)).toEqual([
      "max_uses",
      "expires_in_hours",
      "allowed_cidrs",
      "auto_approve",
    ]);
    expect(callsTo(LIST, "POST")[0]?.authorization).toBeNull();
    expect(callsTo(LIST, "POST")[0]?.csrf).toBe("1");
  });

  it("filled, sends the values with the CIDRs as a list", async () => {
    tokenServer([]);
    await mount();
    setField("Max uses (1 to 10,000)", "10000");
    setField("Expires in hours (1 to 720)", "720");
    setField(
      "Allowed CIDRs (optional, one per line)",
      "10.0.0.0/8\n192.168.1.0/24, 2001:db8::/32\n\n",
    );
    fireEvent.click(screen.getByLabelText("Auto-approve new hosts"));
    await create();
    expect(posted()).toEqual([
      {
        max_uses: 10000,
        expires_in_hours: 720,
        allowed_cidrs: ["10.0.0.0/8", "192.168.1.0/24", "2001:db8::/32"],
        auto_approve: true,
      },
    ]);
  });

  it.each([
    ["0", "24"],
    ["10001", "24"],
    ["1.5", "24"],
    ["", "24"],
    ["1", "0"],
    ["1", "721"],
    ["1", "2.5"],
    ["1", ""],
  ])("max uses %j and hours %j send nothing", async (uses, hours) => {
    tokenServer([]);
    await mount();
    setField("Max uses (1 to 10,000)", uses);
    setField("Expires in hours (1 to 720)", hours);
    await create();
    expect(posted()).toEqual([]);
    expect(screen.getByRole("alert").textContent).toBe(
      "Max uses must be 1 to 10,000 and the expiry 1 to 720 hours.",
    );
  });

  it("the lower bounds 1 and 1 are accepted", async () => {
    tokenServer([]);
    await mount();
    setField("Expires in hours (1 to 720)", "1");
    await create();
    expect(posted()).toEqual([
      {
        max_uses: 1,
        expires_in_hours: 1,
        allowed_cidrs: null,
        auto_approve: false,
      },
    ]);
  });
});

// ------------------------------------------------------------ CHK-M5-221

describe("CHK-M5-221 hint and alert note", () => {
  it("are on the form", async () => {
    tokenServer([]);
    await mount();
    const text = form().textContent ?? "";
    expect(text).toContain(
      "A multi-use token should set max uses to the expected number of hosts and set allowed CIDRs.",
    );
    expect(text).toContain(
      "Creating a token with auto-approve or more than 100 uses raises an alert.",
    );
    expect(
      (screen.getByLabelText("Auto-approve new hosts") as HTMLInputElement)
        .checked,
    ).toBe(false);
  });
});

// ------------------------------------------------------------ CHK-M5-222

describe("CHK-M5-222 the created bse_ token", () => {
  it("is shown once with a copy button, and gone after Done", async () => {
    tokenServer([token(1)]);
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    await mount();
    await create();
    const result = screen.getByRole("region", { name: "New enrolment token" });
    expect(within(result).getByText(BSE).tagName.toLowerCase()).toBe("code");
    expect(result.textContent).toContain(
      "Copy this token now. It is shown only once.",
    );
    // Only inside the result section.
    const outside = document.body.textContent?.replace(
      result.textContent ?? "",
      "",
    );
    expect(outside).not.toContain(BSE);
    fireEvent.click(within(result).getByRole("button", { name: "Copy" }));
    await settle();
    expect(writeText).toHaveBeenCalledWith(BSE);
    expect(screen.getByRole("status").textContent).toBe("Copied.");
    // The list was re-read after the create and holds no token.
    expect(callsTo(LIST)).toHaveLength(2);
    fireEvent.click(within(result).getByRole("button", { name: "Done" }));
    expect(document.body.innerHTML).not.toContain(BSE);
    expect(
      screen.queryByRole("region", { name: "New enrolment token" }),
    ).toBeNull();
    expect(form()).toBeTruthy();
  });

  it("a missing Clipboard API shows nothing and keeps the token on screen", async () => {
    tokenServer([]);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    await mount();
    await create();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await settle();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText(BSE)).toBeTruthy();
  });

  it("leaving the screen drops it", async () => {
    tokenServer([]);
    const { unmount } = await mount();
    await create();
    expect(screen.getByText(BSE)).toBeTruthy();
    unmount();
    expect(document.body.innerHTML).not.toContain(BSE);
  });
});

// ------------------------------------------------------------ CHK-M5-223

describe("CHK-M5-223 revoke", () => {
  it("one DELETE after confirmation, none on cancel; the row then shows revoked_at", async () => {
    tokenServer([token(7), token(8, { revoked_at: "2026-10-20T00:00:00Z" })]);
    await mount();
    const row7 = screen
      .getByRole("cell", { name: "7" })
      .closest("tr") as HTMLElement;
    const row8 = screen
      .getByRole("cell", { name: "8" })
      .closest("tr") as HTMLElement;
    expect(within(row8).queryByRole("button", { name: "Revoke" })).toBeNull();
    expect(row8.textContent).toContain("2026-10-20 00:00:00 UTC");
    expect(row7.textContent).toContain("not revoked");
    fireEvent.click(within(row7).getByRole("button", { name: "Revoke" }));
    fireEvent.click(within(row7).getByRole("button", { name: "Cancel" }));
    await settle();
    expect(callsTo(LIST + "/7", "DELETE")).toHaveLength(0);
    fireEvent.click(within(row7).getByRole("button", { name: "Revoke" }));
    fireEvent.click(within(row7).getByRole("button", { name: "Confirm" }));
    await settle();
    expect(
      calls.filter((c) => c.method === "DELETE").map((c) => c.path),
    ).toEqual([LIST + "/7"]);
    expect(callsTo(LIST)).toHaveLength(2);
    const after = screen
      .getByRole("cell", { name: "7" })
      .closest("tr") as HTMLElement;
    expect(after.textContent).toContain("2026-10-25 11:12:13 UTC");
    expect(within(after).queryByRole("button", { name: "Revoke" })).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-224

describe("CHK-M5-224 refusals", () => {
  it("a 400 shows its detail as text", async () => {
    tokenServer([], (c) =>
      c.method === "POST"
        ? problem(400, "invalid_request", "bad CIDR " + HOSTILE)
        : null,
    );
    const { container } = await mount();
    await create();
    expect(screen.getByText("bad CIDR " + HOSTILE)).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
  });

  it("totp_session_required: sign in again, and no field asks for a token", async () => {
    tokenServer([], (c) =>
      c.method === "POST"
        ? problem(403, "totp_session_required", "TOTP needed")
        : null,
    );
    const { container } = await mount();
    const fieldsBefore = container.querySelectorAll("input, textarea").length;
    await create();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(
      "This action needs a sign-in with your TOTP code. Sign in again with your password and code.",
    );
    expect(
      within(alert).getByRole("button", { name: "Sign in again" }),
    ).toBeTruthy();
    expect(container.querySelectorAll("input, textarea")).toHaveLength(
      fieldsBefore,
    );
    expect(document.body.textContent?.toLowerCase()).not.toMatch(
      /api token|bsk_/,
    );
  });

  it("audit_sink_unavailable on revoke shows the paused message", async () => {
    tokenServer([token(7)], (c) =>
      c.method === "DELETE" ? problem(503, "audit_sink_unavailable") : null,
    );
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
    );
  });

  it("a refused list shows its own banner", async () => {
    tokenServer([], (c) =>
      c.method === "GET" ? problem(403, "forbidden") : null,
    );
    await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
  });

  it("a network failure says the manager is unavailable", async () => {
    tokenServer([], (c) => {
      if (c.method === "POST") {
        throw new TypeError("down");
      }
      return null;
    });
    await mount();
    await create();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });
});

// ------------------------------------------------------------ CHK-M5-225

describe("CHK-M5-225 list paging and plain text", () => {
  it("51 tokens: page 1 has 50, Next shows the 51st, each once", async () => {
    tokenServer(Array.from({ length: 51 }, (_, i) => token(i + 1)));
    await mount();
    const ids = (): string[] =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.querySelector("td")?.textContent ?? "");
    const first = ids();
    expect(first).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      cursor: "c50",
    });
    const second = ids();
    expect(second).toEqual(["51"]);
    expect(new Set([...first, ...second]).size).toBe(51);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(ids()).toEqual(first);
  });

  it("hostile CIDR text and a null list render as text", async () => {
    tokenServer([
      token(1, { allowed_cidrs: [HOSTILE, "<script>x</script>"] }),
      token(2, {
        allowed_cidrs: null,
        auto_approve: true,
        uses: 3,
        max_uses: 9,
      }),
    ]);
    const { container } = await mount();
    expect(screen.getByText(HOSTILE + ", <script>x</script>")).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
    const row2 = screen
      .getByRole("cell", { name: "2" })
      .closest("tr") as HTMLElement;
    expect(row2.textContent).toContain("any");
    expect(row2.textContent).toContain("yes");
    expect(row2.textContent).toContain("3 / 9");
  });
});
