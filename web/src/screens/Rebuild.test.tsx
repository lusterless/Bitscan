// TASK-172 TEST (TP-M7-29): CHK-M7-389.
// Expected values: REQ-182 (3), (5), the TASK-172 row (a 403
// `totp_session_required` on rebuild shows the sign-in-again prompt); TS §4.2
// L540 (rebuild), §6.2 L1104-L1105 (`POST /policies/rebuild` admin + TOTP
// session, async, returns a task id; `GET /tasks/{id}`), §6.2 L1084 and the
// web-ui rule (TOTP-session actions prompt for TOTP, never for an API
// token), §6.3 L1141 (plain text); #98 (f), (g) (202 `{task_id}`; task
// states running, succeeded, failed; `result` files or `{error}`).
import {
  answer,
  bsu,
  calls,
  callsTo,
  json,
  loginResponse,
  problem,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession } from "../app/session";
import { POLL_MS, Rebuild } from "./Rebuild";

const START = "/api/v1/policies/rebuild";
const TASK = "0f8fad5b-d9cb-469f-a165-70867728950e";
const TASK_PATH = "/api/v1/tasks/" + TASK;
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const TOKEN = bsu("R");
const SIGN_IN_AGAIN =
  "This action needs a sign-in with your TOTP code. Sign in again with your password and code.";

type State = "running" | "succeeded" | "failed";

function task(state: State, result: unknown = null) {
  return {
    task_id: TASK,
    kind: "rebuild",
    state,
    requested_by: 1,
    result,
    started_at: "2026-10-28T09:00:00Z",
    finished_at: state === "running" ? null : "2026-10-28T09:00:05Z",
  };
}

const RESULT = {
  files: [
    {
      source_file: "cis.bit",
      import_id: 11,
      outcome: "success",
      policy_id: 7,
      policy_version: 4,
    },
    {
      source_file: "uploaded/policy-9.bit",
      import_id: 12,
      outcome: "rejected",
      policy_id: null,
      policy_version: null,
    },
  ],
  deleted_policy_ids: [3, 5],
  plugins_retired: 6,
  removed_leftovers: ["uploaded/policy-2.bit"],
  not_imported: ["other.bit"],
};

/**
 * POST answers `start`; each GET answers the next state in `states` (the
 * last one repeats).
 */
function rebuildServer(
  states: (() => Response)[],
  start: () => Response = () => json(202, { task_id: TASK }),
) {
  let i = 0;
  answer((call) => {
    if (call.method === "POST" && call.path === START) {
      return start();
    }
    if (call.method === "GET" && call.path === TASK_PATH) {
      const next = states[Math.min(i, states.length - 1)] as () => Response;
      i++;
      return next();
    }
    return json(599, { type: "unexpected" });
  });
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("admin", true, TOKEN));
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  vi.useRealTimers();
  clearSession();
});

// Taken before any test fakes the clock, so flushing never moves it.
const realTimeout = globalThis.setTimeout.bind(globalThis);

/** Lets pending responses arrive without moving the (fake) clock. */
async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => realTimeout(r, 0));
    }
  });
}

async function tick(ms: number): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await flush();
}

async function startRebuild(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: "Rebuild" }));
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", {
      name: "Confirm",
    }),
  );
  await flush();
}

function polls(): Call[] {
  return callsTo(TASK_PATH);
}

function status(): string {
  return (
    within(screen.getByRole("region", { name: "Rebuild task" })).getByRole(
      "status",
    ).textContent ?? ""
  );
}

// ------------------------------------------------------------ CHK-M7-389

describe("CHK-M7-389 (a) start after confirmation", () => {
  it("Cancel sends nothing; Confirm sends one POST with no body", async () => {
    rebuildServer([() => json(200, task("succeeded", RESULT))]);
    render(<Rebuild />);
    fireEvent.click(screen.getByRole("button", { name: "Rebuild" }));
    expect(screen.getByRole("alertdialog").textContent).toContain(
      "Rebuild the catalog from both policy folders now?",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await flush();
    expect(calls).toHaveLength(0);
    await startRebuild();
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts.map((c) => c.path)).toEqual([START]);
    expect(posts[0]?.body).toBe("");
    expect(posts[0]?.authorization).toBe("Bearer " + TOKEN);
  });
});

describe("CHK-M7-389 (b) polling stops at succeeded or failed (REQ-182 (3))", () => {
  it("running, running, succeeded: three GETs, POLL_MS apart, then none", async () => {
    rebuildServer([
      () => json(200, task("running")),
      () => json(200, task("running")),
      () => json(200, task("succeeded", RESULT)),
    ]);
    render(<Rebuild />);
    await startRebuild();
    // the first GET follows the 202 at once
    expect(polls()).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "Task " + TASK,
    );
    expect(status()).toBe("Running.");
    expect(
      (screen.getByRole("button", { name: "Rebuild" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await tick(POLL_MS - 1);
    expect(polls()).toHaveLength(1);
    await tick(1);
    expect(polls()).toHaveLength(2);
    expect(status()).toBe("Running.");
    await tick(POLL_MS);
    expect(polls()).toHaveLength(3);
    expect(status()).toBe("Succeeded.");
    await tick(POLL_MS * 10);
    expect(polls()).toHaveLength(3);
    expect(vi.getTimerCount()).toBe(0);
    expect(
      (screen.getByRole("button", { name: "Rebuild" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("succeeded: the files and the result fields are shown", async () => {
    rebuildServer([() => json(200, task("succeeded", RESULT))]);
    render(<Rebuild />);
    await startRebuild();
    const region = screen.getByRole("region", { name: "Rebuild task" });
    expect(region.textContent).toContain(
      "Started 2026-10-28 09:00:00 UTC, finished 2026-10-28 09:00:05 UTC.",
    );
    const files = within(region).getByRole("table", { name: "Files" });
    expect(
      within(files)
        .getAllByRole("row")
        .slice(1)
        .map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent)),
    ).toEqual([
      ["cis.bit", "success", "11", "7", "4"],
      ["uploaded/policy-9.bit", "rejected", "12", "none", "none"],
    ]);
    const dl = Object.fromEntries(
      [...region.querySelectorAll("dl > div")].map((d) => [
        d.querySelector("dt")?.textContent,
        d.querySelector("dd")?.textContent,
      ]),
    );
    expect(dl).toEqual({
      Files: "2",
      "Not imported": "other.bit",
      "Deleted policies": "3, 5",
      "Plugins retired": "6",
      "Leftovers removed": "uploaded/policy-2.bit",
    });
  });

  it("running then failed: two GETs, then none; the error text is shown", async () => {
    rebuildServer([
      () => json(200, task("running")),
      () => json(200, task("failed", { error: "The rebuild failed." })),
    ]);
    render(<Rebuild />);
    await startRebuild();
    await tick(POLL_MS);
    expect(polls()).toHaveLength(2);
    expect(status()).toBe("Failed.");
    expect(
      screen.getByRole("region", { name: "Rebuild task" }).textContent,
    ).toContain("The rebuild failed.");
    expect(
      within(screen.getByRole("region", { name: "Rebuild task" })).queryByRole(
        "table",
      ),
    ).toBeNull();
    await tick(POLL_MS * 10);
    expect(polls()).toHaveLength(2);
  });

  it("a refusal while polling stops the polling and shows the banner", async () => {
    rebuildServer([
      () => json(200, task("running")),
      () => problem(404, "not_found"),
    ]);
    render(<Rebuild />);
    await startRebuild();
    await tick(POLL_MS);
    expect(polls()).toHaveLength(2);
    expect(screen.getByRole("alert").textContent).toContain(
      "Request failed (status 404).",
    );
    await tick(POLL_MS * 5);
    expect(polls()).toHaveLength(2);
  });

  it("leaving the screen stops the polling", async () => {
    rebuildServer([() => json(200, task("running"))]);
    const view = render(<Rebuild />);
    await startRebuild();
    expect(polls()).toHaveLength(1);
    view.unmount();
    await tick(POLL_MS * 5);
    expect(polls()).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("CHK-M7-389 (c) refusals of the start", () => {
  it("403 totp_session_required: the sign-in-again prompt, no API-token field, no poll", async () => {
    rebuildServer([], () => problem(403, "totp_session_required"));
    const { container } = render(<Rebuild />);
    await startRebuild();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(SIGN_IN_AGAIN);
    expect(
      within(alert).getByRole("button", { name: "Sign in again" }),
    ).toBeTruthy();
    expect(container.querySelectorAll("input, textarea, select")).toHaveLength(
      0,
    );
    expect(document.body.textContent?.toLowerCase()).not.toMatch(
      /api token|bsk_/,
    );
    expect(calls.map((c) => c.method + " " + c.path)).toEqual([
      "POST " + START,
    ]);
    expect(calls.every((c) => c.authorization === "Bearer " + TOKEN)).toBe(
      true,
    );
    expect(screen.queryByRole("region", { name: "Rebuild task" })).toBeNull();
  });

  it("503 audit_sink_unavailable: the paused message", async () => {
    rebuildServer([], () => problem(503, "audit_sink_unavailable"));
    render(<Rebuild />);
    await startRebuild();
    expect(screen.getByRole("alert").textContent).toContain(
      "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
    );
  });

  it("503 at start-up (#102 (d)): the catalog-starting message", async () => {
    const detail = "The catalog is starting; retry shortly.";
    rebuildServer([], () =>
      problem(503, "about:blank", detail, { "Retry-After": "10" }),
    );
    render(<Rebuild />);
    await startRebuild();
    expect(screen.getByRole("alert").firstChild?.textContent).toBe(detail);
  });
});

describe("CHK-M7-389 (d) hostile text (REQ-182 (5))", () => {
  it("file names, leftovers and the error render literally", async () => {
    const H = SCRIPT + IMG;
    rebuildServer([
      () =>
        json(
          200,
          task("succeeded", {
            ...RESULT,
            files: [{ ...RESULT.files[0], source_file: H }],
            removed_leftovers: [IMG],
            not_imported: [SCRIPT],
          }),
        ),
    ]);
    const { container } = render(<Rebuild />);
    await startRebuild();
    const region = screen.getByRole("region", { name: "Rebuild task" });
    expect(within(region).getByRole("table").textContent).toContain(H);
    expect(region.textContent).toContain(IMG);
    expect(region.textContent).toContain(SCRIPT);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });

  it("a hostile failure text renders literally", async () => {
    const H = IMG + SCRIPT;
    rebuildServer([() => json(200, task("failed", { error: H }))]);
    const { container } = render(<Rebuild />);
    await startRebuild();
    expect(
      screen.getByRole("region", { name: "Rebuild task" }).textContent,
    ).toContain(H);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });
});
