// TASK-248 TEST (TP-M11-14): CHK-M11-268, CHK-M11-272 (results), plants
// CHK-M11-360, -365 (screen half), -375, -376.
// Expected values: REQ-281 (1) (a re-evaluated row shows both verdicts,
// another row one, a null result "Not run"), (2) (items without stdout show
// no output column; with it, the text is in a <pre> text node; a stdout
// <img src=x onerror=alert(1)> renders as text), (3) (Export calls
// /api/v1/scans/{id}/results.csv with the current filters and saves the
// blob as scan-<id>-results.csv); #144 (b) (viewer items have no stdout or
// stderr key), (d) (status PASS, FAIL, ERROR, NOT_RUN; agent_id), (e)
// (limit, cursor); TS §6.2 L1083; TS §6.3 L1143.
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
  SCAN,
  SCRIPT,
  at,
  detail,
  host,
  noInjectedMarkup,
  mockLinks,
  pageOf,
  resultItem,
  settle,
  uuid,
  withOutput,
  type ResultItem,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession } from "../app/session";
import { ScanResults } from "./ScanResults";

const RESULTS = "/api/v1/scans/" + SCAN + "/results";
const CSV = RESULTS + ".csv";
const DETAIL = "/api/v1/scans/" + SCAN;
const CR = String.fromCharCode(13);
const LF = String.fromCharCode(10);

function server(items: readonly unknown[], csv?: () => Response): void {
  answer((call) => {
    if (call.path === DETAIL)
      return json(
        200,
        detail({ hosts: [host(1), host(2, { hostname: SCRIPT })] }),
      );
    if (call.path === RESULTS) {
      const q = queryOf(call);
      return json(200, pageOf(items, q.cursor, Number(q.limit)));
    }
    if (call.path === CSV && csv !== undefined) return csv();
    return json(599, { type: "unexpected" });
  });
}

async function mount() {
  const view = render(<ScanResults scanId={SCAN} links={mockLinks()} />);
  await settle();
  return view;
}

function headers(): string[] {
  return screen.getAllByRole("columnheader").map((h) => h.textContent ?? "");
}

function rows(): HTMLElement[] {
  return screen.getAllByRole("row").slice(1);
}

function badgeLabels(row: HTMLElement): string[] {
  return Array.from(row.querySelectorAll(".badge")).map(
    (b) => b.textContent ?? "",
  );
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("operator", true, bsu("O")));
});
afterEach(() => {
  vi.restoreAllMocks();
  clearSession();
});

describe("CHK-M11-268 verdicts (REQ-281 (1); plant CHK-M11-365)", () => {
  it("re-evaluated row shows both, another row one, a null result Not run", async () => {
    server([
      resultItem(1, {
        result: "PASS",
        original_result: "FAIL",
        eval_detail: null,
        original_eval_detail: null,
        reevaluated_at: "2026-11-05T00:00:00Z",
        reeval_policy_version: 4,
        reevaluated_by: 1,
      }),
      resultItem(2, { result: "FAIL", original_result: "FAIL" }),
      resultItem(3, {
        result: null,
        original_result: null,
        job_id: null,
        exit_code: null,
        timed_out: null,
        truncated: null,
        started_at: null,
        finished_at: null,
        received_at: null,
      }),
    ]);
    await mount();
    const [r1, r2, r3] = [at(rows(), 0), at(rows(), 1), at(rows(), 2)];
    expect(badgeLabels(r1)).toEqual(["PASS", "FAIL"]);
    expect(r1.textContent).toContain("original");
    expect(badgeLabels(r2)).toEqual(["FAIL"]);
    expect(badgeLabels(r3)).toEqual(["Not run"]);
  });

  it("re-evaluated with the same verdict still shows both", async () => {
    server([
      resultItem(1, {
        result: "ERROR",
        original_result: "ERROR",
        eval_detail: "stdout not numeric",
        original_eval_detail: "stdout truncated",
        reevaluated_at: "2026-11-05T00:00:00Z",
      }),
    ]);
    await mount();
    const row = at(rows(), 0);
    expect(badgeLabels(row)).toEqual(["ERROR", "ERROR"]);
    expect(row.textContent).toContain("stdout not numeric");
    expect(row.textContent).toContain("Original: stdout truncated");
  });

  it("each row names host and plugin, and the plugin name comes from the item", async () => {
    server([resultItem(1, { plugin_name: "CIS - 5.2.1 sshd root login" })]);
    await mount();
    const cells = Array.from(at(rows(), 0).querySelectorAll("td")).map(
      (td) => td.textContent,
    );
    expect(cells[0]).toBe("host-1");
    expect(cells[1]).toBe("CIS - 5.2.1 sshd root login");
  });
});

describe("CHK-M11-268 output only when present (REQ-281 (2); plants CHK-M11-360, -376)", () => {
  it("viewer items (no stdout key) give no Output column and no <pre>", async () => {
    server([resultItem(1), resultItem(2)]);
    const view = await mount();
    expect(headers()).toEqual([
      "Host",
      "Plugin",
      "Result",
      "Detail",
      "Exit code",
      "Flags",
      "Finished",
    ]);
    expect(view.container.querySelectorAll("pre, details")).toHaveLength(0);
    for (const row of rows()) {
      expect(row.querySelectorAll("td")).toHaveLength(7);
    }
  });

  it("operator items: an Output column; stdout and stderr are single text nodes in <pre>", async () => {
    server([
      withOutput(
        resultItem(1),
        "PermitRootLogin no" + LF + "x",
        "warn" + CR + LF,
      ),
      withOutput(resultItem(2), null, null),
    ]);
    await mount();
    expect(headers().at(-1)).toBe("Output");
    const pres = Array.from(at(rows(), 0).querySelectorAll("pre"));
    expect(pres).toHaveLength(2);
    for (const pre of pres) {
      expect(pre.childNodes).toHaveLength(1);
      expect(pre.firstChild?.nodeType).toBe(Node.TEXT_NODE);
    }
    expect(pres.map((p) => p.textContent)).toEqual([
      "PermitRootLogin no" + LF + "x",
      "warn" + CR + LF,
    ]);
    // A null stdout is an empty <pre>, not the text "null".
    const nulls = Array.from(at(rows(), 1).querySelectorAll("pre")).map(
      (p) => p.textContent,
    );
    expect(nulls).toEqual(["", ""]);
  });

  it("an onerror stdout and a <script> stderr render as text", async () => {
    server([withOutput(resultItem(1), IMG, SCRIPT)]);
    const view = await mount();
    const pres = Array.from(at(rows(), 0).querySelectorAll("pre"));
    expect(pres.map((p) => p.textContent)).toEqual([IMG, SCRIPT]);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});

describe("CHK-M11-268 filters and paging", () => {
  it("status and host filters send status and agent_id; Not run is NOT_RUN; All sends nothing", async () => {
    server([resultItem(1)]);
    await mount();
    expect(queryOf(at(callsTo(RESULTS), 0))).toEqual({ limit: "50" });
    const status = screen.getByRole("combobox", { name: "Status" });
    fireEvent.change(status, { target: { value: "FAIL" } });
    await settle();
    expect(queryOf(at(callsTo(RESULTS), 1))).toEqual({
      limit: "50",
      status: "FAIL",
    });
    const hostSelect = screen.getByRole("combobox", {
      name: "Host",
    }) as HTMLSelectElement;
    expect(Array.from(hostSelect.options).map((o) => o.textContent)).toEqual([
      "All",
      "host-1",
      SCRIPT,
    ]);
    fireEvent.change(hostSelect, { target: { value: uuid(2) } });
    await settle();
    expect(queryOf(at(callsTo(RESULTS), 2))).toEqual({
      limit: "50",
      status: "FAIL",
      agent_id: uuid(2),
    });
    fireEvent.change(status, { target: { value: "NOT_RUN" } });
    await settle();
    expect(queryOf(at(callsTo(RESULTS), 3))).toMatchObject({
      status: "NOT_RUN",
    });
    fireEvent.change(status, { target: { value: "" } });
    fireEvent.change(hostSelect, { target: { value: "" } });
    await settle();
    expect(queryOf(at(callsTo(RESULTS), callsTo(RESULTS).length - 1))).toEqual({
      limit: "50",
    });
  });

  it("51 results: Next sends the cursor; a filter change returns to page 1", async () => {
    const items: ResultItem[] = Array.from({ length: 51 }, (_, i) =>
      resultItem(i),
    );
    server(items);
    await mount();
    expect(rows()).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(at(callsTo(RESULTS), 1))).toEqual({
      limit: "50",
      cursor: "p-50",
    });
    expect(rows()).toHaveLength(1);
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
      target: { value: "PASS" },
    });
    await settle();
    expect(queryOf(at(callsTo(RESULTS), 2))).toEqual({
      limit: "50",
      status: "PASS",
    });
  });

  it("empty: No results.; a refusal: the banner", async () => {
    server([]);
    await mount();
    expect(screen.getByText("No results.")).toBeTruthy();
  });

  it("a 404 for the results shows the banner", async () => {
    answer((call) =>
      call.path === RESULTS
        ? problem(404, "not_found", "Not found.")
        : problem(404, "not_found"),
    );
    await mount();
    expect(screen.getByRole("alert").textContent).toContain("Not found.");
  });
});

function stubSaving(): { names: string[]; blobs: Blob[] } {
  const saved = { names: [] as string[], blobs: [] as Blob[] };
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (b: Blob) => {
      saved.blobs.push(b);
      return "blob:https://manager.test/1";
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined,
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.names.push(this.download);
  });
  return saved;
}

describe("CHK-M11-268 Export CSV (REQ-281 (3))", () => {
  it("calls results.csv with the current filters through the client and saves scan-<id>-results.csv", async () => {
    const saved = stubSaving();
    server(
      [resultItem(1)],
      () =>
        new Response("hostname" + CR + LF, {
          status: 200,
          headers: { "Content-Type": "text/csv; charset=utf-8" },
        }),
    );
    await mount();
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
      target: { value: "ERROR" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Host" }), {
      target: { value: uuid(1) },
    });
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    const call = at(callsTo(CSV), 0);
    expect(queryOf(call)).toEqual({ status: "ERROR", agent_id: uuid(1) });
    expect(call.authorization).toBe("Bearer " + bsu("O"));
    expect(saved.names).toEqual(["scan-" + SCAN + "-results.csv"]);
    expect(saved.blobs).toHaveLength(1);
  });

  it("without filters the export sends no query", async () => {
    stubSaving();
    server([resultItem(1)], () => new Response("h" + CR + LF, { status: 200 }));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    expect(at(callsTo(CSV), 0).url).toBe(CSV);
  });

  it("the 100,000-row refusal shows its detail and saves nothing", async () => {
    const saved = stubSaving();
    const detailText =
      "Invalid request: more than 100000 rows; narrow the filters";
    server([resultItem(1)], () => problem(400, "invalid_request", detailText));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(detailText);
    expect(saved.names).toEqual([]);
  });
});

describe("CHK-M11-272 plain text on the results screen (plant CHK-M11-375)", () => {
  it("<script> hostname, plugin name and eval detail render as text", async () => {
    server([
      resultItem(1, {
        hostname: SCRIPT,
        plugin_name: IMG,
        result: "ERROR",
        eval_detail: SCRIPT + IMG,
      }),
    ]);
    const view = await mount();
    const cells = Array.from(at(rows(), 0).querySelectorAll("td")).map(
      (td) => td.textContent,
    );
    expect(cells[0]).toBe(SCRIPT);
    expect(cells[1]).toBe(IMG);
    expect(cells[3]).toBe(SCRIPT + IMG);
    expect(
      within(view.container)
        .getByRole("link", { name: "Back to the scan" })
        .getAttribute("href"),
    ).toBe("#/test-scan/" + SCAN);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});
