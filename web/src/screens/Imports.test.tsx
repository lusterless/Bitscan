// TASK-172 TEST (TP-M7-29): CHK-M7-388.
// Expected values: REQ-182 (4), (5); TS §6.2 L1106 (`GET /imports`, import
// history and errors, admin), §6.3 L1134 (cursor paging), L1141 (plain
// text); #98 (h) (every `bit_import` column, newest first by `import_id`, no
// filters); SR §3.5 (`errors` = line, element, code, message); #110.
import {
  answer,
  calls,
  callsTo,
  bsu,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession } from "../app/session";
import { Imports } from "./Imports";

const LIST = "/api/v1/imports";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const TOKEN = bsu("I");

interface Finding {
  line: number | null;
  element: string | null;
  code: string;
  message: string;
}

function row(id: number, extra: Record<string, unknown> = {}) {
  return {
    import_id: id,
    file_name: "file-" + String(id) + ".bit",
    file_sha256: "b".repeat(64),
    policy_version: 2,
    mode: "manual",
    outcome: "success",
    plugins_added: 1,
    plugins_updated: 2,
    plugins_retired: 3,
    errors: [] as Finding[],
    imported_by: 4,
    imported_at: "2026-10-28T09:08:07Z",
    ...extra,
  };
}

/** Rows newest first (the server's order), cursor paging. */
function importServer(rows: ReturnType<typeof row>[]) {
  answer((call) => {
    if (call.path !== LIST || call.method !== "GET") {
      return json(599, { type: "unexpected" });
    }
    const q = queryOf(call);
    const start = q.cursor === undefined ? 0 : Number(q.cursor.slice(1));
    const end = Math.min(start + Number(q.limit), rows.length);
    return json(200, {
      items: rows.slice(start, end),
      next_cursor: end < rows.length ? "c" + String(end) : null,
    });
  });
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("admin", true, TOKEN));
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
  const view = render(<Imports />);
  await settle();
  return view;
}

/** The main table's body rows, each cell's text (findings cell excluded). */
function cells(): string[][] {
  const main = screen.getAllByRole("table")[0] as HTMLElement;
  return [...main.querySelectorAll(":scope > tbody > tr")].map((tr) =>
    [...tr.querySelectorAll(":scope > td")]
      .slice(0, 8)
      .map((td) => td.textContent ?? ""),
  );
}

function ids(): string[] {
  return cells().map((c) => c[0] ?? "");
}

// ------------------------------------------------------------ CHK-M7-388

describe("CHK-M7-388 (a) the import history", () => {
  it("asks limit=50 with no filter and shows each column", async () => {
    importServer([
      row(3),
      row(2, {
        mode: "auto",
        outcome: "rejected",
        policy_version: null,
        plugins_added: 0,
        plugins_updated: 0,
        plugins_retired: 0,
        imported_by: null,
      }),
      row(1, { mode: "rebuild", outcome: "skipped", policy_version: null }),
    ]);
    await mount();
    expect(callsTo(LIST)).toHaveLength(1);
    expect(queryOf(callsTo(LIST)[0] as Call)).toEqual({ limit: "50" });
    expect(callsTo(LIST)[0]?.authorization).toBeNull();
    expect(callsTo(LIST)[0]?.csrf).toBe("1");
    expect(cells()).toEqual([
      [
        "3",
        "file-3.bit",
        "manual",
        "success",
        "2",
        "1 / 2 / 3",
        "user 4",
        "2026-10-28 09:08:07 UTC",
      ],
      [
        "2",
        "file-2.bit",
        "auto",
        "rejected",
        "none",
        "0 / 0 / 0",
        "server",
        "2026-10-28 09:08:07 UTC",
      ],
      [
        "1",
        "file-1.bit",
        "rebuild",
        "skipped",
        "none",
        "1 / 2 / 3",
        "user 4",
        "2026-10-28 09:08:07 UTC",
      ],
    ]);
  });

  it("keeps the server's newest-first order (no client re-sort)", async () => {
    importServer([row(10), row(30), row(20)]);
    await mount();
    expect(ids()).toEqual(["10", "30", "20"]);
  });

  it("findings: none, or a table of line, element, code and message", async () => {
    importServer([
      row(5, {
        outcome: "rejected",
        errors: [
          { line: null, element: null, code: "BIT001", message: "bad XML" },
          {
            line: 9,
            element: "Policy/PluginsGroups/Plugin[1]/Execute",
            code: "BIT102",
            message: "rm is not allowed",
          },
        ],
      }),
      row(4),
    ]);
    await mount();
    const table = screen.getByRole("table", { name: "Findings of import 5" });
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent)),
    ).toEqual([
      ["none", "file", "BIT001", "bad XML"],
      [
        "9",
        "Policy/PluginsGroups/Plugin[1]/Execute",
        "BIT102",
        "rm is not allowed",
      ],
    ]);
    expect(document.body.textContent).toContain("2 findings");
    expect(
      screen.queryByRole("table", { name: "Findings of import 4" }),
    ).toBeNull();
    const last = screen
      .getAllByRole("table")[0]
      ?.querySelectorAll(":scope > tbody > tr")[1] as HTMLElement;
    expect(last.lastElementChild?.textContent).toBe("none");
  });

  it("an empty history says so", async () => {
    importServer([]);
    await mount();
    expect(screen.getByText("No imports yet.")).toBeTruthy();
  });
});

describe("CHK-M7-388 (b) paging shows each row once (REQ-182 (4))", () => {
  it("120 rows newest first over three pages: each once, in order", async () => {
    const all = Array.from({ length: 120 }, (_, i) => row(120 - i));
    importServer(all);
    await mount();
    const seen = [...ids()];
    for (let p = 0; p < 2; p++) {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await settle();
      seen.push(...ids());
    }
    expect(seen).toEqual(all.map((r) => String(r.import_id)));
    expect(new Set(seen).size).toBe(120);
    expect(callsTo(LIST).map((c) => queryOf(c))).toEqual([
      { limit: "50" },
      { limit: "50", cursor: "c50" },
      { limit: "50", cursor: "c100" },
    ]);
    expect(
      (screen.getByRole("button", { name: "Next" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});

describe("CHK-M7-388 (c) hostile file names and messages (REQ-182 (5))", () => {
  it("render literally and create no element", async () => {
    const H = SCRIPT + IMG;
    importServer([
      row(1, {
        file_name: H,
        outcome: "rejected",
        errors: [{ line: 1, element: H, code: IMG, message: H }],
      }),
    ]);
    const { container } = await mount();
    expect(cells()[0]?.[1]).toBe(H);
    const findings = screen.getByRole("table", {
      name: "Findings of import 1",
    });
    expect(
      [...findings.querySelectorAll("tbody td")].map((td) => td.textContent),
    ).toEqual(["1", H, IMG, H]);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });
});

describe("CHK-M7-388 (d) refusals", () => {
  it("a 403 forbidden shows the role message", async () => {
    answer(() => problem(403, "forbidden"));
    await mount();
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
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
