// TASK-170 TEST (TP-M7-29): CHK-M7-313.
// Expected values: REQ-181 (1)-(3), REQ-182 (2); TS §1.4 L41 and §4.3 L551
// (plugins as `<family name> - <plugin name>` in `.bit` order,
// `policy_plugin.sort_order`), §4.3 L548 (the admin toggle and clearing the
// override with `{"status_overridden": false}`), L550 (delete; 409
// `policy_managed_on_server`), §6.2 L1101-L1104 (GET any role; PATCH admin;
// DELETE admin + TOTP session), §6.3 L1141 (plain text); REQ-168 (the PATCH
// bodies); #98 (b), (c), (e); web-ui rule (Disabled and Deleted states; the
// UI prompts for TOTP, never for an API token).
import {
  answer,
  bsu,
  calls,
  callsTo,
  json,
  loginResponse,
  noContent,
  problem,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession, type Role } from "../app/session";
import { ProfileDetail } from "./ProfileDetail";

const ID = "7";
const PATH = "/api/v1/policies/7";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const TOKEN = bsu("D");
const FAMILY = "CIS Ubuntu 24.04";
const SIGN_IN_AGAIN =
  "This action needs a sign-in with your TOTP code. Sign in again with your password and code.";

interface Plugin {
  plugin_uuid: string;
  sort_order: number;
  display_name: string;
  plugin_name: string;
  control_ref: string | null;
  plugin_description: string;
  execute: string;
  execute_sha256: string;
  operator: string;
  expected_result: string;
  timeout_s: number;
  state: "active" | "retired";
  updated_at: string;
}

function plugin(n: number, extra: Partial<Plugin> = {}): Plugin {
  const name = "1.1." + String(n) + " - Ensure thing " + String(n);
  return {
    plugin_uuid: "00000000-0000-4000-8000-" + String(n).padStart(12, "0"),
    sort_order: n,
    display_name: FAMILY + " - " + name,
    plugin_name: name,
    control_ref: "1.1." + String(n),
    plugin_description: "Checks thing " + String(n),
    execute: "dpkg-query -W -f='${Status}' pkg" + String(n),
    execute_sha256: "a".repeat(64),
    operator: "equal",
    expected_result: "install ok installed",
    timeout_s: 30 + n,
    state: "active",
    updated_at: "2026-10-28T00:00:00Z",
    ...extra,
  };
}

function detail(extra: Record<string, unknown> = {}) {
  return {
    policy_id: 7,
    policy_name: "CIS Ubuntu 24.04 Level 1 - Server",
    policy_description: "Level 1 server checks",
    policy_status: "enabled",
    file_status: "enabled",
    status_overridden: false,
    family_id: 1,
    family_name: FAMILY,
    format_version: "1.0",
    version: 3,
    source_file: "uploaded/policy-7.bit",
    plugin_count: 3,
    imported_at: "2026-10-27T08:00:00Z",
    updated_at: "2026-10-28T09:08:07Z",
    deleted_at: null,
    // Out of order on purpose: the screen shows sort_order order.
    plugins: [plugin(2), plugin(0), plugin(1)],
    ...extra,
  };
}

/** GET answers the current detail; PATCH and DELETE go to `mutate`. */
function detailServer(
  body: () => unknown,
  mutate: (c: Call) => Response = () => noContent(),
) {
  answer((call) => {
    if (call.path !== PATH) {
      return json(599, { type: "unexpected" });
    }
    return call.method === "GET" ? json(200, body()) : mutate(call);
  });
}

const navigate = vi.fn();

beforeEach(() => {
  resetHttp();
  navigate.mockReset();
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

async function mount(role: Role = "admin"): Promise<ReturnType<typeof render>> {
  setSession(loginResponse(role, true, TOKEN));
  const view = render(
    <ProfileDetail policyId={ID} role={role} navigate={navigate} />,
  );
  await settle();
  return view;
}

function cards(): HTMLElement[] {
  return screen.getAllByRole("article");
}

function mutations(): Call[] {
  return calls.filter((c) => c.method !== "GET");
}

function buttonNames(container: HTMLElement): string[] {
  return [...container.querySelectorAll("button")].map(
    (b) => b.textContent ?? "",
  );
}

// ------------------------------------------------------------ CHK-M7-313

describe("CHK-M7-313 (a) the profile and its plugins (REQ-181 (1))", () => {
  it("GETs /policies/7 and shows the fields", async () => {
    detailServer(() => detail());
    await mount("viewer");
    expect(calls.map((c) => c.method + " " + c.path)).toEqual(["GET " + PATH]);
    expect(calls[0]?.authorization).toBe("Bearer " + TOKEN);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "CIS Ubuntu 24.04 Level 1 - Server",
    );
    expect(document.body.textContent).toContain("Level 1 server checks");
    const fields = within(
      screen.getByRole("region", { name: "Profile" }),
    ).getAllByRole("definition");
    const labels = within(screen.getByRole("region", { name: "Profile" }))
      .getAllByRole("term")
      .map((t) => t.textContent);
    expect(
      Object.fromEntries(labels.map((l, i) => [l, fields[i]?.textContent])),
    ).toEqual({
      Family: FAMILY,
      Status: "enabled",
      "Status in the file": "enabled",
      "Admin override": "no",
      Version: "3",
      "Format version": "1.0",
      "Source file": "uploaded/policy-7.bit",
      Imported: "2026-10-27 08:00:00 UTC",
      Updated: "2026-10-28 09:08:07 UTC",
      Deleted: "no",
    });
  });

  it("plugins appear as `<family name> - <plugin name>` in sort_order", async () => {
    detailServer(() => detail());
    await mount("viewer");
    expect(
      cards().map(
        (c) => within(c).getByRole("heading", { level: 3 }).textContent,
      ),
    ).toEqual(
      [0, 1, 2].map(
        (n) => FAMILY + " - 1.1." + String(n) + " - Ensure thing " + String(n),
      ),
    );
    expect(screen.getByRole("heading", { level: 2, name: "Plugins (3)" }));
  });

  it("each plugin shows its description, Execute, Operator, ExpectedResult and timeout", async () => {
    detailServer(() => detail());
    await mount("viewer");
    const first = cards()[0] as HTMLElement;
    const text = first.textContent ?? "";
    for (const part of [
      "Checks thing 0",
      "1.1.0",
      "equal",
      "install ok installed",
      "30",
      "00000000-0000-4000-8000-000000000000",
    ]) {
      expect(text).toContain(part);
    }
    expect(first.querySelector("pre")?.textContent).toBe(
      "dpkg-query -W -f='${Status}' pkg0",
    );
    const dl = Object.fromEntries(
      [...first.querySelectorAll("dl > div")].map((d) => [
        d.querySelector("dt")?.textContent,
        d.querySelector("dd")?.textContent,
      ]),
    );
    expect(dl).toEqual({
      Control: "1.1.0",
      Operator: "equal",
      "Expected result": "install ok installed",
      "Timeout (s)": "30",
      "Plugin id": "00000000-0000-4000-8000-000000000000",
    });
  });

  it("a plugin without control_ref shows none; a retired plugin is marked Retired", async () => {
    detailServer(() =>
      detail({
        plugins: [
          plugin(0, { control_ref: null }),
          plugin(1, { state: "retired" }),
        ],
      }),
    );
    await mount("viewer");
    const [a, b] = cards() as [HTMLElement, HTMLElement];
    expect(a.textContent).toContain("Controlnone");
    expect(a.textContent).not.toContain("Retired");
    expect(within(b).getByText("Retired")).toBeTruthy();
  });

  it("the Disabled state shows as such, with the override marked", async () => {
    detailServer(() =>
      detail({ policy_status: "disabled", status_overridden: true }),
    );
    await mount("viewer");
    const title = screen.getByRole("heading", { level: 1 })
      .parentElement as HTMLElement;
    expect(title.textContent).toContain("Disabled (override)");
  });

  it("a 404 shows Profile not found; a back link returns to the list", async () => {
    answer(() => problem(404, "not_found"));
    await mount("viewer");
    expect(screen.getByRole("alert").textContent).toBe("Profile not found.");
    const back = screen.getByRole("link", { name: "Back to profiles" });
    expect(back.getAttribute("href")).toBe("#/profiles");
    fireEvent.click(back);
    expect(navigate).toHaveBeenCalledWith({ name: "profiles" });
  });
});

describe("CHK-M7-313 (b) a deleted policy (REQ-181 (2))", () => {
  it.each(["admin", "operator", "viewer"] as const)(
    "%s sees Deleted and no actions",
    async (role) => {
      detailServer(() =>
        detail({
          deleted_at: "2026-10-28T10:00:00Z",
          source_file: "deleted/7",
        }),
      );
      const { container } = await mount(role);
      const title = screen.getByRole("heading", { level: 1 })
        .parentElement as HTMLElement;
      expect(title.textContent).toContain("Deleted");
      expect(title.textContent).not.toContain("Enabled");
      expect(buttonNames(container)).toEqual([]);
      expect(container.textContent).toContain("2026-10-28 10:00:00 UTC");
    },
  );
});

describe("CHK-M7-313 (c) admin status actions send exactly the REQ-168 bodies (REQ-181 (3))", () => {
  it.each([
    [
      "enabled, no override",
      { policy_status: "enabled", status_overridden: false },
      ["Disable", "Delete"],
    ],
    [
      "disabled, no override",
      { policy_status: "disabled", status_overridden: false },
      ["Enable", "Delete"],
    ],
    [
      "disabled by an override",
      { policy_status: "disabled", status_overridden: true },
      ["Enable", "Clear override", "Delete"],
    ],
    [
      "enabled by an override",
      { policy_status: "enabled", status_overridden: true },
      ["Disable", "Clear override", "Delete"],
    ],
  ])("%s offers %j", async (_n, state, want) => {
    detailServer(() => detail(state));
    const { container } = await mount("admin");
    expect(buttonNames(container)).toEqual(want);
  });

  it.each([
    [
      "Disable",
      { policy_status: "enabled" },
      { policy_status: "disabled" },
      "Profile disabled.",
    ],
    [
      "Enable",
      { policy_status: "disabled" },
      { policy_status: "enabled" },
      "Profile enabled.",
    ],
    [
      "Clear override",
      { policy_status: "disabled", status_overridden: true },
      { status_overridden: false },
      "Override cleared.",
    ],
  ])(
    "%s sends one PATCH with exactly %j",
    async (button, state, body, done) => {
      detailServer(
        () => detail(state),
        () => json(200, detail(state)),
      );
      await mount("admin");
      fireEvent.click(screen.getByRole("button", { name: button }));
      await settle();
      expect(mutations().map((c) => c.method + " " + c.path)).toEqual([
        "PATCH " + PATH,
      ]);
      const call = mutations()[0] as Call;
      expect(JSON.parse(call.body)).toStrictEqual(body);
      expect(call.contentType).toBe("application/json");
      expect(call.authorization).toBe("Bearer " + TOKEN);
      expect(screen.getByRole("status").textContent).toBe(done);
      // and the profile is read again
      expect(callsTo(PATH)).toHaveLength(2);
    },
  );

  it("a PATCH 409 conflict says the profile is deleted", async () => {
    detailServer(
      () => detail(),
      () => problem(409, "conflict"),
    );
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await settle();
    expect(screen.getByRole("status").textContent).toBe(
      "This profile is deleted.",
    );
  });

  it.each(["viewer", "operator"] as const)(
    "%s sees no action at all, even with an override set",
    async (role) => {
      detailServer(() =>
        detail({ policy_status: "disabled", status_overridden: true }),
      );
      const { container } = await mount(role);
      expect(buttonNames(container)).toEqual([]);
      expect(screen.queryByRole("button")).toBeNull();
      expect(mutations()).toEqual([]);
    },
  );
});

describe("CHK-M7-313 (d) delete (REQ-182 (2))", () => {
  it("asks for confirmation; Cancel sends nothing; Confirm sends one DELETE", async () => {
    let deleted = false;
    detailServer(
      () =>
        deleted
          ? detail({
              deleted_at: "2026-10-28T11:00:00Z",
              source_file: "deleted/7",
            })
          : detail(),
      () => {
        deleted = true;
        return noContent();
      },
    );
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete" });
    expect(dialog.textContent).toContain(
      "Delete profile CIS Ubuntu 24.04 Level 1 - Server?",
    );
    expect(mutations()).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await settle();
    expect(mutations()).toEqual([]);
    expect(screen.queryByRole("alertdialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Confirm",
      }),
    );
    await settle();
    expect(mutations().map((c) => c.method + " " + c.path)).toEqual([
      "DELETE " + PATH,
    ]);
    expect(mutations()[0]?.body).toBe("");
    expect(mutations()[0]?.authorization).toBe("Bearer " + TOKEN);
    expect(screen.getByRole("status").textContent).toBe("Profile deleted.");
    // reloaded: now Deleted, no actions
    expect(callsTo(PATH)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    const title = screen.getByRole("heading", { level: 1 })
      .parentElement as HTMLElement;
    expect(title.textContent).toContain("Deleted");
  });

  it("a 409 policy_managed_on_server shows the server-folder message", async () => {
    detailServer(
      () => detail({ source_file: "cis.bit" }),
      () => problem(409, "policy_managed_on_server", "server folder"),
    );
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(mutations()).toHaveLength(1);
    expect(screen.getByRole("alert").firstChild?.textContent).toBe(
      "This policy is managed in the server folder. Change or remove its file on the server.",
    );
  });

  it("a 403 totp_session_required shows the sign-in-again prompt and never asks for an API token", async () => {
    detailServer(
      () => detail(),
      () => problem(403, "totp_session_required"),
    );
    const { container } = await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
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
    // one DELETE, no retry with another credential
    expect(mutations()).toHaveLength(1);
    expect(calls.every((c) => c.authorization === "Bearer " + TOKEN)).toBe(
      true,
    );
  });

  it("a 503 audit_sink_unavailable shows the paused message", async () => {
    detailServer(
      () => detail(),
      () => problem(503, "audit_sink_unavailable"),
    );
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
    );
  });

  it("a DELETE 404 says Profile not found", async () => {
    detailServer(
      () => detail(),
      () => problem(404, "not_found"),
    );
    await mount("admin");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("status").textContent).toBe("Profile not found.");
  });
});

describe("CHK-M7-313 (e) hostile text renders literally (REQ-181 (1))", () => {
  it("every stored text field creates no element", async () => {
    const H = SCRIPT + IMG;
    detailServer(() =>
      detail({
        policy_name: H,
        policy_description: IMG,
        family_name: SCRIPT,
        source_file: H,
        format_version: IMG,
        plugins: [
          plugin(0, {
            display_name: H,
            plugin_name: H,
            control_ref: IMG,
            plugin_description: H,
            execute: H,
            operator: IMG,
            expected_result: H,
          }),
        ],
      }),
    );
    const { container } = await mount("admin");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(H);
    const card = cards()[0] as HTMLElement;
    expect(within(card).getByRole("heading", { level: 3 }).textContent).toBe(H);
    expect(card.querySelector("pre")?.textContent).toBe(H);
    expect(card.textContent).toContain(IMG);
    expect(container.textContent).toContain(SCRIPT);
    // the delete question quotes the name as text too
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("alertdialog").textContent).toContain(H);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });
});
