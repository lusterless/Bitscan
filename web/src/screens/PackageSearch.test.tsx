// TASK-124 TEST (TP-M5-17): CHK-M5-260 to CHK-M5-265 (and the TASK-125
// export button on this screen, CHK-M5-274).
// Expected values: REQ-129 (1)-(5), REQ-136, REQ-132; TS §7.1 (the eleven
// parameters; version_op only with version; q and name not both), §7.3 L1223
// (grouped package -> version -> host count, click through to hosts); #86
// (a), (b); lead ruling 2026-10-25 "TASK-124 version drill-down carries the
// active filters" (status, os, tag, host; impl-web also carries agent_id).
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
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  expectTypeOf,
  it,
  vi,
} from "vitest";

import type { UserPathsArePrefixed } from "../api/client";
import type { components, paths } from "../api/schema";
import { clearSession, setSession } from "../app/session";
import { PackageSearch } from "./PackageSearch";

type PackageGroup = components["schemas"]["PackageGroupItem"];
type Row = components["schemas"]["PackageRowItem"];
type HostGroup = components["schemas"]["HostGroupItem"];

const SEARCH = "/api/v1/packages/search";
const CRLF = String.fromCharCode(13, 10);
const CSV = "/api/v1/packages/search.csv";
const A1 = "0f8fad5b-d9cb-469f-a165-000000000001";
const A2 = "0f8fad5b-d9cb-469f-a165-000000000002";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";

const GROUPS: PackageGroup[] = [
  {
    name: "openssl",
    version: "3.0.2-0ubuntu1.18",
    architecture: "amd64",
    host_count: 4,
  },
  {
    name: "openssl",
    version: "3.0.13-0ubuntu3.5",
    architecture: "amd64",
    host_count: 7,
  },
  {
    name: "openssl-doc",
    version: "3.0.13-0ubuntu3.5",
    architecture: "all",
    host_count: 2,
  },
];
const ROWS: Row[] = [
  {
    name: "openssl",
    version: "3.0.13-0ubuntu3.5",
    architecture: "amd64",
    status: "install ok installed",
    agent_id: A1,
    hostname: "web-01",
  },
  {
    name: "openssl",
    version: "3.0.13-0ubuntu3.5",
    architecture: "amd64",
    status: "hold ok installed",
    agent_id: A2,
    hostname: "web-02",
  },
];
const HOSTS: HostGroup[] = [
  { agent_id: A1, hostname: "web-01", package_count: 3 },
  { agent_id: A2, hostname: "db-01", package_count: 1 },
];

/** Answers by shape: package groups, host groups, or rows (no group_by). */
function searchServer(
  over: Partial<{
    groups: PackageGroup[];
    hosts: HostGroup[];
    rows: Row[];
    pageSize: number;
  }> = {},
) {
  const data = { groups: GROUPS, hosts: HOSTS, rows: ROWS, ...over };
  answer((call) => {
    if (call.path !== SEARCH) {
      return json(599, { type: "unexpected" });
    }
    const q = queryOf(call);
    const items: object[] =
      q.group_by === "package"
        ? data.groups
        : q.group_by === "host"
          ? data.hosts
          : data.rows;
    const size = data.pageSize ?? Number(q.limit);
    const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(2));
    const end = Math.min(start + size, items.length);
    return json(200, {
      items: items.slice(start, end),
      next_cursor: end < items.length ? "s-" + String(end) : null,
    });
  });
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("viewer", true, bsu("V")));
});

afterEach(() => {
  clearSession();
  vi.useRealTimers();
});

async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 4; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

async function mount(navigate = vi.fn()): Promise<ReturnType<typeof render>> {
  const view = render(<PackageSearch navigate={navigate} />);
  await settle();
  return view;
}

function type(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function choose(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function search(): Promise<void> {
  fireEvent.submit(screen.getByRole("form", { name: "Search packages" }));
  await settle();
}

function searches(): Call[] {
  return callsTo(SEARCH).filter((c) => c.query.get("limit") === "50");
}

function lastSearch(): Record<string, string> {
  return queryOf(searches().at(-1) as Call);
}

// ------------------------------------------------------------ CHK-M5-260

describe("CHK-M5-260 the form sends exactly the filled parameters", () => {
  it("nothing is requested before Search; an empty form sends only the view", async () => {
    searchServer();
    await mount();
    expect(calls).toHaveLength(0);
    await search();
    expect(searches()).toHaveLength(1);
    expect(lastSearch()).toEqual({ group_by: "package", limit: "50" });
    expect(searches()[0]?.authorization).toBeNull();
    expect(searches()[0]?.csrf).toBe("1");
  });

  it("every field filled, as typed", async () => {
    searchServer();
    await mount();
    type("Exact name", "openssl");
    type("Version", "1:3.0");
    choose("Version comparison", "ge");
    type("Architecture", "amd64");
    choose("Status", "any");
    type("OS (for example ubuntu:24.04)", "ubuntu:24.04");
    type("Host tag", "prod-web");
    type("Hostname contains", " WEB ");
    type("Agent id", A1);
    choose("View", "host");
    await search();
    expect(lastSearch()).toEqual({
      name: "openssl",
      version: "1:3.0",
      version_op: "ge",
      arch: "amd64",
      status: "any",
      os: "ubuntu:24.04",
      tag: "prod-web",
      host: " WEB ",
      agent_id: A1,
      group_by: "host",
      limit: "50",
    });
  });

  it("q alone; status installed is not sent (the server default)", async () => {
    searchServer();
    await mount();
    type("Name contains (q, 3 or more characters)", "ssl");
    choose("Status", "installed");
    await search();
    expect(lastSearch()).toEqual({
      q: "ssl",
      group_by: "package",
      limit: "50",
    });
  });

  it("version_op only with a version: disabled without one, never sent", async () => {
    searchServer();
    await mount();
    const op = screen.getByLabelText("Version comparison") as HTMLSelectElement;
    expect(op.disabled).toBe(true);
    type("Version", "2.0");
    expect(op.disabled).toBe(false);
    choose("Version comparison", "lt");
    type("Version", "");
    expect(op.disabled).toBe(true);
    await search();
    expect(lastSearch()).toEqual({ group_by: "package", limit: "50" });
    type("Version", "2.0");
    choose("Version comparison", "");
    await search();
    expect(lastSearch()).toEqual({
      version: "2.0",
      group_by: "package",
      limit: "50",
    });
  });

  it("q and name together send nothing and explain", async () => {
    searchServer();
    await mount();
    type("Name contains (q, 3 or more characters)", "ssl");
    type("Exact name", "openssl");
    await search();
    expect(searches()).toHaveLength(0);
    expect(screen.getByRole("alert").textContent).toBe(
      "Use either “Name contains” or “Exact name”, not both.",
    );
  });

  it("a 400 shows its detail as text", async () => {
    answer(() =>
      problem(400, "invalid_request", "Invalid request: query.q " + IMG),
    );
    const { container } = await mount();
    type("Name contains (q, 3 or more characters)", "ab");
    await search();
    expect(screen.getByText("Invalid request: query.q " + IMG)).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M5-261

describe("CHK-M5-261 group_by=package nested by name", () => {
  it("two names and three versions render as two groups with versions and host counts", async () => {
    searchServer();
    await mount();
    await search();
    const sections = screen.getAllByRole("region");
    expect(sections.map((s) => s.getAttribute("aria-label"))).toEqual([
      "openssl",
      "openssl-doc",
    ]);
    const rowsOf = (name: string): string[][] =>
      within(screen.getByRole("region", { name }))
        .getAllByRole("row")
        .slice(1)
        .map((r) =>
          Array.from(r.querySelectorAll("td")).map((c) => c.textContent ?? ""),
        );
    expect(rowsOf("openssl")).toEqual([
      ["3.0.2-0ubuntu1.18", "amd64", "4"],
      ["3.0.13-0ubuntu3.5", "amd64", "7"],
    ]);
    expect(rowsOf("openssl-doc")).toEqual([["3.0.13-0ubuntu3.5", "all", "2"]]);
    expect(
      within(screen.getByRole("region", { name: "openssl" })).getByRole(
        "heading",
        {
          level: 2,
        },
      ).textContent,
    ).toBe("openssl");
  });

  it("an empty result says so", async () => {
    searchServer({ groups: [] });
    await mount();
    await search();
    expect(screen.getByText("No packages found.")).toBeTruthy();
  });
});

// ------------------------------------------------------------ CHK-M5-262

describe("CHK-M5-262 the generated client knows both package routes", () => {
  it("type level", () => {
    expectTypeOf<UserPathsArePrefixed>().toEqualTypeOf<true>();
    expectTypeOf<paths>().toHaveProperty("/api/v1/packages/search");
    expectTypeOf<paths>().toHaveProperty("/api/v1/packages/search.csv");
    type Q = NonNullable<
      paths["/api/v1/packages/search"]["get"]["parameters"]["query"]
    >;
    expectTypeOf<keyof Q>().toEqualTypeOf<
      | "q"
      | "name"
      | "version"
      | "version_op"
      | "arch"
      | "status"
      | "os"
      | "tag"
      | "host"
      | "agent_id"
      | "group_by"
      | "limit"
      | "cursor"
    >();
    type C = NonNullable<
      paths["/api/v1/packages/search.csv"]["get"]["parameters"]["query"]
    >;
    expectTypeOf<keyof C>().toEqualTypeOf<
      Exclude<keyof Q, "limit" | "cursor">
    >();
    expectTypeOf<NonNullable<Q["version_op"]>>().toEqualTypeOf<
      "lt" | "le" | "eq" | "ge" | "gt"
    >();
    expectTypeOf<NonNullable<Q["group_by"]>>().toEqualTypeOf<
      "package" | "host"
    >();
  });
});

// ------------------------------------------------------------ CHK-M5-263

describe("CHK-M5-263 version and host click-through", () => {
  it("a version click after a plain search sends exactly name, version, arch (+ limit)", async () => {
    searchServer();
    await mount();
    await search();
    fireEvent.click(
      within(screen.getByRole("region", { name: "openssl" })).getByRole(
        "button",
        {
          name: "3.0.13-0ubuntu3.5",
        },
      ),
    );
    await settle();
    expect(lastSearch()).toEqual({
      name: "openssl",
      version: "3.0.13-0ubuntu3.5",
      arch: "amd64",
      limit: "50",
    });
    const table = screen.getByRole("table", {
      name: "Hosts with this version",
    });
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((r) =>
          Array.from(r.querySelectorAll("td")).map((c) => c.textContent),
        ),
    ).toEqual([
      [
        "web-01",
        "openssl",
        "3.0.13-0ubuntu3.5",
        "amd64",
        "install ok installed",
      ],
      ["web-02", "openssl", "3.0.13-0ubuntu3.5", "amd64", "hold ok installed"],
    ]);
  });

  it("after a filtered search it also carries status, os, tag, host and agent_id, not q or version_op", async () => {
    searchServer();
    await mount();
    type("Name contains (q, 3 or more characters)", "ssl");
    type("Version", "3.0");
    choose("Version comparison", "ge");
    type("Architecture", "i386");
    choose("Status", "any");
    type("OS (for example ubuntu:24.04)", "ubuntu");
    type("Host tag", "db");
    type("Hostname contains", "web");
    type("Agent id", A2);
    await search();
    fireEvent.click(
      within(screen.getByRole("region", { name: "openssl-doc" })).getByRole(
        "button",
        {
          name: "3.0.13-0ubuntu3.5",
        },
      ),
    );
    await settle();
    expect(lastSearch()).toEqual({
      name: "openssl-doc",
      version: "3.0.13-0ubuntu3.5",
      arch: "all",
      status: "any",
      os: "ubuntu",
      tag: "db",
      host: "web",
      agent_id: A2,
      limit: "50",
    });
  });

  it("Back to results re-runs the search from page 1", async () => {
    searchServer();
    await mount();
    await search();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "3.0.13-0ubuntu3.5",
      })[0] as HTMLElement,
    );
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Back to results" }));
    await settle();
    expect(lastSearch()).toEqual({ group_by: "package", limit: "50" });
    expect(screen.getAllByRole("region")).toHaveLength(2);
  });

  it("a host click navigates to the host (rows and host views)", async () => {
    searchServer();
    const navigate = vi.fn();
    await mount(navigate);
    await search();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "3.0.13-0ubuntu3.5",
      })[0] as HTMLElement,
    );
    await settle();
    const link = screen.getByRole("link", { name: "web-02" });
    expect(link.getAttribute("href")).toBe("#/hosts/" + A2);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(navigate).toHaveBeenCalledWith({ name: "host", agentId: A2 });
    choose("View", "host");
    await search();
    fireEvent.click(screen.getByRole("link", { name: "db-01" }));
    expect(navigate).toHaveBeenLastCalledWith({ name: "host", agentId: A2 });
  });
});

// ------------------------------------------------------------ CHK-M5-264

describe("CHK-M5-264 hostile text", () => {
  it("package names, versions and hostnames render as text", async () => {
    searchServer({
      groups: [
        { name: SCRIPT, version: IMG, architecture: SCRIPT, host_count: 1 },
      ],
      rows: [
        { ...(ROWS[0] as Row), name: SCRIPT, hostname: IMG, status: SCRIPT },
      ],
    });
    const { container } = await mount();
    await search();
    expect(screen.getByRole("region", { name: SCRIPT })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: IMG }));
    await settle();
    expect(screen.getByRole("link", { name: IMG })).toBeTruthy();
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M5-265

describe("CHK-M5-265 paging and the per-host view", () => {
  it("each group once across pages, with the returned cursor", async () => {
    searchServer({ pageSize: 2 });
    await mount();
    await search();
    const versions = (): string[] =>
      screen.getAllByRole("region").flatMap((s) =>
        within(s)
          .getAllByRole("button")
          .map(
            (b) =>
              (s.getAttribute("aria-label") ?? "") +
              "@" +
              (b.textContent ?? ""),
          ),
      );
    const first = versions();
    expect(first).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(lastSearch()).toEqual({
      group_by: "package",
      limit: "50",
      cursor: "s-2",
    });
    const second = versions();
    expect(second).toEqual(["openssl-doc@3.0.13-0ubuntu3.5"]);
    expect(new Set([...first, ...second]).size).toBe(3);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(versions()).toEqual(first);
  });

  it("group_by=host renders the host table", async () => {
    searchServer();
    await mount();
    choose("View", "host");
    await search();
    expect(lastSearch()).toEqual({ group_by: "host", limit: "50" });
    const table = screen.getByRole("table", { name: "Hosts" });
    expect(
      within(table)
        .getAllByRole("row")
        .map((r) =>
          Array.from(r.querySelectorAll("th, td")).map((c) => c.textContent),
        ),
    ).toEqual([
      ["Host", "Matching packages"],
      ["web-01", "3"],
      ["db-01", "1"],
    ]);
  });

  it("a new search after paging starts at page 1", async () => {
    searchServer({ pageSize: 2 });
    await mount();
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    type("Architecture", "amd64");
    await search();
    expect(lastSearch()).toEqual({
      arch: "amd64",
      group_by: "package",
      limit: "50",
    });
  });
});

// ------------------------------------------- CHK-M5-274 / -276 (TASK-125)

describe("CHK-M5-274 Export CSV sends the visible search through the client", () => {
  function stubSaving(): { saved: Blob[]; revoked: string[] } {
    const saved: Blob[] = [];
    const revoked: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: (b: Blob) => {
        saved.push(b);
        return "blob:https://manager.test/" + String(saved.length);
      },
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: (u: string) => {
        revoked.push(u);
      },
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    return { saved, revoked };
  }

  function csvAndSearch(csvReply: () => Response): void {
    answer((call) => {
      if (call.path === CSV) {
        return csvReply();
      }
      const q = queryOf(call);
      const items = q.group_by === "package" ? GROUPS : ROWS;
      const start = q.cursor === undefined ? 0 : 2;
      return json(200, {
        items: items.slice(start, start + 2),
        next_cursor: start === 0 && items.length > 2 ? "s-2" : null,
      });
    });
  }

  it("no button before a search; after paging, the CSV query equals the search without limit or cursor", async () => {
    const { saved } = stubSaving();
    csvAndSearch(
      () =>
        new Response("name" + CRLF, {
          status: 200,
          headers: { "Content-Type": "text/csv" },
        }),
    );
    await mount();
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
    type("Architecture", "amd64");
    choose("Status", "any");
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(lastSearch().cursor).toBe("s-2");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    const csv = callsTo(CSV);
    expect(csv).toHaveLength(1);
    expect(queryOf(csv[0] as Call)).toEqual({
      arch: "amd64",
      status: "any",
      group_by: "package",
    });
    expect(csv[0]?.authorization).toBeNull();
    expect(csv[0]?.csrf).toBe("1");
    expect(saved).toHaveLength(1);
  });

  it("from a version drill-down it exports that host list's query", async () => {
    stubSaving();
    csvAndSearch(
      () =>
        new Response("x", {
          status: 200,
          headers: { "Content-Type": "text/csv" },
        }),
    );
    await mount();
    choose("Status", "any");
    await search();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "3.0.13-0ubuntu3.5",
      })[0] as HTMLElement,
    );
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    expect(queryOf(callsTo(CSV)[0] as Call)).toEqual({
      name: "openssl",
      version: "3.0.13-0ubuntu3.5",
      arch: "amd64",
      status: "any",
    });
  });

  it("CHK-M5-276 a 400 (over the cap) shows its detail; nothing is saved", async () => {
    const { saved } = stubSaving();
    csvAndSearch(() =>
      problem(
        400,
        "invalid_request",
        "Invalid request: more than 100000 rows; narrow the filters",
      ),
    );
    await mount();
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    expect(
      screen.getByText(
        "Invalid request: more than 100000 rows; narrow the filters",
      ),
    ).toBeTruthy();
    expect(saved).toHaveLength(0);
  });
});
