// TASK-247 TEST (TP-M11-14): CHK-M11-267, CHK-M11-272 (scan detail),
// plants CHK-M11-361, -362, -375 (detail).
// Expected values: REQ-280 (1)-(3); #145 (b) (detail = item + target as
// requested + hosts in API order with jobs, passed, failed, errors,
// not_run, score); #149 (score display, Not run in its own column); TS §4.5
// L603-L604; TS §6.2 L1086, L1124, L1125 (Cancel operator, Re-evaluate
// admin TOTP session); #147 (c) (rows_added); main's ruling 2026-11-08 on
// REQ-280 (3): 403 totp_session_required offers Sign in again, 503
// audit_sink_unavailable shows its fixed text with NO sign-in button, never
// an API-token field, and neither sends another request.
import {
  answer,
  bsu,
  calls,
  json,
  loginResponse,
  problem,
  resetHttp,
  watchSecrets,
  type Call,
  type Handler,
} from "../test/harness";
import {
  IMG,
  SCAN,
  SCRIPT,
  at,
  detail,
  host,
  mockLinks,
  noInjectedMarkup,
  settle,
  uuid,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { formatHash } from "../app/router";
import { clearSession, setSession, type Role } from "../app/session";
import { formatTime } from "../format";
import { ScanDetail } from "./ScanDetail";

const GET = "/api/v1/scans/" + SCAN;
const REEVAL = GET + "/reevaluate";
const CANCEL = GET + "/cancel";
const TOTP_TEXT =
  "This action needs a sign-in with your TOTP code. Sign in again with your password and code.";
const SINK_TEXT =
  "Sensitive actions are paused while the audit log cannot be shipped. Try again later.";

const REEVAL_OK = {
  scan_id: SCAN,
  policy_id: 7,
  scan_policy_version: 3,
  policy_version: 4,
  rows_added: 17,
  not_in_version: 1,
};

/** GET answered with `value()` each time; POSTs by `post`. */
function server(
  value: () => unknown = () => detail(),
  post: Handler = () => json(599, { type: "unexpected" }),
): void {
  answer((call) => {
    if (call.method === "GET" && call.path === GET) return json(200, value());
    if (call.method === "POST") return post(call);
    return json(599, { type: "unexpected" });
  });
}

async function mount(role: Role) {
  setSession(loginResponse(role, true, bsu("A")));
  const view = render(
    <ScanDetail scanId={SCAN} role={role} links={mockLinks()} />,
  );
  await settle();
  return view;
}

function sent(): string[] {
  return calls.map((c: Call) => c.method + " " + c.path);
}

function hostRows(): string[][] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((r) =>
      Array.from(r.querySelectorAll("td")).map((td) =>
        (td.textContent ?? "").replace(/\s+/g, " ").trim(),
      ),
    );
}

/** The <dd> of the field labelled `label`. */
function field(label: string): string {
  const dt = screen.getAllByRole("term").find((d) => d.textContent === label);
  return dt?.nextElementSibling?.textContent ?? "(missing)";
}

async function confirm(label: string): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: label }));
  const dialog = screen.getByRole("alertdialog", { name: label });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
  await settle();
}

beforeEach(() => {
  resetHttp();
});
afterEach(() => {
  clearSession();
});

describe("CHK-M11-267 the summary (REQ-280 (1))", () => {
  it("shows state, profile, version, trigger, target and times as given", async () => {
    server(() =>
      detail({
        state: "partial",
        policy_version: 3,
        trigger: "scheduled",
        schedule_id: 12,
        requested_by: null,
        target: { tags: ["prod-web"] },
        resolved_count: 4,
        finished_at: null,
      }),
    );
    const view = await mount("viewer");
    const text = (view.container.textContent ?? "").replace(/\s+/g, " ");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "CIS Ubuntu 24.04 0",
    );
    expect(text).toContain("Partial");
    expect(field("Profile")).toBe("CIS Ubuntu 24.04 0");
    expect(field("Profile version")).toBe("3");
    expect(field("Trigger")).toBe("Scheduled");
    expect(field("Schedule")).toBe("12");
    expect(field("Requested by (user id)")).toBe("system");
    expect(field("Target")).toBe("Hosts with any of the tags: prod-web");
    expect(field("Hosts targeted")).toBe("4");
    expect(field("Created")).toBe(formatTime("2026-11-01T10:00:00Z"));
    expect(field("Finished")).toBe("not finished");
  });

  it("the state shown is scan.state as returned, never re-derived from jobs", async () => {
    // Every job completed, but the scan says cancelled: the screen says cancelled.
    server(() => detail({ state: "cancelled" }));
    await mount("viewer");
    expect(screen.getByText("Cancelled")).toBeTruthy();
    expect(screen.queryByText("Completed")).toBeNull();
  });

  it("per-host rows in API order: host, jobs, passed, failed, not run, score with errors beside", async () => {
    server(() =>
      detail({
        hosts: [
          host(2, { hostname: "web-2" }),
          host(1, {
            hostname: "db-1",
            passed: 0,
            failed: 0,
            errors: 1,
            not_run: 7,
            score: null,
            jobs: [
              { ...at(host(1).jobs, 0), state: "expired" },
              {
                ...at(host(1).jobs, 0),
                job_id: uuid(6001),
                retry_of: uuid(5001),
                state: "running",
              },
            ],
          }),
          host(3, { hostname: "app-3", score: 0.9996, errors: 0 }),
        ],
      }),
    );
    await mount("viewer");
    expect(hostRows()).toEqual([
      ["web-2", "completed", "3", "1", "2", "75.0 % 5 errors"],
      ["db-1", "expired, retry running", "0", "0", "7", "n/a 1 error"],
      ["app-3", "completed", "3", "1", "2", "99.9 % 0 errors"],
    ]);
  });

  it("the host name links to the host page; Results links to the results screen", async () => {
    server();
    await mount("viewer");
    expect(
      screen.getByRole("link", { name: "host-1" }).getAttribute("href"),
    ).toBe(formatHash({ name: "host", agentId: uuid(1) }));
    expect(
      screen.getByRole("link", { name: "Results" }).getAttribute("href"),
    ).toBe("#/test-results/" + SCAN);
    expect(
      screen.getByRole("link", { name: "Back to scans" }).getAttribute("href"),
    ).toBe("#/test-scans");
  });

  it("no hosts: says so", async () => {
    server(() => detail({ hosts: [] }));
    await mount("viewer");
    expect(screen.getByText("No host has a job in this scan.")).toBeTruthy();
  });

  it("404 says Scan not found.", async () => {
    answer(() => problem(404, "not_found", "Not found."));
    await mount("viewer");
    expect(screen.getByRole("alert").textContent).toBe("Scan not found.");
  });

  it("another refusal shows the banner; a network failure says unavailable", async () => {
    answer(() => problem(400, "invalid_request", "Invalid request: id"));
    await mount("viewer");
    expect(screen.getByRole("alert").textContent).toContain(
      "Invalid request: id",
    );
    clearSession();
    resetHttp();
    answer(() => Promise.reject(new TypeError("down")));
    await mount("viewer");
    expect(screen.getAllByRole("alert").at(-1)?.textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });
});

describe("CHK-M11-267 buttons by role (REQ-280 (2))", () => {
  const cases: [Role, string[]][] = [
    ["viewer", []],
    ["operator", ["Cancel scan"]],
    ["admin", ["Cancel scan", "Re-evaluate"]],
  ];
  for (const [role, buttons] of cases) {
    it(
      role + " on an unfinished scan: " + (buttons.join(", ") || "none"),
      async () => {
        server(() => detail({ finished_at: null, state: "running" }));
        await mount(role);
        const offered = screen
          .queryAllByRole("button")
          .map((b) => b.textContent)
          .filter((t) => t === "Cancel scan" || t === "Re-evaluate");
        expect(offered).toEqual(buttons);
      },
    );
  }

  it("a finished scan: Cancel is not offered, Re-evaluate still is (admin)", async () => {
    server(() => detail({ finished_at: "2026-11-01T10:05:00Z" }));
    await mount("admin");
    expect(screen.queryByRole("button", { name: "Cancel scan" })).toBeNull();
    expect(screen.getByRole("button", { name: "Re-evaluate" })).toBeTruthy();
  });
});

describe("CHK-M11-267 confirm, then act (REQ-280 (3))", () => {
  it("Re-evaluate asks first; Cancel in the question sends nothing", async () => {
    server(undefined, () => json(200, REEVAL_OK));
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
    const dialog = screen.getByRole("alertdialog", { name: "Re-evaluate" });
    expect(sent()).toEqual(["GET " + GET]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await settle();
    expect(sent()).toEqual(["GET " + GET]);
  });

  it("Re-evaluate 200: one POST with no body, shows rows_added, reloads the summary", async () => {
    let version = 3;
    server(
      () => detail({ policy_version: version }),
      () => {
        version = 4;
        return json(200, REEVAL_OK);
      },
    );
    await mount("admin");
    await confirm("Re-evaluate");
    expect(sent()).toEqual(["GET " + GET, "POST " + REEVAL, "GET " + GET]);
    const post = at(calls, 1);
    expect(post.body).toBe("");
    expect(post.authorization).toBeNull();
    expect(post.csrf).toBe("1");
    expect(screen.getByRole("status").textContent).toBe(
      "Re-evaluated against version 4: 17 verdicts added.",
    );
    expect(field("Profile version")).toBe("4");
  });

  it("Cancel 200 shows the count and reloads", async () => {
    server(
      () => detail({ finished_at: null, state: "running" }),
      () => json(200, { scan_id: SCAN, state: "cancelled", cancelled_jobs: 2 }),
    );
    await mount("operator");
    await confirm("Cancel scan");
    expect(sent()).toEqual(["GET " + GET, "POST " + CANCEL, "GET " + GET]);
    expect(screen.getByRole("status").textContent).toBe(
      "Scan cancelled: 2 jobs cancelled.",
    );
  });

  it("403 totp_session_required: the sign-in-again prompt, no API-token field, no other request (plant CHK-M11-362)", async () => {
    const watch = watchSecrets();
    server(undefined, () => problem(403, "totp_session_required"));
    const view = await mount("admin");
    await confirm("Re-evaluate");
    watch.stop();
    expect(sent()).toEqual(["GET " + GET, "POST " + REEVAL]);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(TOTP_TEXT);
    expect(
      within(alert).getByRole("button", { name: "Sign in again" }),
    ).toBeTruthy();
    expect(view.container.querySelectorAll("input, textarea")).toHaveLength(0);
    expect(view.container.textContent).not.toMatch(/API token|bsk_/);
    expect(watch.leaked(bsu("A"))).toEqual([]);
  });

  it("503 audit_sink_unavailable: its fixed text, NO sign-in button, no API-token field, no other request", async () => {
    server(undefined, () => problem(503, "audit_sink_unavailable"));
    const view = await mount("admin");
    await confirm("Re-evaluate");
    expect(sent()).toEqual(["GET " + GET, "POST " + REEVAL]);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(SINK_TEXT);
    expect(
      within(alert).queryByRole("button", { name: "Sign in again" }),
    ).toBeNull();
    expect(view.container.querySelectorAll("input, textarea")).toHaveLength(0);
    expect(view.container.textContent).not.toMatch(/API token|bsk_/);
  });

  it("409 deleted policy shows its detail and sends no other request", async () => {
    server(undefined, () => problem(409, "conflict", "The policy is deleted."));
    await mount("admin");
    await confirm("Re-evaluate");
    expect(sent()).toEqual(["GET " + GET, "POST " + REEVAL]);
    expect(screen.getByRole("alert").textContent).toContain(
      "The policy is deleted.",
    );
  });

  it("Cancel refused with 403 forbidden: banner, no reload", async () => {
    server(
      () => detail({ finished_at: null }),
      () => problem(403, "forbidden"),
    );
    await mount("operator");
    await confirm("Cancel scan");
    expect(sent()).toEqual(["GET " + GET, "POST " + CANCEL]);
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
  });
});

describe("CHK-M11-272 plain text on the scan detail (plant CHK-M11-375)", () => {
  it("<script> hostname, onerror profile name and tag render as text", async () => {
    server(() =>
      detail({
        policy_name: IMG,
        target: { tags: [SCRIPT] },
        hosts: [host(1, { hostname: SCRIPT })],
      }),
    );
    const view = await mount("admin");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(IMG);
    expect(screen.getByRole("link", { name: SCRIPT })).toBeTruthy();
    expect(view.container.textContent).toContain(
      "Hosts with any of the tags: " + SCRIPT,
    );
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});
