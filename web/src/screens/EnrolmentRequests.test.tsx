// TASK-121 TEST (TP-M5-14): CHK-M5-230 to CHK-M5-234.
// Expected values: REQ-125 (1)-(4), REQ-126, REQ-132; TS §3.2 L185 (an admin
// approves or rejects), L192 (requests matching an existing hostname or
// machine-id are flagged; a cloned image shares the machine-id), §6.2
// L1114-L1115 (GET ?state=pending|decided, POST .../approve|reject, TOTP
// session), §6.3 L1141 (plain text).
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
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession } from "../app/session";
import { EnrolmentRequests } from "./EnrolmentRequests";

const LIST = "/api/v1/enrollment-requests";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const MID = "a".repeat(32);

interface Req {
  request_id: number;
  agent_id: string;
  hostname: string;
  machine_id: string;
  source_ip: string;
  os_pretty_name: string | null;
  agent_version: string;
  kind: "new" | "reenrol";
  requested_at: string;
  token_expires_at: string;
  decision: "approved" | "rejected" | null;
  decided_by: number | null;
  decided_at: string | null;
  matches: {
    agent_id: string;
    hostname: string;
    machine_id: string;
    status: string;
  }[];
}

function req(id: number, extra: Partial<Req> = {}): Req {
  return {
    request_id: id,
    agent_id: "00000000-0000-4000-8000-" + String(id).padStart(12, "0"),
    hostname: "host-" + String(id),
    machine_id: String(id).padStart(32, "0"),
    source_ip: "10.0.0." + String(id),
    os_pretty_name: "Ubuntu 24.04.1 LTS",
    agent_version: "0.5.0",
    kind: "new",
    requested_at: "2026-10-25T09:08:07Z",
    token_expires_at: "2026-11-25T09:08:07Z",
    decision: null,
    decided_by: null,
    decided_at: null,
    matches: [],
    ...extra,
  };
}

/** Pending and decided requests behind the list and decision routes. */
function requestServer(items: Req[], refuse?: (call: Call) => Response | null) {
  const all = [...items];
  answer((call) => {
    const r = refuse?.(call);
    if (r) {
      return r;
    }
    if (call.path === LIST && call.method === "GET") {
      const q = queryOf(call);
      const want = all.filter((x) =>
        q.state === "decided" ? x.decision !== null : x.decision === null,
      );
      const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(1));
      const end = Math.min(start + Number(q.limit), want.length);
      return json(200, {
        items: want.slice(start, end),
        next_cursor: end < want.length ? "c" + String(end) : null,
      });
    }
    const m = /^\/api\/v1\/enrollment-requests\/(\d+)\/(approve|reject)$/.exec(
      call.path,
    );
    if (m && call.method === "POST") {
      const item = all.find((x) => x.request_id === Number(m[1]));
      if (!item) {
        return problem(404, "not_found");
      }
      if (item.decision !== null) {
        return problem(409, "conflict", "already decided");
      }
      item.decision = m[2] === "approve" ? "approved" : "rejected";
      item.decided_by = 1;
      item.decided_at = "2026-10-25T10:00:00Z";
      return m[2] === "approve"
        ? json(200, { agent_id: item.agent_id })
        : noContent();
    }
    return json(599, { type: "unexpected" });
  });
  return all;
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("admin", true, bsu("A")));
});

afterEach(() => {
  clearSession();
});

async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 4; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

async function mount(): Promise<ReturnType<typeof render>> {
  const view = render(<EnrolmentRequests />);
  await settle();
  return view;
}

function article(hostname: string): HTMLElement {
  return screen.getByRole("article", { name: hostname });
}

function decisionPosts(): string[] {
  return calls.filter((c) => c.method === "POST").map((c) => c.path);
}

// ------------------------------------------------------------ CHK-M5-230

describe("CHK-M5-230 pending by default, decided on request", () => {
  it("shows the six fields of each pending request", async () => {
    requestServer([
      req(1),
      req(2, { kind: "reenrol", os_pretty_name: null }),
      req(3, {
        decision: "approved",
        decided_by: 4,
        decided_at: "2026-10-24T01:02:03Z",
      }),
    ]);
    await mount();
    expect(callsTo(LIST)).toHaveLength(1);
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({
      state: "pending",
      limit: "50",
    });
    expect(screen.queryByRole("article", { name: "host-3" })).toBeNull();
    const one = article("host-1").textContent ?? "";
    for (const part of [
      "host-1",
      "Kind",
      "New host",
      "Source IP",
      "10.0.0.1",
      "OS",
      "Ubuntu 24.04.1 LTS",
      "Agent version",
      "0.5.0",
      "Requested",
      "2026-10-25 09:08:07 UTC",
    ]) {
      expect(one).toContain(part);
    }
    const two = article("host-2").textContent ?? "";
    expect(two).toContain("Re-enrolment of an existing agent");
    expect(two).toContain("unknown");
    expect(
      within(article("host-1")).getByRole("button", { name: "Approve" }),
    ).toBeTruthy();
  });

  it("switching to Decided asks state=decided and shows the decision, no buttons", async () => {
    requestServer([
      req(1),
      req(3, {
        decision: "rejected",
        decided_by: 4,
        decided_at: "2026-10-24T01:02:03Z",
      }),
    ]);
    await mount();
    fireEvent.change(screen.getByLabelText("Show"), {
      target: { value: "decided" },
    });
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      state: "decided",
      limit: "50",
    });
    const three = article("host-3");
    expect(three.textContent).toContain(
      "rejected by user 4 at 2026-10-24 01:02:03 UTC",
    );
    expect(within(three).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(within(three).queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("article", { name: "host-1" })).toBeNull();
  });

  it("an empty page says so", async () => {
    requestServer([]);
    await mount();
    expect(screen.getByText("No requests.")).toBeTruthy();
  });

  it("pages with the returned cursor; each request once", async () => {
    requestServer(Array.from({ length: 51 }, (_, i) => req(i + 1)));
    await mount();
    expect(screen.getAllByRole("article")).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      state: "pending",
      limit: "50",
      cursor: "c50",
    });
    expect(
      screen.getAllByRole("article").map((a) => a.getAttribute("aria-label")),
    ).toEqual(["host-51"]);
  });
});

// ------------------------------------------------------------ CHK-M5-231

describe("CHK-M5-231 matching agents are flagged", () => {
  it("a request with two matches shows both with hostname, machine-id and status", async () => {
    requestServer([
      req(5, {
        hostname: "web-01",
        machine_id: MID,
        matches: [
          {
            agent_id: "11111111-1111-4111-8111-111111111111",
            hostname: "web-01-old",
            machine_id: MID,
            status: "online",
          },
          {
            agent_id: "22222222-2222-4222-8222-222222222222",
            hostname: "web-01",
            machine_id: "b".repeat(32),
            status: "decommissioned",
          },
        ],
      }),
      req(6),
    ]);
    await mount();
    const flagged = within(article("web-01")).getByRole("region", {
      name: "Matching agents",
    });
    expect(flagged.textContent).toContain(
      "Warning: 2 existing agent(s) share this hostname or machine-id. A cloned image shares the machine-id.",
    );
    const items = within(flagged)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items).toEqual([
      "web-01-old (same machine-id), machine-id " + MID + ", status Online",
      "web-01 (same hostname), machine-id " +
        "b".repeat(32) +
        ", status Decommissioned",
    ]);
    expect(
      within(article("host-6")).queryByRole("region", {
        name: "Matching agents",
      }),
    ).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-232

describe("CHK-M5-232 hostile text is literal", () => {
  it("hostname, match hostname and os_pretty_name", async () => {
    requestServer([
      req(7, {
        hostname: SCRIPT,
        os_pretty_name: IMG,
        matches: [
          {
            agent_id: "33333333-3333-4333-8333-333333333333",
            hostname: IMG + SCRIPT,
            machine_id: "c".repeat(32),
            status: "online",
          },
        ],
      }),
    ]);
    const { container } = await mount();
    const a = article(SCRIPT);
    expect(within(a).getByRole("heading", { level: 2 }).textContent).toBe(
      SCRIPT,
    );
    expect(within(a).getByText(IMG)).toBeTruthy();
    expect(a.textContent).toContain(IMG + SCRIPT + " (match)");
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M5-233

describe("CHK-M5-233 approve and reject", () => {
  it.each(["Approve", "Reject"] as const)(
    "%s: one POST after confirmation, none on cancel; the item leaves pending",
    async (button) => {
      requestServer([req(8), req(9)]);
      await mount();
      const a = article("host-8");
      fireEvent.click(within(a).getByRole("button", { name: button }));
      fireEvent.click(within(a).getByRole("button", { name: "Cancel" }));
      await settle();
      expect(decisionPosts()).toEqual([]);
      fireEvent.click(
        within(article("host-8")).getByRole("button", { name: button }),
      );
      fireEvent.click(
        within(article("host-8")).getByRole("button", { name: "Confirm" }),
      );
      await settle();
      expect(decisionPosts()).toEqual([LIST + "/8/" + button.toLowerCase()]);
      expect(calls.find((c) => c.method === "POST")?.authorization).toBeNull();
      expect(calls.find((c) => c.method === "POST")?.csrf).toBe("1");
      expect(callsTo(LIST)).toHaveLength(2);
      expect(queryOf(callsTo(LIST)[1] as Call)).toEqual({
        state: "pending",
        limit: "50",
      });
      expect(screen.queryByRole("article", { name: "host-8" })).toBeNull();
      expect(article("host-9")).toBeTruthy();
    },
  );
});

// ------------------------------------------------------------ CHK-M5-234

describe("CHK-M5-234 refusals", () => {
  it("409 shows already decided and refreshes", async () => {
    const all = requestServer([req(10)]);
    await mount();
    (all[0] as Req).decision = "approved"; // decided elsewhere meanwhile
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "This request was already decided.",
    );
    expect(callsTo(LIST)).toHaveLength(2);
    expect(screen.queryByRole("article", { name: "host-10" })).toBeNull();
  });

  it("totp_session_required: sign in again, no token field", async () => {
    requestServer([req(11)], (c) =>
      c.method === "POST" ? problem(403, "totp_session_required") : null,
    );
    const { container } = await mount();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(
      "This action needs a sign-in with your TOTP code. Sign in again with your password and code.",
    );
    expect(
      within(alert).getByRole("button", { name: "Sign in again" }),
    ).toBeTruthy();
    expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
    expect(document.body.textContent?.toLowerCase()).not.toMatch(
      /api token|bsk_/,
    );
  });

  it("audit_sink_unavailable shows the paused message", async () => {
    requestServer([req(12)], (c) =>
      c.method === "POST" ? problem(503, "audit_sink_unavailable") : null,
    );
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
    );
  });

  it("forbidden shows the role message", async () => {
    requestServer([req(13)], (c) =>
      c.method === "POST" ? problem(403, "forbidden") : null,
    );
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
  });
});
