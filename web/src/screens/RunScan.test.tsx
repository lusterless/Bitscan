// TASK-246 TEST (TP-M11-14): CHK-M11-266, CHK-M11-272 (Run scan).
// Expected values: REQ-279 (1) (an operator's submission sends
// {policy_id, target} with one Idempotency-Key; a double click sends one
// request), (2) (409 disabled and 422 no host show their detail), (3)
// (plain text); #154 (a) (profiles from GET /policies?status=enabled),
// (b) (one crypto.randomUUID() key per submission, kept while that
// submission is retried after a network error, replaced for the next; the
// button disabled while in flight), (c) (after the 202 the new scan's
// detail opens); #122 (a), (b), (f); TS §6.3 L1137.
import {
  answer,
  bsu,
  callsTo,
  deferred,
  json,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
  type Handler,
} from "../test/harness";
import {
  IMG,
  SCRIPT,
  at,
  mockLinks,
  noInjectedMarkup,
  policy,
  settle,
  uuid,
} from "../test/m11";

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession } from "../app/session";
import { RunScan } from "./RunScan";

const SCANS = "/api/v1/scans";
const POLICIES = "/api/v1/policies";
const NEW_SCAN = "9a0b1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d";
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const accepted = () =>
  json(202, { scan_id: NEW_SCAN, state: "queued", policy_version: 3, jobs: 2 });

/** Policies always answered; POST /scans by `post`. */
function server(post: Handler, policies = [policy(7), policy(8)]): void {
  answer((call) => {
    if (call.path === POLICIES)
      return json(200, { items: policies, next_cursor: null });
    if (call.path === SCANS && call.method === "POST") return post(call);
    return json(599, { type: "unexpected" });
  });
}

async function mount(policyId: string | null = null) {
  const links = mockLinks();
  const view = render(<RunScan policyId={policyId} links={links} />);
  await settle();
  return { view, links };
}

function choose(value: string): void {
  fireEvent.change(screen.getByRole("combobox", { name: "Profile" }), {
    target: { value },
  });
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Run scan" }) as HTMLButtonElement;
}

function posts(): Call[] {
  return callsTo(SCANS, "POST");
}

function keyOf(call: Call): string | null {
  return call.headers.get("Idempotency-Key");
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("operator", true, bsu("O")));
});
afterEach(() => {
  vi.restoreAllMocks();
  clearSession();
});

describe("CHK-M11-266 the profiles", () => {
  it("are the enabled ones (GET /policies?status=enabled) and render as text", async () => {
    server(accepted, [
      policy(7, { policy_name: SCRIPT }),
      policy(8, { policy_name: IMG }),
    ]);
    const { view } = await mount();
    expect(queryOf(at(callsTo(POLICIES), 0))).toMatchObject({
      status: "enabled",
    });
    const select = screen.getByRole("combobox", {
      name: "Profile",
    }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "Choose an enabled profile",
      SCRIPT,
      IMG,
    ]);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });

  it("a profile given by the profile page is preselected", async () => {
    server(accepted);
    await mount("8");
    expect(
      (screen.getByRole("combobox", { name: "Profile" }) as HTMLSelectElement)
        .value,
    ).toBe("8");
  });
});

describe("CHK-M11-266 a submission", () => {
  it("sends {policy_id, target} with one UUID Idempotency-Key and opens the new scan", async () => {
    server(accepted);
    const { links } = await mount();
    choose("7");
    fireEvent.click(submitButton());
    await settle();
    expect(posts()).toHaveLength(1);
    const call = at(posts(), 0);
    expect(JSON.parse(call.body)).toEqual({
      policy_id: 7,
      target: { all: true },
    });
    expect(call.authorization).toBeNull();
    expect(call.csrf).toBe("1");
    expect(keyOf(call)).toMatch(UUID_RE);
    expect(links.opened).toEqual([NEW_SCAN]);
  });

  it("a tags target and a chosen-hosts target are sent as #122 (b) bodies", async () => {
    server(accepted);
    await mount("7");
    fireEvent.click(
      screen.getByRole("radio", { name: "Hosts with any of these tags" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: /Tags/ }), {
      target: { value: "prod-web, db" },
    });
    fireEvent.click(submitButton());
    await settle();
    expect(JSON.parse(at(posts(), 0).body)).toEqual({
      policy_id: 7,
      target: { tags: ["prod-web", "db"] },
    });
  });

  it("a double click sends one request; the button is disabled while in flight", async () => {
    const pending = deferred();
    server(() => pending.promise);
    const { links } = await mount("7");
    fireEvent.click(submitButton());
    fireEvent.click(submitButton());
    fireEvent.submit(screen.getByRole("form", { name: "Run scan" }));
    await settle();
    expect(posts()).toHaveLength(1);
    expect(submitButton().disabled).toBe(true);
    pending.resolve(accepted());
    await settle();
    expect(posts()).toHaveLength(1);
    expect(submitButton().disabled).toBe(false);
    expect(links.opened).toEqual([NEW_SCAN]);
  });

  it("no profile chosen: refused before sending", async () => {
    server(accepted);
    await mount();
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "Choose an enabled profile.",
    );
    expect(posts()).toHaveLength(0);
  });

  it("a preselected profile that is not enabled is refused before sending", async () => {
    server(accepted);
    await mount("99");
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "Choose an enabled profile.",
    );
    expect(posts()).toHaveLength(0);
  });

  it("a bad tag is refused before sending (#68 rule)", async () => {
    server(accepted);
    await mount("7");
    fireEvent.click(
      screen.getByRole("radio", { name: "Hosts with any of these tags" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: /Tags/ }), {
      target: { value: "<script>" },
    });
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "Tags are 1 to 32 names",
    );
    expect(posts()).toHaveLength(0);
  });

  it("These hosts with nothing chosen is refused before sending", async () => {
    answer((call) =>
      call.path === "/api/v1/agents"
        ? json(200, { items: [], next_cursor: null })
        : call.path === POLICIES
          ? json(200, { items: [policy(7)], next_cursor: null })
          : accepted(),
    );
    await mount("7");
    fireEvent.click(screen.getByRole("radio", { name: "These hosts" }));
    await settle();
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "Choose at least one host.",
    );
    expect(posts()).toHaveLength(0);
  });
});

describe("CHK-M11-266 the Idempotency-Key across retries (#154 (b))", () => {
  it("kept after a network error, replaced after an answer", async () => {
    let n = 0;
    server(() => {
      n += 1;
      if (n === 1) return Promise.reject(new TypeError("network down"));
      if (n === 2) return problem(409, "conflict", "The policy is disabled.");
      return accepted();
    });
    await mount("7");
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager could not be reached. Submit again to retry.",
    );
    fireEvent.click(submitButton()); // the retry of the same submission
    await settle();
    fireEvent.click(submitButton()); // a new submission after an answer
    await settle();
    const keys = posts().map(keyOf);
    expect(keys).toHaveLength(3);
    expect(keys[0]).toMatch(UUID_RE);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).toMatch(UUID_RE);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("two successful submissions use two keys", async () => {
    server(accepted);
    await mount("7");
    fireEvent.click(submitButton());
    await settle();
    fireEvent.click(submitButton());
    await settle();
    const keys = posts().map(keyOf);
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("changing the profile after a network error starts a new submission (new key)", async () => {
    let n = 0;
    server(() => {
      n += 1;
      return n === 1 ? Promise.reject(new TypeError("down")) : accepted();
    });
    await mount("7");
    fireEvent.click(submitButton());
    await settle();
    choose("8");
    fireEvent.click(submitButton());
    await settle();
    const keys = posts().map(keyOf);
    expect(keys[1]).not.toBe(keys[0]);
    expect(JSON.parse(at(posts(), 1).body)).toMatchObject({ policy_id: 8 });
  });

  it("the key comes from crypto.randomUUID", async () => {
    const spy = vi
      .spyOn(crypto, "randomUUID")
      .mockReturnValue("11111111-2222-4333-8444-555555555555");
    server(accepted);
    await mount("7");
    fireEvent.click(submitButton());
    await settle();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(keyOf(at(posts(), 0))).toBe("11111111-2222-4333-8444-555555555555");
  });
});

describe("CHK-M11-266 refusals show their detail (REQ-279 (2))", () => {
  it("409 disabled", async () => {
    server(() => problem(409, "conflict", "The policy is disabled."));
    const { links } = await mount("7");
    fireEvent.click(submitButton());
    await settle();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Request failed (status 409).");
    expect(alert.textContent).toContain("The policy is disabled.");
    expect(links.opened).toEqual([]);
  });

  it("422 no host, with a hostile detail kept as text", async () => {
    server(() =>
      problem(422, "about:blank", "No agent matches the target. " + SCRIPT),
    );
    const { view, links } = await mount("7");
    fireEvent.click(submitButton());
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "No agent matches the target. " + SCRIPT,
    );
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
    expect(links.opened).toEqual([]);
  });
});

describe("CHK-M11-272 the Run scan screen", () => {
  it("links back to the scans list", async () => {
    server(accepted);
    await mount();
    expect(
      screen.getByRole("link", { name: "Back to scans" }).getAttribute("href"),
    ).toBe("#/test-scans");
  });

  it("chosen hosts with <script> names are text and their ids are sent", async () => {
    answer((call) => {
      if (call.path === "/api/v1/agents")
        return json(200, {
          items: [
            {
              agent_id: uuid(1),
              hostname: SCRIPT,
              status: "online",
              os_id: "ubuntu",
              os_version_id: "24.04",
              os_pretty_name: "U",
              agent_version: "0.2.0",
              last_heartbeat_at: null,
              last_inventory_at: null,
              tags: [],
              runner_helpers: [],
            },
          ],
          next_cursor: null,
        });
      if (call.path === POLICIES)
        return json(200, { items: [policy(7)], next_cursor: null });
      return accepted();
    });
    const { view } = await mount("7");
    fireEvent.click(screen.getByRole("radio", { name: "These hosts" }));
    await settle();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(submitButton());
    await settle();
    expect(JSON.parse(at(posts(), 0).body)).toEqual({
      policy_id: 7,
      target: { agents: [uuid(1)] },
    });
    expect(view.container.textContent).toContain(SCRIPT);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
  });
});
