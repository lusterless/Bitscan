// TASK-169 TEST (TP-M7-29): CHK-M7-312.
// Expected values: REQ-181 (1), (4) for the list; TS §4.3 L546 (the UI lists
// `policy_name` and `policy_description`), L547-L548 (status and the admin
// override), §6.2 L1100 (`GET /policies?status=enabled`), §6.3 L1134 (cursor
// paging, `?limit=50&cursor=`), L1141 (plain text); #98 (a) (the item
// fields); #9 (the list holds no deleted policy).
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

import { clearSession, setSession } from "../app/session";
import { Profiles } from "./Profiles";

const LIST = "/api/v1/policies";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const TOKEN = bsu("P");

interface Item {
  policy_id: number;
  policy_name: string;
  policy_description: string;
  policy_status: "enabled" | "disabled";
  file_status: "enabled" | "disabled";
  status_overridden: boolean;
  family_id: number;
  family_name: string;
  format_version: string;
  version: number;
  source_file: string;
  plugin_count: number;
  imported_at: string;
  updated_at: string;
}

function item(id: number, extra: Partial<Item> = {}): Item {
  return {
    policy_id: id,
    policy_name: "Policy " + String(id).padStart(3, "0"),
    policy_description: "Description " + String(id),
    policy_status: "enabled",
    file_status: "enabled",
    status_overridden: false,
    family_id: 1,
    family_name: "CIS Ubuntu 24.04",
    format_version: "1.0",
    version: 1,
    source_file: "cis-" + String(id) + ".bit",
    plugin_count: 15,
    imported_at: "2026-10-27T08:00:00Z",
    updated_at: "2026-10-28T09:08:07Z",
    ...extra,
  };
}

/** A list route with the server's status filter and cursor paging. */
function policyServer(items: Item[], over?: (c: Call) => Response | null) {
  answer((call) => {
    const r = over?.(call);
    if (r) {
      return r;
    }
    if (call.path !== LIST || call.method !== "GET") {
      return json(599, { type: "unexpected" });
    }
    const q = queryOf(call);
    const want = items.filter(
      (x) => q.status === undefined || x.policy_status === q.status,
    );
    const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(1));
    const end = Math.min(start + Number(q.limit), want.length);
    return json(200, {
      items: want.slice(start, end),
      next_cursor: end < want.length ? "c" + String(end) : null,
    });
  });
}

const navigate = vi.fn();

beforeEach(() => {
  resetHttp();
  navigate.mockReset();
  setSession(loginResponse("viewer", true, TOKEN));
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
  const view = render(<Profiles navigate={navigate} />);
  await settle();
  return view;
}

/** Each body row's cells as text. */
function rows(): string[][] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((r) =>
      [...r.querySelectorAll("td")].map((td) => td.textContent ?? ""),
    );
}

function names(): string[] {
  return rows().map((r) => r[0] ?? "");
}

// ------------------------------------------------------------ CHK-M7-312

describe("CHK-M7-312 (a) the list renders the fixture", () => {
  it("asks limit=50 and no status; shows name, description, status, family and version", async () => {
    policyServer([
      item(1),
      item(2, {
        policy_status: "disabled",
        file_status: "disabled",
        family_name: "Clustermax",
        version: 4,
        plugin_count: 2,
      }),
      item(3, { policy_status: "disabled", status_overridden: true }),
    ]);
    await mount();
    expect(callsTo(LIST)).toHaveLength(1);
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({ limit: "50" });
    expect(callsTo(LIST)[0]?.authorization).toBe("Bearer " + TOKEN);
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Name",
      "Description",
      "Status",
      "Family",
      "Version",
      "Plugins",
      "Updated",
    ]);
    expect(rows()).toEqual([
      [
        "Policy 001",
        "Description 1",
        "Enabled",
        "CIS Ubuntu 24.04",
        "1",
        "15",
        "2026-10-28 09:08:07 UTC",
      ],
      [
        "Policy 002",
        "Description 2",
        "Disabled",
        "Clustermax",
        "4",
        "2",
        "2026-10-28 09:08:07 UTC",
      ],
      [
        "Policy 003",
        "Description 3",
        "Disabled (override)",
        "CIS Ubuntu 24.04",
        "1",
        "15",
        "2026-10-28 09:08:07 UTC",
      ],
    ]);
  });

  it("the server's order is kept (policy_name, then id, #98 (a))", async () => {
    policyServer([
      item(9, { policy_name: "b" }),
      item(2, { policy_name: "a" }),
    ]);
    await mount();
    expect(names()).toEqual(["b", "a"]);
  });

  it("each name links to its profile; a click navigates there", async () => {
    policyServer([item(12), item(345)]);
    await mount();
    const link = screen.getByRole("link", { name: "Policy 345" });
    expect(link.getAttribute("href")).toBe("#/profiles/345");
    expect(
      screen.getByRole("link", { name: "Policy 012" }).getAttribute("href"),
    ).toBe("#/profiles/12");
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({
      name: "profile",
      policyId: "345",
    });
  });

  it("an empty list says so", async () => {
    policyServer([]);
    await mount();
    expect(screen.getByText("No profiles.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("the list offers no admin action (it is a view for every role)", async () => {
    policyServer([item(1)]);
    const { container } = await mount();
    const buttons = [...container.querySelectorAll("button")].map(
      (b) => b.textContent,
    );
    expect(buttons).toEqual(["Previous", "Next"]);
  });
});

describe("CHK-M7-312 (b) the status filter", () => {
  it.each([
    ["enabled", { status: "enabled", limit: "50" }, ["Policy 001"]],
    ["disabled", { status: "disabled", limit: "50" }, ["Policy 002"]],
  ] as const)("%s sends status=%s", async (value, query, shown) => {
    policyServer([item(1), item(2, { policy_status: "disabled" })]);
    await mount();
    fireEvent.change(screen.getByLabelText("Status"), { target: { value } });
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual(query);
    expect(names()).toEqual(shown);
  });

  it("All again sends no status", async () => {
    policyServer([item(1), item(2, { policy_status: "disabled" })]);
    await mount();
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "disabled" },
    });
    await settle();
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "all" },
    });
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({ limit: "50" });
    expect(names()).toEqual(["Policy 001", "Policy 002"]);
  });

  it("offers exactly All, Enabled, Disabled (no Deleted: the list never holds one, #9)", async () => {
    policyServer([]);
    await mount();
    const options = [
      ...(screen.getByLabelText("Status") as HTMLSelectElement).options,
    ].map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["all", "All"],
      ["enabled", "Enabled"],
      ["disabled", "Disabled"],
    ]);
  });

  it("changing the filter on page 2 starts again at page 1 (no cursor)", async () => {
    policyServer(Array.from({ length: 60 }, (_, i) => item(i + 1)));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call).cursor).toBe("c50");
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "enabled" },
    });
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      status: "enabled",
      limit: "50",
    });
    expect(names()).toHaveLength(50);
    expect(names()[0]).toBe("Policy 001");
  });
});

describe("CHK-M7-312 (c) paging shows each policy once (REQ-181 (4))", () => {
  it("121 policies over three pages: every one exactly once, then back", async () => {
    const all = Array.from({ length: 121 }, (_, i) => item(i + 1));
    policyServer(all);
    await mount();
    const seen: string[] = [...names()];
    expect(seen).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    seen.push(...names());
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    seen.push(...names());
    expect(names()).toEqual(all.slice(100).map((x) => x.policy_name));
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(seen).toEqual(all.map((x) => x.policy_name));
    expect(new Set(seen).size).toBe(121);
    expect(callsTo(LIST).map((c) => queryOf(c).cursor ?? null)).toEqual([
      null,
      "c50",
      "c100",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(queryOf(callsTo(LIST).at(-1) as Call).cursor).toBe("c50");
    expect(names()[0]).toBe("Policy 051");
  });
});

describe("CHK-M7-312 (d) hostile text renders literally (REQ-181 (1))", () => {
  it("name, description and family create no element", async () => {
    const H = SCRIPT + IMG;
    policyServer([
      item(1, { policy_name: H, policy_description: IMG, family_name: SCRIPT }),
    ]);
    const { container } = await mount();
    expect(rows()[0]?.slice(0, 4)).toEqual([H, IMG, "Enabled", SCRIPT]);
    expect(screen.getByRole("link", { name: H })).toBeTruthy();
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });
});

describe("CHK-M7-312 (e) refusals", () => {
  it("a 503 shows the problem banner and no table", async () => {
    policyServer([], () => problem(503, "about:blank", "down"));
    await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "The manager is unavailable. Try again later.",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a network failure shows unavailable", async () => {
    answer(() => Promise.reject(new TypeError("down")) as never);
    await mount();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
    expect(calls).toHaveLength(1);
  });
});
