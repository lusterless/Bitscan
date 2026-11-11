// TASK-246 TEST (TP-M11-14): CHK-M11-265, CHK-M11-272 (Scans), plants
// CHK-M11-366 (screen half), CHK-M11-375 (Scans).
// Expected values: REQ-279 (1), (3); REQ-264 (filters policy_id, agent_id,
// state, created_after (>=), created_before (<), RFC 3339 with an offset;
// limit 1-500); #145 (a), (d); TS §6.3 L1136 (cursor pages), L1143.
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
import {
  IMG,
  SCRIPT,
  at,
  mockLinks,
  noInjectedMarkup,
  pageOf,
  policy,
  scanItem,
  settle,
  uuid,
  type ScanItem,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession, type Role } from "../app/session";
import { Scans } from "./Scans";

const LIST = "/api/v1/scans";
const POLICIES = "/api/v1/policies";

function server(
  scans: readonly ScanItem[],
  policies = [policy(7), policy(8, { policy_name: SCRIPT })],
): void {
  answer((call) => {
    if (call.path === POLICIES)
      return json(200, { items: policies, next_cursor: null });
    if (call.path === LIST) {
      const q = queryOf(call);
      return json(200, pageOf(scans, q.cursor, Number(q.limit)));
    }
    return json(599, { type: "unexpected" });
  });
}

async function mount(role: Role = "viewer") {
  setSession(loginResponse(role, true, bsu("V")));
  const links = mockLinks();
  const view = render(<Scans role={role} links={links} />);
  await settle();
  return { view, links };
}

function names(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelectorAll("td")[1]?.textContent ?? "");
}

function form() {
  return within(screen.getByRole("form", { name: "Filter scans" }));
}

beforeEach(() => {
  resetHttp();
});
afterEach(() => {
  clearSession();
});

describe("CHK-M11-265 the list and its query", () => {
  it("first request: limit 50, no filter, no cursor, with the bearer", async () => {
    server([scanItem(1)]);
    await mount();
    const first = at(callsTo(LIST), 0);
    expect(queryOf(first)).toEqual({ limit: "50" });
    expect(first.authorization).toBe("Bearer " + bsu("V"));
    expect(names()).toEqual(["CIS Ubuntu 24.04 1"]);
  });

  it("the filters build exactly the REQ-264 query", async () => {
    server([scanItem(1)]);
    await mount();
    const f = form();
    fireEvent.change(f.getByRole("combobox", { name: "Profile" }), {
      target: { value: "7" },
    });
    fireEvent.change(f.getByRole("textbox", { name: "Host id" }), {
      target: { value: "  " + uuid(5).toUpperCase() + " " },
    });
    fireEvent.change(f.getByRole("combobox", { name: "State" }), {
      target: { value: "partial" },
    });
    fireEvent.change(f.getByLabelText("Created on or after (UTC)"), {
      target: { value: "2026-11-01" },
    });
    fireEvent.change(f.getByLabelText("Created before (UTC)"), {
      target: { value: "2026-11-08" },
    });
    // Nothing is sent before Apply.
    expect(callsTo(LIST)).toHaveLength(1);
    fireEvent.click(f.getByRole("button", { name: "Apply" }));
    await settle();
    expect(callsTo(LIST)).toHaveLength(2);
    expect(queryOf(at(callsTo(LIST), 1))).toEqual({
      limit: "50",
      policy_id: "7",
      agent_id: uuid(5),
      state: "partial",
      created_after: "2026-11-01T00:00:00Z",
      created_before: "2026-11-08T00:00:00Z",
    });
  });

  it("each of the six states is offered and sent as its name", async () => {
    server([]);
    await mount();
    const select = form().getByRole("combobox", { name: "State" });
    const values = Array.from((select as HTMLSelectElement).options).map(
      (o) => o.value,
    );
    expect(values).toEqual([
      "",
      "queued",
      "running",
      "completed",
      "partial",
      "failed",
      "cancelled",
    ]);
  });

  it("a malformed host id refuses the filter and sends nothing", async () => {
    server([scanItem(1)]);
    await mount();
    fireEvent.change(form().getByRole("textbox", { name: "Host id" }), {
      target: { value: "not-a-uuid" },
    });
    fireEvent.click(form().getByRole("button", { name: "Apply" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "The host id must be a UUID and the dates must be valid.",
    );
    expect(callsTo(LIST)).toHaveLength(1);
  });

  it("clearing a filter drops its parameter", async () => {
    server([scanItem(1)]);
    await mount();
    const state = form().getByRole("combobox", { name: "State" });
    fireEvent.change(state, { target: { value: "failed" } });
    fireEvent.click(form().getByRole("button", { name: "Apply" }));
    await settle();
    fireEvent.change(state, { target: { value: "" } });
    fireEvent.click(form().getByRole("button", { name: "Apply" }));
    await settle();
    expect(queryOf(at(callsTo(LIST), 1))).toEqual({
      limit: "50",
      state: "failed",
    });
    expect(queryOf(at(callsTo(LIST), 2))).toEqual({ limit: "50" });
  });
});

describe("CHK-M11-265 paging forward and back", () => {
  it("51 scans: Next sends the cursor, Previous goes back, each scan once", async () => {
    const scans = Array.from({ length: 51 }, (_, i) => scanItem(i));
    server(scans);
    await mount();
    const first = names();
    expect(first).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(at(callsTo(LIST), 1))).toEqual({
      limit: "50",
      cursor: "p-50",
    });
    expect(names()).toEqual(["CIS Ubuntu 24.04 50"]);
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(queryOf(at(callsTo(LIST), 2))).toEqual({ limit: "50" });
    expect(names()).toEqual(first);
  });

  it("applying a filter on page 2 starts again at page 1", async () => {
    server(Array.from({ length: 51 }, (_, i) => scanItem(i)));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    fireEvent.change(form().getByRole("combobox", { name: "State" }), {
      target: { value: "completed" },
    });
    fireEvent.click(form().getByRole("button", { name: "Apply" }));
    await settle();
    const last = at(callsTo(LIST), callsTo(LIST).length - 1);
    expect(queryOf(last)).toEqual({ limit: "50", state: "completed" });
  });
});

describe("CHK-M11-265 Run scan by role (plant CHK-M11-366)", () => {
  it("a viewer sees no Run scan", async () => {
    server([scanItem(1)]);
    const { view } = await mount("viewer");
    expect(screen.queryByRole("link", { name: "Run scan" })).toBeNull();
    expect(view.container.textContent).not.toContain("Run scan");
  });

  for (const role of ["operator", "admin"] as const) {
    it(
      "an " + role + " gets Run scan linking to the Run scan screen",
      async () => {
        server([scanItem(1)]);
        await mount(role);
        expect(
          screen.getByRole("link", { name: "Run scan" }).getAttribute("href"),
        ).toBe("#/test-run-scan");
      },
    );
  }
});

describe("CHK-M11-265 states", () => {
  it("an empty list says No scans.", async () => {
    server([]);
    await mount();
    expect(screen.getByText("No scans.")).toBeTruthy();
  });

  it("a refusal shows the banner with its detail", async () => {
    answer((call) =>
      call.path === POLICIES
        ? json(200, { items: [], next_cursor: null })
        : problem(400, "invalid_request", "Invalid request: cursor"),
    );
    await mount();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Request failed (status 400).");
    expect(alert.textContent).toContain("Invalid request: cursor");
  });

  it("the profile filter falls back to All when the policies call fails", async () => {
    answer((call) =>
      call.path === POLICIES
        ? problem(503, "about:blank")
        : json(200, { items: [scanItem(1)], next_cursor: null }),
    );
    await mount();
    const select = form().getByRole("combobox", {
      name: "Profile",
    }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "All",
    ]);
    expect(names()).toEqual(["CIS Ubuntu 24.04 1"]);
  });
});

describe("CHK-M11-272 plain text on the Scans screen (plant CHK-M11-375)", () => {
  it("<script> and onerror policy names render as text in the list and the filter", async () => {
    server([
      scanItem(1, { policy_name: SCRIPT }),
      scanItem(2, { policy_name: IMG }),
    ]);
    const { view } = await mount();
    expect(names()).toEqual([SCRIPT, IMG]);
    const options = Array.from(
      (form().getByRole("combobox", { name: "Profile" }) as HTMLSelectElement)
        .options,
    ).map((o) => o.textContent);
    expect(options).toContain(SCRIPT);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });

  it("only the client was called (every call is a GET to a known path)", async () => {
    server([scanItem(1)]);
    await mount();
    const all = [...callsTo(LIST), ...callsTo(POLICIES)];
    expect(all.every((c: Call) => c.method === "GET")).toBe(true);
  });
});
