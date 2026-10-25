// TASK-123 TEST (TP-M5-16): CHK-M5-250 to CHK-M5-255.
// Expected values: REQ-128 (1)-(5), REQ-132; TS §6.2 L1109-L1110 (GET
// /agents/{id} with os_info and last_snapshot; GET /agents/{id}/packages,
// paged), §7.3 L1225 (host detail: identity, OS, added/removed since the last
// snapshot, packages), §6.3 L1141 (plain text); the agent's token is never
// part of the item (TS §6.2).
import {
  answer,
  bsu,
  calls,
  callsTo,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import { clearSession, setSession } from "../app/session";
import { HostDetail } from "./HostDetail";

type Detail = components["schemas"]["AgentDetailItem"];
type Pkg = components["schemas"]["AgentPackageItem"];

const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";

function detail(extra: Partial<Detail> = {}): Detail {
  return {
    agent_id: ID,
    hostname: "web-01",
    machine_id: "f".repeat(32),
    status: "stale",
    agent_version: "0.5.0",
    enrolled_at: "2026-10-01T01:02:03Z",
    last_seen_ip: "10.1.2.3",
    last_heartbeat_at: "2026-10-25T10:00:00Z",
    last_inventory_at: "2026-10-25T09:00:00Z",
    token_issued_at: "2026-10-02T00:00:00Z",
    token_expires_at: "2026-12-31T00:00:00Z",
    token_revoked_at: null,
    tags: ["prod-web", "db"],
    runner_helpers: ["capread"],
    os_id: "ubuntu",
    os_version_id: "24.04",
    os_pretty_name: "Ubuntu 24.04.1 LTS",
    os_info: {
      os_id: "ubuntu",
      os_version_id: "24.04",
      os_pretty_name: "Ubuntu 24.04.1 LTS",
      kernel_release: "6.8.0-45-generic",
      architecture: "amd64",
      cpu_count: 8,
      memory_mb: 16000,
      uptime_s: 12345,
      ip_addresses: ["10.1.2.3/24", "fe80::1/64"],
      raw: { lsb: { codename: "noble" }, list: [1, true, "x"] },
      collected_at: "2026-10-25T09:00:00Z",
    },
    last_snapshot: {
      snapshot_id: 9,
      collected_at: "2026-10-25T09:00:00Z",
      package_count: 1234,
      added: [
        {
          name: "curl",
          version: "8.5.0-2ubuntu10",
          architecture: "amd64",
          status: "install ok installed",
        },
        {
          name: "jq",
          version: "1.7.1-3",
          architecture: "amd64",
          status: "install ok installed",
        },
      ],
      removed: [
        {
          name: "telnet",
          version: "0.17-44",
          architecture: "amd64",
          status: "deinstall ok config-files",
        },
      ],
    },
    ...extra,
  };
}

function pkg(i: number, extra: Partial<Pkg> = {}): Pkg {
  return {
    name: "pkg-" + String(i).padStart(3, "0"),
    version: "1." + String(i),
    architecture: "amd64",
    status: "install ok installed",
    source_name: "src-" + String(i),
    installed_size_kb: 100 + i,
    first_seen_at: "2026-10-01T00:00:00Z",
    last_seen_at: "2026-10-25T00:00:00Z",
    ...extra,
  };
}

function hostServer(d: Detail | Response, packages: Pkg[]) {
  answer((call) => {
    if (call.path === "/api/v1/agents/" + ID) {
      return d instanceof Response ? d : json(200, d);
    }
    if (call.path === "/api/v1/agents/" + ID + "/packages") {
      const q = queryOf(call);
      const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(2));
      const end = Math.min(start + Number(q.limit), packages.length);
      return json(200, {
        items: packages.slice(start, end),
        next_cursor: end < packages.length ? "p-" + String(end) : null,
      });
    }
    return json(599, { type: "unexpected" });
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
  const view = render(<HostDetail agentId={ID} navigate={navigate} />);
  await settle();
  return view;
}

/** The <dd> after the <dt> with this label. */
function field(label: string): string | null {
  for (const dt of Array.from(document.querySelectorAll("dt"))) {
    if (dt.textContent === label) {
      return dt.nextElementSibling?.textContent ?? null;
    }
  }
  return null;
}

// ------------------------------------------------------------ CHK-M5-250

describe("CHK-M5-250 every REQ-128 field", () => {
  it("identity, status, enrolment, IP, token times, tags, helpers, OS, raw", async () => {
    hostServer(detail(), [pkg(1)]);
    const { container } = await mount();
    expect(callsTo("/api/v1/agents/" + ID)).toHaveLength(1);
    expect(
      queryOf(callsTo("/api/v1/agents/" + ID + "/packages")[0] as Call),
    ).toEqual({
      limit: "50",
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "web-01",
    );
    expect(container.textContent).toContain("Stale");
    const want: [string, string][] = [
      ["Hostname", "web-01"],
      ["Machine-id", "f".repeat(32)],
      ["Agent id", ID],
      ["Agent version", "0.5.0"],
      ["Enrolled", "2026-10-01 01:02:03 UTC"],
      ["Last seen IP", "10.1.2.3"],
      ["Last heartbeat", "2026-10-25 10:00:00 UTC"],
      ["Last inventory", "2026-10-25 09:00:00 UTC"],
      ["Token issued", "2026-10-02 00:00:00 UTC"],
      ["Token expires", "2026-12-31 00:00:00 UTC"],
      ["Token revoked", "never"],
      ["Tags", "prod-web, db"],
      ["Runner helpers", "capread"],
      ["OS", "Ubuntu 24.04.1 LTS"],
      ["OS id", "ubuntu"],
      ["OS version id", "24.04"],
      ["Kernel release", "6.8.0-45-generic"],
      ["Architecture", "amd64"],
      ["CPU count", "8"],
      ["Memory (MB)", "16000"],
      ["Uptime (s)", "12345"],
      ["Collected", "2026-10-25 09:00:00 UTC"],
    ];
    for (const [label, value] of want) {
      expect([label, field(label)]).toEqual([label, value]);
    }
    const ipHeading = screen.getByRole("heading", { name: "IP addresses" });
    const ips = ipHeading.nextElementSibling as HTMLElement;
    expect(
      within(ips)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["10.1.2.3/24", "fe80::1/64"]);
    const pre = container.querySelector("pre");
    expect(pre?.textContent).toBe(
      JSON.stringify(
        { lsb: { codename: "noble" }, list: [1, true, "x"] },
        null,
        2,
      ),
    );
    expect(pre?.textContent).toContain('\n  "lsb": {\n    "codename": "noble"');
    // No token value anywhere (the item has none; nothing else adds one).
    expect(container.textContent).not.toMatch(/bs[auke]_/);
  });

  it("revoked token time, empty tags and helpers, unknown OS values", async () => {
    hostServer(
      detail({
        token_revoked_at: "2026-10-20T05:06:07Z",
        tags: [],
        runner_helpers: [],
        last_seen_ip: null,
        os_info: {
          ...(detail().os_info as NonNullable<Detail["os_info"]>),
          kernel_release: null,
          cpu_count: null,
          memory_mb: null,
          ip_addresses: [],
        },
      }),
      [],
    );
    await mount();
    expect(field("Token revoked")).toBe("2026-10-20 05:06:07 UTC");
    expect(field("Tags")).toBe("none");
    expect(field("Runner helpers")).toBe("none");
    expect(field("Last seen IP")).toBe("unknown");
    expect(field("Kernel release")).toBe("unknown");
    expect(field("CPU count")).toBe("unknown");
  });
});

// ------------------------------------------------------------ CHK-M5-251

describe("CHK-M5-251 no inventory, no snapshot", () => {
  it("null os_info shows No inventory yet; null last_snapshot shows no change list", async () => {
    hostServer(detail({ os_info: null, last_snapshot: null }), []);
    await mount();
    expect(screen.getByText("No inventory yet.")).toBeTruthy();
    expect(field("Kernel release")).toBeNull();
    expect(
      screen.queryByRole("region", {
        name: "Added / removed since last snapshot",
      }),
    ).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-252

describe("CHK-M5-252 added and removed lists", () => {
  it("equal the snapshot items, in order", async () => {
    hostServer(detail(), []);
    await mount();
    const region = screen.getByRole("region", {
      name: "Added / removed since last snapshot",
    });
    expect(region.textContent).toContain(
      "Snapshot 2026-10-25 09:00:00 UTC, 1234 packages.",
    );
    const items = (name: string): string[] =>
      within(within(region).getByRole("region", { name }))
        .queryAllByRole("listitem")
        .map((li) => li.textContent ?? "");
    expect(items("Added")).toEqual([
      "curl 8.5.0-2ubuntu10 amd64 (install ok installed)",
      "jq 1.7.1-3 amd64 (install ok installed)",
    ]);
    expect(items("Removed")).toEqual([
      "telnet 0.17-44 amd64 (deinstall ok config-files)",
    ]);
    expect(
      within(region).getByRole("heading", { name: "Added (2)" }),
    ).toBeTruthy();
    expect(
      within(region).getByRole("heading", { name: "Removed (1)" }),
    ).toBeTruthy();
  });

  it("an empty snapshot change shows two empty lists", async () => {
    const d = detail();
    hostServer(
      detail({
        last_snapshot: {
          ...(d.last_snapshot as NonNullable<Detail["last_snapshot"]>),
          added: [],
          removed: [],
        },
      }),
      [],
    );
    await mount();
    expect(screen.getByRole("heading", { name: "Added (0)" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Removed (0)" })).toBeTruthy();
  });
});

// ------------------------------------------------------------ CHK-M5-253

describe("CHK-M5-253 hostile text", () => {
  it("raw key and value, hostname, tags, snapshot and package names are text", async () => {
    const os = detail().os_info as NonNullable<Detail["os_info"]>;
    hostServer(
      detail({
        hostname: SCRIPT,
        tags: [IMG],
        os_info: { ...os, raw: { [SCRIPT]: IMG, nested: { [IMG]: [SCRIPT] } } },
        last_snapshot: {
          snapshot_id: 1,
          collected_at: "2026-10-25T09:00:00Z",
          package_count: 1,
          added: [
            { name: SCRIPT, version: "1", architecture: "all", status: IMG },
          ],
          removed: [],
        },
      }),
      [pkg(1, { name: IMG, source_name: SCRIPT })],
    );
    const { container } = await mount();
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    const pre = container.querySelector("pre")?.textContent ?? "";
    expect(JSON.parse(pre)).toEqual({
      [SCRIPT]: IMG,
      nested: { [IMG]: [SCRIPT] },
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(SCRIPT);
    expect(screen.getByText(SCRIPT + " 1 all (" + IMG + ")")).toBeTruthy();
    expect(screen.getByRole("cell", { name: IMG })).toBeTruthy();
  });
});

// ------------------------------------------------------------ CHK-M5-254

describe("CHK-M5-254 not found and failures", () => {
  it("404 shows Host not found, with a way back", async () => {
    hostServer(problem(404, "not_found", "no such agent"), []);
    const navigate = vi.fn();
    await mount(navigate);
    expect(screen.getByRole("alert").textContent).toBe("Host not found.");
    expect(document.body.textContent).not.toContain("no such agent");
    fireEvent.click(screen.getByRole("link", { name: "Back to hosts" }));
    expect(navigate).toHaveBeenCalledWith({ name: "hosts" });
  });

  it("another refusal goes to the banner; a network failure says unavailable", async () => {
    hostServer(problem(403, "forbidden"), []);
    const { unmount } = await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
    unmount();
    answer(() => Promise.reject(new TypeError("down")));
    await mount();
    expect(screen.getAllByRole("alert")[0]?.textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });
});

// ------------------------------------------------------------ CHK-M5-255

describe("CHK-M5-255 the package list", () => {
  it("51 packages: each once, with all eight columns", async () => {
    hostServer(detail(), [
      pkg(0, { source_name: null, installed_size_kb: null }),
      ...Array.from({ length: 50 }, (_, i) => pkg(i + 1)),
    ]);
    await mount();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Name",
      "Version",
      "Architecture",
      "Status",
      "Source",
      "Size (KB)",
      "First seen",
      "Last seen",
    ]);
    const rows = (): string[][] =>
      within(screen.getByRole("table"))
        .getAllByRole("row")
        .slice(1)
        .map((r) =>
          Array.from(r.querySelectorAll("td")).map((c) => c.textContent ?? ""),
        );
    const first = rows();
    expect(first).toHaveLength(50);
    expect(first[0]).toEqual([
      "pkg-000",
      "1.0",
      "amd64",
      "install ok installed",
      "unknown",
      "unknown",
      "2026-10-01 00:00:00 UTC",
      "2026-10-25 00:00:00 UTC",
    ]);
    expect(first[1]?.slice(4, 6)).toEqual(["src-1", "101"]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(
      queryOf(callsTo("/api/v1/agents/" + ID + "/packages").at(-1) as Call),
    ).toEqual({ limit: "50", cursor: "p-50" });
    const second = rows();
    expect(second.map((r) => r[0])).toEqual(["pkg-050"]);
    expect(new Set([...first, ...second].map((r) => r[0])).size).toBe(51);
    // The detail is not re-requested for a package page.
    expect(callsTo("/api/v1/agents/" + ID)).toHaveLength(1);
    expect(calls.every((c) => c.authorization === "Bearer " + bsu("V"))).toBe(
      true,
    );
  });
});
