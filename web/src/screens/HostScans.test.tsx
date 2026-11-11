// TASK-250 TEST (TP-M11-14): CHK-M11-270, CHK-M11-272 (host scans).
// Expected values: REQ-283 (1) (rows, links to the scan detail, the empty
// state and the error banner, with the mocked client); #145 (c) (scan items
// of GET /agents/{id}/scans, paged by cursor); REQ-266; TS §6.3 L1143.
import {
  answer,
  bsu,
  callsTo,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
} from "../test/harness";
import {
  IMG,
  SCRIPT,
  at,
  mockLinks,
  noInjectedMarkup,
  pageOf,
  scanItem,
  settle,
  uuid,
  type ScanItem,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import { clearSession, setSession } from "../app/session";
import { HostDetail } from "./HostDetail";
import { HostScans } from "./HostScans";

const AGENT = uuid(1);
const PATH = "/api/v1/agents/" + AGENT + "/scans";

function server(scans: readonly ScanItem[]): void {
  answer((call) => {
    if (call.path === PATH) {
      const q = queryOf(call);
      return json(200, pageOf(scans, q.cursor, Number(q.limit)));
    }
    return json(599, { type: "unexpected" });
  });
}

async function mount() {
  const view = render(<HostScans agentId={AGENT} links={mockLinks()} />);
  await settle();
  return view;
}

function section() {
  return within(screen.getByRole("region", { name: "Scans" }));
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("viewer", true, bsu("V")));
});
afterEach(() => {
  clearSession();
});

describe("CHK-M11-270 host scan history (REQ-283 (1))", () => {
  it("rows from GET /agents/{id}/scans, each linking to its scan detail", async () => {
    server([scanItem(1), scanItem(2, { state: "partial" })]);
    await mount();
    expect(at(callsTo(PATH), 0).authorization).toBe("Bearer " + bsu("V"));
    const rows = section().getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.querySelector("a")?.getAttribute("href"))).toEqual(
      ["#/test-scan/" + uuid(1001), "#/test-scan/" + uuid(1002)],
    );
    expect(rows[1]?.textContent).toContain("Partial");
  });

  it("is paged by the opaque cursor, forward and back", async () => {
    const scans = Array.from({ length: 5 }, (_, i) => scanItem(i));
    // The fake server pages by 2 whatever the limit, so paging is exercised.
    answer((call) => json(200, pageOf(scans, queryOf(call).cursor, 2)));
    await mount();
    const limit = Number(queryOf(at(callsTo(PATH), 0)).limit);
    expect(limit).toBeGreaterThanOrEqual(1);
    expect(limit).toBeLessThanOrEqual(500);
    expect(queryOf(at(callsTo(PATH), 0)).cursor).toBeUndefined();
    const hrefs = () =>
      section()
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.querySelector("a")?.getAttribute("href"));
    const first = hrefs();
    expect(first).toEqual([
      "#/test-scan/" + uuid(1000),
      "#/test-scan/" + uuid(1001),
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(at(callsTo(PATH), 1)).cursor).toBe("p-2");
    expect(hrefs()).toEqual([
      "#/test-scan/" + uuid(1002),
      "#/test-scan/" + uuid(1003),
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(queryOf(at(callsTo(PATH), 2)).cursor).toBeUndefined();
    expect(hrefs()).toEqual(first);
  });

  it("the empty state", async () => {
    server([]);
    await mount();
    expect(section().getByText("No scans of this host yet.")).toBeTruthy();
    expect(section().queryByRole("table")).toBeNull();
  });

  it("the error banner (404 unknown host)", async () => {
    answer(() => problem(404, "not_found", "Not found."));
    await mount();
    const alert = section().getByRole("alert");
    expect(alert.textContent).toContain("Request failed (status 404).");
    expect(alert.textContent).toContain("Not found.");
  });

  it("a network failure says the manager is unavailable", async () => {
    answer(() => Promise.reject(new TypeError("down")));
    await mount();
    expect(section().getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });

  it("<script> and onerror policy names render as text (CHK-M11-272)", async () => {
    server([
      scanItem(1, { policy_name: SCRIPT }),
      scanItem(2, { policy_name: IMG }),
    ]);
    const view = await mount();
    expect(section().getByText(SCRIPT)).toBeTruthy();
    expect(section().getByText(IMG)).toBeTruthy();
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});

type Detail = components["schemas"]["AgentDetailItem"];

function hostDetail(): Detail {
  return {
    agent_id: AGENT,
    hostname: "web-01",
    machine_id: "f".repeat(32),
    status: "online",
    agent_version: "0.2.0",
    enrolled_at: "2026-10-01T01:02:03Z",
    last_seen_ip: "10.1.2.3",
    last_heartbeat_at: "2026-10-25T10:00:00Z",
    last_inventory_at: "2026-10-25T09:00:00Z",
    token_issued_at: "2026-10-02T00:00:00Z",
    token_expires_at: "2026-12-31T00:00:00Z",
    token_revoked_at: null,
    tags: [],
    runner_helpers: [],
    os_id: "ubuntu",
    os_version_id: "24.04",
    os_pretty_name: "Ubuntu 24.04.1 LTS",
    os_info: null,
    last_snapshot: null,
  };
}

describe("CHK-M11-270 on the host page", () => {
  function hostServer(): void {
    answer((call) => {
      if (call.path === "/api/v1/agents/" + AGENT)
        return json(200, hostDetail());
      if (call.path === "/api/v1/agents/" + AGENT + "/packages")
        return json(200, { items: [], next_cursor: null });
      if (call.path === PATH)
        return json(200, { items: [scanItem(1)], next_cursor: null });
      return json(599, { type: "unexpected" });
    });
  }

  it("with scanLinks the host page shows the history", async () => {
    hostServer();
    render(
      <HostDetail agentId={AGENT} navigate={vi.fn()} scanLinks={mockLinks()} />,
    );
    await settle();
    expect(callsTo(PATH)).toHaveLength(1);
    expect(section().getAllByRole("row")).toHaveLength(2);
  });

  it("without scanLinks nothing changes and no scan request is sent", async () => {
    hostServer();
    render(<HostDetail agentId={AGENT} navigate={vi.fn()} />);
    await settle();
    expect(callsTo(PATH)).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Scans" })).toBeNull();
  });
});
