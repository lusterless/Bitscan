// TASK-249 TEST (TP-M11-14): CHK-M11-269 (screen half; the viewer gating
// half is TASK-251's, in App.test.tsx), CHK-M11-272 (schedules).
// Expected values: REQ-282 (1) (create sends the #122 (h) body; an edit
// sends only the changed fields; delete asks to confirm), (2) (400 and 409
// show their fixed detail); #122 (h) (POST {name, policy_id, target, cron,
// timezone?: "UTC", enabled?: true}; PATCH any non-empty subset of name,
// target, cron, timezone, enabled; policy_id cannot change; DELETE 204; a
// disabled policy is allowed); #154 (d) (same target picker); TS §6.3 L1143.
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
  type Handler,
} from "../test/harness";
import {
  IMG,
  SCRIPT,
  agentItem,
  at,
  noInjectedMarkup,
  pageOf,
  policy,
  schedule,
  settle,
  uuid,
  type ScheduleItem,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession } from "../app/session";
import { formatTime } from "../format";
import { Schedules } from "./Schedules";

const LIST = "/api/v1/scan-schedules";
const POLICIES = "/api/v1/policies";

interface Server {
  items: ScheduleItem[];
  write: Handler;
}

function server(
  items: ScheduleItem[],
  write: Handler = () => json(599, { type: "unexpected" }),
): Server {
  const s: Server = { items, write };
  answer((call) => {
    if (call.path === POLICIES)
      return json(200, {
        items: [
          policy(7),
          policy(8, { policy_status: "disabled", policy_name: "Disabled one" }),
          policy(9, { policy_name: SCRIPT }),
        ],
        next_cursor: null,
      });
    if (call.path === "/api/v1/agents")
      return json(200, {
        items: [agentItem(1), agentItem(2)],
        next_cursor: null,
      });
    if (call.path === LIST && call.method === "GET") {
      const q = queryOf(call);
      return json(200, pageOf(s.items, q.cursor, Number(q.limit)));
    }
    return s.write(call);
  });
  return s;
}

async function mount() {
  const view = render(<Schedules />);
  await settle();
  return view;
}

function writes(): Call[] {
  return calls.filter((c) => c.method !== "GET");
}

function rowOf(name: string): HTMLElement {
  const row = screen
    .getAllByRole("row")
    .find((r) => r.querySelector("td")?.textContent === name);
  if (row === undefined) throw new Error("no row " + name);
  return row;
}

function theForm(name: "New schedule" | "Edit schedule") {
  return within(screen.getByRole("form", { name }));
}

function type(
  form: ReturnType<typeof theForm>,
  label: RegExp,
  value: string,
): void {
  fireEvent.change(form.getByRole("textbox", { name: label }), {
    target: { value },
  });
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("operator", true, bsu("O")));
});
afterEach(() => {
  clearSession();
});

describe("CHK-M11-269 the list", () => {
  it("shows each schedule's fields, last and next run, through the client", async () => {
    server([
      schedule(1),
      schedule(2, {
        policy_id: 42,
        target: { all: true },
        enabled: false,
        last_run_at: "2026-11-08T02:00:00Z",
        next_run_at: null,
        timezone: "Asia/Singapore",
      }),
    ]);
    await mount();
    expect(queryOf(at(callsTo(LIST), 0))).toEqual({ limit: "50" });
    expect(at(callsTo(LIST), 0).authorization).toBe("Bearer " + bsu("O"));
    const cells = (r: HTMLElement) =>
      Array.from(r.querySelectorAll("td"))
        .slice(0, 8)
        .map((td) => td.textContent);
    expect(cells(rowOf("Nightly 1"))).toEqual([
      "Nightly 1",
      "Profile 7",
      "Hosts with any of the tags: prod-web",
      "0 2 * * *",
      "UTC",
      "yes",
      formatTime(null),
      formatTime("2026-11-09T02:00:00Z"),
    ]);
    expect(cells(rowOf("Nightly 2"))).toEqual([
      "Nightly 2",
      "Profile 42",
      "All hosts",
      "0 2 * * *",
      "Asia/Singapore",
      "no",
      formatTime("2026-11-08T02:00:00Z"),
      formatTime(null),
    ]);
  });

  it("an empty list says No schedules.", async () => {
    server([]);
    await mount();
    expect(screen.getByText("No schedules.")).toBeTruthy();
  });

  it("a refused list shows the banner", async () => {
    answer((call) =>
      call.path === LIST
        ? problem(403, "forbidden")
        : json(200, { items: [], next_cursor: null }),
    );
    await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
  });
});

describe("CHK-M11-269 create sends the #122 (h) body", () => {
  it("name, policy_id, target, cron, timezone UTC and enabled true; then the list reloads", async () => {
    const s = server([], (call) => {
      if (call.method === "POST" && call.path === LIST) {
        s.items = [schedule(5, { name: "Weekly" })];
        return json(201, s.items[0]);
      }
      return json(599, { type: "unexpected" });
    });
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const f = theForm("New schedule");
    type(f, /^Name/, "Weekly");
    fireEvent.change(f.getByRole("combobox", { name: "Profile" }), {
      target: { value: "7" },
    });
    fireEvent.click(
      f.getByRole("radio", { name: "Hosts with any of these tags" }),
    );
    type(f, /^Tags/, "prod-web db");
    type(f, /^Cron/, "0 3 * * 1");
    expect(
      (f.getByRole("textbox", { name: /^Time zone/ }) as HTMLInputElement)
        .value,
    ).toBe("UTC");
    expect(
      (f.getByRole("checkbox", { name: "Enabled" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(writes()).toHaveLength(1);
    const post = at(writes(), 0);
    expect(post.path).toBe(LIST);
    expect(JSON.parse(post.body)).toEqual({
      name: "Weekly",
      policy_id: 7,
      target: { tags: ["prod-web", "db"] },
      cron: "0 3 * * 1",
      timezone: "UTC",
      enabled: true,
    });
    expect(screen.queryByRole("form", { name: "New schedule" })).toBeNull();
    expect(callsTo(LIST)).toHaveLength(2);
    expect(rowOf("Weekly")).toBeTruthy();
  });

  it("a disabled profile can be chosen (#122 (h)); the profiles call has no status filter", async () => {
    server([], () => json(201, schedule(6)));
    await mount();
    expect(queryOf(at(callsTo(POLICIES), 0)).status).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const f = theForm("New schedule");
    const select = f.getByRole("combobox", {
      name: "Profile",
    }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toContain(
      "Disabled one",
    );
    type(f, /^Name/, "D");
    fireEvent.change(select, { target: { value: "8" } });
    type(f, /^Cron/, "0 1 * * *");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(JSON.parse(at(writes(), 0).body)).toMatchObject({
      policy_id: 8,
      target: { all: true },
    });
  });

  it("no profile, or a bad tag, is refused before sending", async () => {
    server([]);
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const f = theForm("New schedule");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(f.getByRole("alert").textContent).toBe("Choose a profile.");
    fireEvent.change(f.getByRole("combobox", { name: "Profile" }), {
      target: { value: "7" },
    });
    fireEvent.click(
      f.getByRole("radio", { name: "Hosts with any of these tags" }),
    );
    type(f, /^Tags/, "bad tag/");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(f.getByRole("alert").textContent).toContain(
      "Tags are 1 to 32 names",
    );
    expect(writes()).toHaveLength(0);
  });

  it("Cancel closes the form and sends nothing", async () => {
    server([]);
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    fireEvent.click(
      theForm("New schedule").getByRole("button", { name: "Cancel" }),
    );
    expect(screen.queryByRole("form", { name: "New schedule" })).toBeNull();
    expect(writes()).toHaveLength(0);
  });
});

describe("CHK-M11-269 an edit sends only the changed fields", () => {
  function patching(): Server {
    return server([schedule(3, { target: { agents: [uuid(1)] } })], (call) =>
      call.method === "PATCH"
        ? json(200, schedule(3))
        : json(599, { type: "unexpected" }),
    );
  }

  async function edit() {
    await mount();
    fireEvent.click(
      within(rowOf("Nightly 3")).getByRole("button", { name: "Edit" }),
    );
    await settle();
    return theForm("Edit schedule");
  }

  it("only cron changed: PATCH {cron}", async () => {
    patching();
    const f = await edit();
    type(f, /^Cron/, "30 4 * * *");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    const patch = at(writes(), 0);
    expect(patch.method).toBe("PATCH");
    expect(patch.path).toBe(LIST + "/3");
    expect(JSON.parse(patch.body)).toEqual({ cron: "30 4 * * *" });
    expect(callsTo(LIST)).toHaveLength(2);
  });

  it("name and enabled changed: exactly those two", async () => {
    patching();
    const f = await edit();
    type(f, /^Name/, "Renamed");
    fireEvent.click(f.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(JSON.parse(at(writes(), 0).body)).toEqual({
      name: "Renamed",
      enabled: false,
    });
  });

  it("the stored chosen-hosts target loads into the picker and is not resent when unchanged", async () => {
    patching();
    const f = await edit();
    expect(
      (f.getByRole("radio", { name: "These hosts" }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (f.getByRole("checkbox", { name: /host-1/ }) as HTMLInputElement).checked,
    ).toBe(true);
    type(f, /^Time zone/, "Europe/Berlin");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(JSON.parse(at(writes(), 0).body)).toEqual({
      timezone: "Europe/Berlin",
    });
  });

  it("a target change sends the new target only", async () => {
    patching();
    const f = await edit();
    fireEvent.click(f.getByRole("checkbox", { name: /host-2/ }));
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(JSON.parse(at(writes(), 0).body)).toEqual({
      target: { agents: [uuid(1), uuid(2)] },
    });
  });

  it("nothing changed: says so and sends nothing; the profile cannot change", async () => {
    patching();
    const f = await edit();
    expect(
      (f.getByRole("combobox", { name: "Profile" }) as HTMLSelectElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(f.getByRole("alert").textContent).toBe("Nothing has changed.");
    expect(writes()).toHaveLength(0);
  });
});

describe("CHK-M11-269 refusals show their detail (REQ-282 (2))", () => {
  it("400 on create keeps the form open with the detail", async () => {
    server([], () => problem(400, "invalid_request", "Invalid request: cron"));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const f = theForm("New schedule");
    type(f, /^Name/, "N");
    fireEvent.change(f.getByRole("combobox", { name: "Profile" }), {
      target: { value: "7" },
    });
    type(f, /^Cron/, "61 * * * *");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    const alert = f.getByRole("alert");
    expect(alert.textContent).toContain("Request failed (status 400).");
    expect(alert.textContent).toContain("Invalid request: cron");
    expect(callsTo(LIST)).toHaveLength(1);
  });

  it("409 on edit shows the detail", async () => {
    server([schedule(3)], () =>
      problem(409, "conflict", "The policy is deleted."),
    );
    await mount();
    fireEvent.click(
      within(rowOf("Nightly 3")).getByRole("button", { name: "Edit" }),
    );
    const f = theForm("Edit schedule");
    fireEvent.click(f.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await settle();
    expect(f.getByRole("alert").textContent).toContain(
      "The policy is deleted.",
    );
  });
});

describe("CHK-M11-269 delete asks to confirm", () => {
  it("no DELETE until confirmed; Cancel sends nothing; Confirm deletes and reloads", async () => {
    const s = server([schedule(3), schedule(4)], (call) => {
      if (call.method === "DELETE") {
        s.items = [schedule(4)];
        return noContent();
      }
      return json(599, { type: "unexpected" });
    });
    await mount();
    const row = rowOf("Nightly 3");
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete" });
    expect(dialog.textContent).toContain("Nightly 3");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await settle();
    expect(writes()).toHaveLength(0);
    fireEvent.click(
      within(rowOf("Nightly 3")).getByRole("button", { name: "Delete" }),
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog", { name: "Delete" })).getByRole(
        "button",
        {
          name: "Confirm",
        },
      ),
    );
    await settle();
    expect(writes().map((c) => c.method + " " + c.path)).toEqual([
      "DELETE " + LIST + "/3",
    ]);
    expect(callsTo(LIST)).toHaveLength(2);
    expect(
      screen
        .queryAllByRole("row")
        .some((r) => r.textContent?.includes("Nightly 3")),
    ).toBe(false);
  });

  it("a refused delete shows the banner and keeps the row", async () => {
    server([schedule(3)], () => problem(404, "not_found", "Not found."));
    await mount();
    fireEvent.click(
      within(rowOf("Nightly 3")).getByRole("button", { name: "Delete" }),
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog", { name: "Delete" })).getByRole(
        "button",
        {
          name: "Confirm",
        },
      ),
    );
    await settle();
    expect(screen.getByRole("alert").textContent).toContain("Not found.");
    expect(rowOf("Nightly 3")).toBeTruthy();
  });
});

describe("CHK-M11-272 plain text on the schedules screen", () => {
  it("<script> names, profile names and tags render as text", async () => {
    server([
      schedule(3, { name: SCRIPT, policy_id: 9, target: { tags: [IMG] } }),
    ]);
    const view = await mount();
    const row = rowOf(SCRIPT);
    expect(row.textContent).toContain(SCRIPT);
    expect(row.textContent).toContain("Hosts with any of the tags: " + IMG);
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(
      screen.getByRole("alertdialog", { name: "Delete" }).textContent,
    ).toContain(SCRIPT);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});
