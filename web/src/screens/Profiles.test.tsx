// TASK-169 TEST (TP-M7-29, CHK-M7-310): the Profiles list screen.
// Expected values: REQ-181 (1) and (4) for the list (policy_name,
// policy_description, status, family, version; paging shows each policy once;
// hostile text renders literally and creates no element), #9 (the list filter
// takes enabled or disabled; deleted never appears), PD-34 (a) (every role),
// TS §4.3 L546-L548, §6.2 (GET /policies, every role), §6.3 L1134 (cursor
// pages), L1141 (plain text), REQ-126 and the lead's 503 rule.
import {
  answer,
  bsu,
  calls,
  callsTo,
  deferred,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import { clearSession, setSession } from "../app/session";
import { Profiles } from "./Profiles";

type PolicyItem = components["schemas"]["PolicyItem"];

const LIST = "/api/v1/policies";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const BOLD = "<b>x</b>";
const RTL = "‮gnp.exe‬ policy";
const LONG = "N".repeat(16384);

function policy(i: number, extra: Partial<PolicyItem> = {}): PolicyItem {
  return {
    policy_id: 100 + i,
    policy_name: "Policy " + String(i).padStart(3, "0"),
    policy_description: "Description " + String(i),
    policy_status: "enabled",
    file_status: "enabled",
    status_overridden: false,
    family_id: 7,
    family_name: "CIS Ubuntu 24.04",
    format_version: "1.0",
    version: 3,
    plugin_count: 12,
    source_file: "cis-ubuntu-2404.bit",
    imported_at: "2026-10-25T09:00:00Z",
    updated_at: "2026-10-25T10:11:12Z",
    ...extra,
  };
}

/** A fake GET /policies: filters by status, pages by an offset cursor. */
function policyServer(items: PolicyItem[], size?: number): void {
  answer((call) => {
    if (call.path !== LIST || call.method !== "GET") {
      return json(599, { type: "unexpected" });
    }
    const q = queryOf(call);
    const wanted =
      q.status === undefined
        ? items
        : items.filter((p) => p.policy_status === q.status);
    const limit = size ?? Number(q.limit);
    const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(2));
    const end = Math.min(start + limit, wanted.length);
    return json(200, {
      items: wanted.slice(start, end),
      next_cursor: end < wanted.length ? "p-" + String(end) : null,
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

async function mount(
  onOpen?: (id: number) => void,
): Promise<ReturnType<typeof render>> {
  const view = render(
    onOpen === undefined ? <Profiles /> : <Profiles onOpen={onOpen} />,
  );
  await settle();
  return view;
}

function rows(): HTMLElement[] {
  return screen.getAllByRole("row").slice(1);
}

function names(): string[] {
  return rows().map((r) => r.querySelector("td")?.textContent ?? "");
}

function cells(row: HTMLElement): string[] {
  return Array.from(row.querySelectorAll("td")).map((c) => c.textContent);
}

function statusSelect(): HTMLSelectElement {
  return screen.getByRole("combobox", { name: "Status" });
}

async function pick(value: string): Promise<void> {
  fireEvent.change(statusSelect(), { target: { value } });
  await settle();
}

async function click(name: string): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name }));
  await settle();
}

function noDeleted(): void {
  for (const c of calls) {
    expect(c.query.get("status")).not.toBe("deleted");
    expect(c.url).not.toContain("deleted");
  }
}

// ------------------------------------------------------------ REQ-181 (1)

describe("REQ-181 (1) list columns", () => {
  it("shows every column of each fixture policy", async () => {
    policyServer([
      policy(1),
      policy(2, {
        policy_status: "disabled",
        status_overridden: true,
        family_name: "Clustermax",
        version: 1,
        plugin_count: 0,
        updated_at: "2026-01-02T03:04:05Z",
      }),
    ]);
    await mount();
    expect(
      screen.getAllByRole("columnheader").map((h) => h.textContent),
    ).toEqual([
      "Name",
      "Description",
      "Status",
      "Family",
      "Version",
      "Plugins",
      "Updated",
    ]);
    const [r1, r2] = rows();
    expect(cells(r1 as HTMLElement)).toEqual([
      "Policy 001",
      "Description 1",
      "Enabled",
      "CIS Ubuntu 24.04",
      "3",
      "12",
      "2026-10-25 10:11:12 UTC",
    ]);
    expect(cells(r2 as HTMLElement)).toEqual([
      "Policy 002",
      "Description 2",
      "Disabled (set by an admin)",
      "Clustermax",
      "1",
      "0",
      "2026-01-02 03:04:05 UTC",
    ]);
  });

  it("the override note follows status_overridden, not the file status", async () => {
    policyServer([
      policy(1, { policy_status: "enabled", file_status: "disabled" }),
      policy(2, { policy_status: "enabled", status_overridden: true }),
      policy(3, { policy_status: "disabled", file_status: "disabled" }),
    ]);
    await mount();
    expect(rows().map((r) => cells(r)[2])).toEqual([
      "Enabled",
      "Enabled (set by an admin)",
      "Disabled",
    ]);
  });

  it("an empty list says so and offers no next page", async () => {
    policyServer([]);
    await mount();
    expect(screen.getByText("No profiles.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("shows Loading until the answer arrives", async () => {
    const d = deferred();
    answer(() => d.promise);
    await mount();
    expect(screen.getByText("Loading.")).toBeTruthy();
    d.resolve(json(200, { items: [policy(1)], next_cursor: null }));
    await settle();
    expect(screen.queryByText("Loading.")).toBeNull();
    expect(names()).toEqual(["Policy 001"]);
  });
});

// ------------------------------------------------------------ plain text

describe("REQ-181 (1) hostile text renders literally", () => {
  it.each([false, true])(
    "names, descriptions and families create no element (onOpen %s)",
    async (withOpen) => {
      policyServer([
        policy(1, {
          policy_name: SCRIPT,
          policy_description: IMG,
          family_name: BOLD,
        }),
        policy(2, {
          policy_name: RTL,
          policy_description: SCRIPT + IMG,
          family_name: RTL,
        }),
        policy(3, { policy_name: LONG, policy_description: LONG }),
      ]);
      const { container } = await mount(withOpen ? vi.fn() : undefined);
      const [r1, r2, r3] = rows().map(cells);
      expect(r1?.slice(0, 4)).toEqual([SCRIPT, IMG, "Enabled", BOLD]);
      expect(r2?.slice(0, 4)).toEqual([RTL, SCRIPT + IMG, "Enabled", RTL]);
      expect(r3?.[0]).toHaveLength(16384);
      expect(r3?.[1]).toBe(LONG);
      expect(
        container.querySelectorAll("script, img, b, iframe, [onerror]"),
      ).toHaveLength(0);
      expect(container.innerHTML).not.toContain("<script");
      expect(container.innerHTML).not.toContain("<img");
      expect(container.innerHTML).toContain("&lt;script&gt;");
      // The RTL override stays a character in a text node; no dir attribute.
      expect(container.querySelectorAll("[dir]")).toHaveLength(0);
    },
  );

  it("a hostile detail in a problem answer is shown as text", async () => {
    answer(() => problem(400, "invalid_request", SCRIPT + IMG));
    const { container } = await mount();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Request failed (status 400).");
    expect(alert.textContent).toContain(SCRIPT + IMG);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ REQ-181 (4)

describe("REQ-181 (4) paging", () => {
  it("51 policies at 50: next and previous show each policy once", async () => {
    policyServer(Array.from({ length: 51 }, (_, i) => policy(i)));
    await mount();
    expect(callsTo(LIST)).toHaveLength(1);
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({ limit: "50" });
    const first = names();
    expect(first).toHaveLength(50);
    expect(
      (screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await click("Next");
    expect(callsTo(LIST)).toHaveLength(2);
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      cursor: "p-50",
    });
    expect(names()).toEqual(["Policy 050"]);
    expect(new Set([...first, ...names()]).size).toBe(51);
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await click("Previous");
    expect(callsTo(LIST)).toHaveLength(3);
    expect(callsTo(LIST).at(-1)?.query.has("cursor")).toBe(false);
    expect(names()).toEqual(first);
  });

  it("a server page size of 2 (5 policies) walks 3 pages, each once", async () => {
    policyServer(
      Array.from({ length: 5 }, (_, i) => policy(i)),
      2,
    );
    await mount();
    const seen = [...names()];
    await click("Next");
    seen.push(...names());
    await click("Next");
    seen.push(...names());
    expect(seen).toEqual([
      "Policy 000",
      "Policy 001",
      "Policy 002",
      "Policy 003",
      "Policy 004",
    ]);
    expect(callsTo(LIST).map((c) => c.query.get("cursor"))).toEqual([
      null,
      "p-2",
      "p-4",
    ]);
    expect(calls).toHaveLength(3);
  });

  it("a stale answer for an old page is dropped", async () => {
    const first = deferred();
    let n = 0;
    answer(() => {
      n += 1;
      return n === 1
        ? first.promise
        : json(200, { items: [policy(9)], next_cursor: null });
    });
    await mount();
    await pick("disabled");
    expect(names()).toEqual(["Policy 009"]);
    first.resolve(json(200, { items: [policy(1)], next_cursor: "p-1" }));
    await settle();
    expect(names()).toEqual(["Policy 009"]);
  });
});

// ------------------------------------------------------------ #9 filter

describe("#9 status filter", () => {
  it("offers exactly all, enabled and disabled", async () => {
    policyServer([policy(1)]);
    await mount();
    expect(Array.from(statusSelect().options).map((o) => o.value)).toEqual([
      "all",
      "enabled",
      "disabled",
    ]);
    expect(statusSelect().value).toBe("all");
  });

  it("each choice sends its status, resets to page 1, never sends deleted", async () => {
    policyServer(
      Array.from({ length: 120 }, (_, i) =>
        policy(i, { policy_status: i % 2 === 0 ? "enabled" : "disabled" }),
      ),
    );
    await mount();
    await click("Next");
    expect(callsTo(LIST).at(-1)?.query.get("cursor")).toBe("p-50");
    await pick("disabled");
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      status: "disabled",
    });
    expect(screen.getByText("Page 1")).toBeTruthy();
    expect(rows().every((r) => cells(r)[2] === "Disabled")).toBe(true);
    await click("Next");
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      status: "disabled",
      cursor: "p-50",
    });
    await pick("enabled");
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({
      limit: "50",
      status: "enabled",
    });
    expect(rows().every((r) => cells(r)[2] === "Enabled")).toBe(true);
    await pick("all");
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({ limit: "50" });
    noDeleted();
    expect(calls.every((c) => c.path === LIST && c.method === "GET")).toBe(
      true,
    );
  });

  it("a forged deleted option value maps to all and is never sent", async () => {
    policyServer([policy(1)]);
    await mount();
    const select = statusSelect();
    const forged = document.createElement("option");
    forged.value = "deleted";
    select.appendChild(forged);
    await pick("disabled");
    await pick("deleted");
    expect(queryOf(callsTo(LIST).at(-1) as Call)).toEqual({ limit: "50" });
    noDeleted();
  });
});

// ------------------------------------------------------------ roles

describe("PD-34 (a): every role sees the list", () => {
  it.each(["viewer", "operator", "admin"])(
    "%s: one GET /api/v1/policies?limit=50 with the session token",
    async (role) => {
      const token = bsu(role.slice(0, 1).toUpperCase());
      setSession(loginResponse(role, true, token));
      policyServer([policy(1), policy(2)]);
      await mount();
      expect(calls).toHaveLength(1);
      expect(calls[0]?.method).toBe("GET");
      expect(calls[0]?.url).toBe("/api/v1/policies?limit=50");
      expect(calls[0]?.authorization).toBe("Bearer " + token);
      expect(names()).toEqual(["Policy 001", "Policy 002"]);
    },
  );
});

// ------------------------------------------------------------ errors

describe("error states go through problems.ts", () => {
  it.each([
    [problem(401, "unauthorized"), "Your session has ended. Sign in again."],
    [problem(403, "forbidden"), "Your role does not allow this."],
    [
      problem(503, "about:blank", "starting", { "Retry-After": "10" }),
      "The manager is not ready yet. Try again in 10 seconds.",
    ],
    [
      problem(503, "about:blank", "internal"),
      "The manager is unavailable. Try again later.",
    ],
    [problem(500, "about:blank"), "Request failed (status 500)."],
  ] as const)("%#: the banner shows the fixed text", async (resp, text) => {
    answer(() => resp.clone());
    await mount();
    const alert = screen.getByRole("alert");
    expect(alert.querySelector("p")?.textContent).toBe(text);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Loading.")).toBeNull();
  });

  it("a network failure shows the unavailable callout", async () => {
    answer(() => Promise.reject(new TypeError("down")));
    await mount();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
    expect(screen.queryByText("Loading.")).toBeNull();
  });

  it("a later success clears the banner", async () => {
    let n = 0;
    answer(() => {
      n += 1;
      return n === 1
        ? problem(500, "about:blank")
        : json(200, { items: [policy(1)], next_cursor: null });
    });
    await mount();
    expect(screen.getByRole("alert")).toBeTruthy();
    await pick("enabled");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(names()).toEqual(["Policy 001"]);
  });
});

// ------------------------------------------------------------ onOpen

describe("onOpen", () => {
  it("without it the name is plain text, with no button", async () => {
    policyServer([policy(1)]);
    await mount();
    expect(screen.queryByRole("button", { name: "Policy 001" })).toBeNull();
    expect(screen.getByText("Policy 001").tagName).toBe("TD");
  });

  it("with it a click on the name calls onOpen(policy_id) once", async () => {
    policyServer([policy(1), policy(2)]);
    const onOpen = vi.fn();
    await mount(onOpen);
    fireEvent.click(screen.getByRole("button", { name: "Policy 002" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(102);
    expect(calls).toHaveLength(1);
  });
});
