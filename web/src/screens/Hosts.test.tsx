// TASK-122 TEST (TP-M5-15): CHK-M5-240 to CHK-M5-245.
// Expected values: REQ-127 (1)-(4), REQ-136, REQ-117; TS §6.2 L1108 (GET
// /agents, viewer), §5.2 L710 (the six agent_status values), §6.3 L1134
// (cursor pages), L1141 (plain text); work/decisions.md PD-29 (a).
import {
  answer,
  bsu,
  callsTo,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  expectTypeOf,
  it,
  vi,
} from "vitest";

import type { components } from "../api/schema";
import { clearSession, setSession } from "../app/session";
import { StatusBadge, type AgentStatus } from "../components/StatusBadge";
import { Hosts } from "./Hosts";

type AgentItem = components["schemas"]["AgentItem"];

const LIST = "/api/v1/agents";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const STATUSES = [
  "awaiting_approval",
  "enrolled",
  "online",
  "stale",
  "offline",
  "decommissioned",
] as const;

function agent(i: number, extra: Partial<AgentItem> = {}): AgentItem {
  return {
    agent_id: "0f8fad5b-d9cb-469f-a165-" + String(i).padStart(12, "0"),
    hostname: "host-" + String(i).padStart(3, "0"),
    status: "online",
    os_id: "ubuntu",
    os_version_id: "24.04",
    os_pretty_name: "Ubuntu 24.04.1 LTS",
    agent_version: "0.5." + String(i),
    last_heartbeat_at: "2026-10-25T10:11:12Z",
    last_inventory_at: "2026-10-25T09:00:00Z",
    tags: ["prod-web", "db"],
    runner_helpers: ["capread"],
    ...extra,
  };
}

function agentServer(items: AgentItem[], size?: number) {
  answer((call) => {
    if (call.path !== LIST) {
      return json(599, { type: "unexpected" });
    }
    const q = queryOf(call);
    const limit = size ?? Number(q.limit);
    const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(2));
    const end = Math.min(start + limit, items.length);
    return json(200, {
      items: items.slice(start, end),
      next_cursor: end < items.length ? "a-" + String(end) : null,
    });
  });
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("viewer", true, bsu("V")));
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

async function mount(navigate = vi.fn()): Promise<ReturnType<typeof render>> {
  const view = render(<Hosts navigate={navigate} />);
  await settle();
  return view;
}

function hostnames(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelector("td")?.textContent ?? "");
}

// ------------------------------------------------------------ CHK-M5-240

describe("CHK-M5-240 paging", () => {
  it("51 hosts at the screen's 50: next and previous show each host once", async () => {
    agentServer(Array.from({ length: 51 }, (_, i) => agent(i)));
    await mount();
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({ limit: "50" });
    const first = hostnames();
    expect(first).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      cursor: "a-50",
    });
    expect(hostnames()).toEqual(["host-050"]);
    expect(new Set([...first, ...hostnames()]).size).toBe(51);
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(hostnames()).toEqual(first);
    expect(callsTo(LIST).at(-1)?.query.has("cursor")).toBe(false);
  });

  it("N + 1 with a server page size of 2 (5 hosts) walks 3 pages", async () => {
    agentServer(
      Array.from({ length: 5 }, (_, i) => agent(i)),
      2,
    );
    await mount();
    const seen = [...hostnames()];
    for (let i = 0; i < 2; i++) {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await settle();
      seen.push(...hostnames());
    }
    expect(seen).toEqual([
      "host-000",
      "host-001",
      "host-002",
      "host-003",
      "host-004",
    ]);
  });

  it("an empty list says so", async () => {
    agentServer([]);
    await mount();
    expect(screen.getByText("No hosts yet.")).toBeTruthy();
  });
});

// ------------------------------------------------------------ CHK-M5-241

describe("CHK-M5-241 rows and status labels", () => {
  it("each of the six statuses has its own distinct label", async () => {
    agentServer(STATUSES.map((s, i) => agent(i, { status: s })));
    await mount();
    const labels = screen
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelectorAll("td")[1]?.textContent ?? "");
    expect(labels).toEqual([
      "Awaiting approval",
      "Enrolled",
      "Online",
      "Stale",
      "Offline",
      "Decommissioned",
    ]);
    expect(new Set(labels).size).toBe(6);
  });

  it("each row shows the eight REQ-127 columns", async () => {
    agentServer([
      agent(1),
      agent(2, { tags: [], runner_helpers: [], os_pretty_name: null }),
    ]);
    await mount();
    const head = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(head).toEqual([
      "Hostname",
      "Status",
      "OS",
      "Agent version",
      "Last heartbeat",
      "Last inventory",
      "Tags",
      "Runner helpers",
    ]);
    const cells = (n: number): string[] =>
      Array.from(
        screen.getAllByRole("row")[n]?.querySelectorAll("td") ?? [],
      ).map((c) => c.textContent ?? "");
    expect(cells(1)).toEqual([
      "host-001",
      "Online",
      "Ubuntu 24.04.1 LTS",
      "0.5.1",
      "2026-10-25 10:11:12 UTC",
      "2026-10-25 09:00:00 UTC",
      "prod-web, db",
      "capread",
    ]);
    expect(cells(2).slice(2)).toEqual([
      "unknown",
      "0.5.2",
      "2026-10-25 10:11:12 UTC",
      "2026-10-25 09:00:00 UTC",
      "none",
      "none",
    ]);
  });
});

// ------------------------------------------------------------ CHK-M5-243

describe("CHK-M5-243 hostile text and null times", () => {
  it("hostnames and tags render as text; null heartbeat shows never", async () => {
    agentServer([
      agent(1, {
        hostname: SCRIPT,
        tags: [IMG, SCRIPT],
        last_heartbeat_at: null,
        last_inventory_at: null,
        os_pretty_name: IMG,
        agent_version: SCRIPT,
      }),
    ]);
    const { container } = await mount();
    expect(screen.getByRole("link", { name: SCRIPT })).toBeTruthy();
    expect(screen.getByText(IMG + ", " + SCRIPT)).toBeTruthy();
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    const cells = Array.from(
      screen.getAllByRole("row")[1]?.querySelectorAll("td") ?? [],
    );
    expect(cells[4]?.textContent).toBe("never");
    expect(cells[5]?.textContent).toBe("never");
  });

  it("a refusal goes to the banner, a network failure says unavailable", async () => {
    answer(() => problem(403, "totp_enrolment_required"));
    const { unmount } = await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "Set up TOTP to continue.",
    );
    unmount();
    answer(() => Promise.reject(new TypeError("down")));
    await mount();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });
});

// ------------------------------------------------------------ CHK-M5-244

describe("CHK-M5-244 a row click opens the host", () => {
  it("navigates to {name: host, agentId}; the link is a # hash", async () => {
    const a = agent(7);
    agentServer([a, agent(8)]);
    const navigate = vi.fn();
    await mount(navigate);
    const link = screen.getByRole("link", { name: "host-007" });
    expect(link.getAttribute("href")).toBe("#/hosts/" + a.agent_id);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({
      name: "host",
      agentId: a.agent_id,
    });
  });

  it("a hostile agent_id cannot leave the # hash", async () => {
    agentServer([agent(1, { agent_id: "javascript:alert(1)" })]);
    await mount();
    const href =
      screen.getByRole("link", { name: "host-001" }).getAttribute("href") ?? "";
    expect(href.startsWith("#")).toBe(true);
  });
});

// ------------------------------------------------------------ CHK-M5-245

describe("CHK-M5-245 the status type is the six-value union", () => {
  it("AgentItem.status and StatusBadge take exactly the six statuses", () => {
    expectTypeOf<AgentItem["status"]>().toEqualTypeOf<
      (typeof STATUSES)[number]
    >();
    expectTypeOf<AgentStatus>().toEqualTypeOf<(typeof STATUSES)[number]>();
    expectTypeOf<
      components["schemas"]["AgentDetailItem"]["status"]
    >().toEqualTypeOf<(typeof STATUSES)[number]>();
    expectTypeOf<components["schemas"]["MatchItem"]["status"]>().toEqualTypeOf<
      (typeof STATUSES)[number]
    >();
    expectTypeOf<components["schemas"]["RequestItem"]["kind"]>().toEqualTypeOf<
      "new" | "reenrol"
    >();
    for (const s of STATUSES) {
      const { container, unmount } = render(<StatusBadge status={s} />);
      expect(container.textContent).not.toBe("");
      expect(container.textContent).not.toBe(s);
      unmount();
    }
  });
});
