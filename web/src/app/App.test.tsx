// TASK-126 TEST (TP-M5-19): CHK-M5-280 to CHK-M5-287.
// Expected values: REQ-133 (1)-(3), REQ-120 (1)-(4), REQ-122 (1), (6),
// REQ-132 (1); TS §6.2 L1089 (an admin without TOTP can call only TOTP
// enrolment and logout; every user is offered TOTP at first sign-in), L1080
// (bsu_ in memory), L1093-L1127 (route roles); #85 (a), (c); plan TASK-116
// navigation table.
// TASK-173 TEST (TP-M7-29): CHK-M5-280 updated for REQ-183 (3) (Profiles for
// every role; Upload, Import history and Rebuild for admins, TS §6.2
// L1100-L1107), plus CHK-M7-390 (shell part), CHK-M7-392, CHK-M7-393.
import {
  answer,
  bsu,
  calls,
  json,
  loginResponse,
  noContent,
  problem,
  queryOf,
  resetHttp,
  watchSecrets,
  type Call,
  type Watch,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { clearSession, currentSession } from "./session";

const TOKEN = bsu("Z");
const PASSWORD = "App-Shell-Password-1";
const SECRET = "JBSWY3DPEHPK3PXPAPPSHELL";
const ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const H = SCRIPT + IMG;

const AGENT = {
  agent_id: ID,
  hostname: H,
  status: "online",
  os_id: "ubuntu",
  os_version_id: "24.04",
  os_pretty_name: IMG,
  agent_version: SCRIPT,
  last_heartbeat_at: null,
  last_inventory_at: null,
  tags: [H],
  runner_helpers: [IMG],
};

const DETAIL = {
  ...AGENT,
  machine_id: "a".repeat(32),
  enrolled_at: "2026-10-01T00:00:00Z",
  last_seen_ip: "10.0.0.1",
  token_issued_at: "2026-10-01T00:00:00Z",
  token_expires_at: "2026-12-01T00:00:00Z",
  token_revoked_at: null,
  os_info: {
    os_id: "ubuntu",
    os_version_id: "24.04",
    os_pretty_name: H,
    kernel_release: IMG,
    architecture: "amd64",
    cpu_count: 2,
    memory_mb: 1,
    uptime_s: 1,
    ip_addresses: [H],
    raw: { [H]: H },
    collected_at: "2026-10-25T00:00:00Z",
  },
  last_snapshot: {
    snapshot_id: 1,
    collected_at: "2026-10-25T00:00:00Z",
    package_count: 1,
    added: [{ name: H, version: "1", architecture: "all", status: H }],
    removed: [],
  },
};

const PID = "7";
const POLICY = {
  policy_id: 7,
  policy_name: H,
  policy_description: IMG,
  policy_status: "enabled",
  file_status: "enabled",
  status_overridden: true,
  family_id: 1,
  family_name: SCRIPT,
  format_version: "1.0",
  version: 1,
  source_file: H,
  plugin_count: 1,
  imported_at: "2026-10-28T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
};
const POLICY_DETAIL = {
  ...POLICY,
  deleted_at: null,
  plugins: [
    {
      plugin_uuid: ID,
      sort_order: 0,
      display_name: SCRIPT + " - " + H,
      plugin_name: H,
      control_ref: IMG,
      plugin_description: H,
      execute: H,
      execute_sha256: "a".repeat(64),
      operator: IMG,
      expected_result: H,
      timeout_s: 30,
      state: "active",
      updated_at: "2026-10-28T00:00:00Z",
    },
  ],
};
const IMPORT_ROW = {
  import_id: 1,
  file_name: H,
  file_sha256: "b".repeat(64),
  policy_version: null,
  mode: "manual",
  outcome: "rejected",
  plugins_added: 0,
  plugins_updated: 0,
  plugins_retired: 0,
  errors: [{ line: 1, element: H, code: IMG, message: H }],
  imported_by: 1,
  imported_at: "2026-10-28T00:00:00Z",
};

/** One fake manager for every route the shell can reach. */
function manager(
  role: string,
  totpEnrolled: boolean,
  over?: (c: Call) => Response | null,
) {
  answer((call) => {
    const r = over?.(call);
    if (r) {
      return r;
    }
    const page = (items: unknown[]) => json(200, { items, next_cursor: null });
    switch (call.method + " " + call.path) {
      case "POST /api/v1/auth/login":
        return json(200, loginResponse(role, totpEnrolled, TOKEN));
      case "POST /api/v1/auth/logout":
        return noContent();
      case "POST /api/v1/auth/totp/enrol":
        return JSON.parse(call.body).totp_code === undefined
          ? json(200, {
              secret: SECRET,
              otpauth_uri: "otpauth://totp/x?secret=" + SECRET,
            })
          : json(200, loginResponse(role, true, bsu("Y")));
      case "GET /api/v1/agents":
        return page([AGENT]);
      case "GET /api/v1/agents/" + ID:
        return json(200, DETAIL);
      case "GET /api/v1/agents/" + ID + "/packages":
        return page([
          {
            name: H,
            version: "1",
            architecture: "all",
            status: H,
            source_name: H,
            installed_size_kb: 1,
            first_seen_at: "2026-10-01T00:00:00Z",
            last_seen_at: "2026-10-25T00:00:00Z",
          },
        ]);
      case "GET /api/v1/enrollment-requests":
        return page([
          {
            request_id: 1,
            agent_id: ID,
            hostname: H,
            machine_id: "b".repeat(32),
            source_ip: "10.0.0.2",
            os_pretty_name: H,
            agent_version: "0.5.0",
            kind: "new",
            requested_at: "2026-10-25T00:00:00Z",
            token_expires_at: "2026-11-25T00:00:00Z",
            decision: null,
            decided_by: null,
            decided_at: null,
            matches: [
              {
                agent_id: ID,
                hostname: H,
                machine_id: "b".repeat(32),
                status: "online",
              },
            ],
          },
        ]);
      case "GET /api/v1/enrollment-tokens":
        return page([
          {
            token_id: 1,
            max_uses: 1,
            uses: 0,
            expires_at: "2026-10-26T00:00:00Z",
            allowed_cidrs: [H],
            auto_approve: false,
            created_by: 1,
            created_at: "2026-10-25T00:00:00Z",
            revoked_at: null,
          },
        ]);
      case "GET /api/v1/policies":
        return page([POLICY]);
      case "GET /api/v1/policies/" + PID:
        return json(200, POLICY_DETAIL);
      case "PATCH /api/v1/policies/" + PID:
        return json(200, POLICY);
      case "GET /api/v1/imports":
        return page([IMPORT_ROW]);
      case "POST /api/v1/policies/import":
        return json(200, {
          import_id: 2,
          outcome: "rejected",
          policy_id: null,
          policy_name: null,
          policy_version: null,
          plugins_added: 0,
          plugins_updated: 0,
          plugins_retired: 0,
          errors: [{ line: 1, element: H, code: "BIT001", message: H }],
        });
      case "POST /api/v1/policies/rebuild":
        return json(202, { task_id: ID });
      case "GET /api/v1/tasks/" + ID:
        return json(200, {
          task_id: ID,
          kind: "rebuild",
          state: "succeeded",
          requested_by: 1,
          result: {
            files: [
              {
                source_file: H,
                import_id: 1,
                outcome: "success",
                policy_id: 7,
                policy_version: 1,
              },
            ],
            deleted_policy_ids: [],
            plugins_retired: 0,
            removed_leftovers: [],
            not_imported: [],
          },
          started_at: "2026-10-28T00:00:00Z",
          finished_at: "2026-10-28T00:00:01Z",
        });
      case "GET /api/v1/packages/search":
        return queryOf(call).group_by === "package"
          ? page([
              { name: H, version: IMG, architecture: "all", host_count: 1 },
            ])
          : page([
              {
                name: H,
                version: IMG,
                architecture: "all",
                status: H,
                agent_id: ID,
                hostname: H,
              },
            ]);
      default:
        return json(599, {
          type: "unexpected",
          detail: call.method + " " + call.path,
        });
    }
  });
}

let watch: Watch;

beforeEach(() => {
  resetHttp();
  clearSession();
  window.location.hash = "";
  watch = watchSecrets();
});

afterEach(() => {
  const leaks = [TOKEN, bsu("Y"), PASSWORD, SECRET].flatMap((s) =>
    watch.leaked(s),
  );
  watch.stop();
  clearSession();
  window.location.hash = "";
  expect(leaks).toEqual([]);
});

async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 5; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  await settle();
}

async function signIn(code = ""): Promise<void> {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "u" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: PASSWORD },
  });
  fireEvent.change(
    screen.getByLabelText(
      "TOTP code (required for admins and accounts with TOTP)",
    ),
    { target: { value: code } },
  );
  fireEvent.submit(
    screen
      .getByRole("button", { name: "Sign in" })
      .closest("form") as HTMLFormElement,
  );
  await settle();
  await settle();
}

function nav(): string[] {
  return within(screen.getByRole("navigation", { name: "Main" }))
    .getAllByRole("link")
    .map((a) => (a.textContent ?? "") + " " + (a.getAttribute("href") ?? ""));
}

function requested(): string[] {
  return calls.map((c) => c.method + " " + c.path);
}

// ------------------------------------------------------------ CHK-M5-280

describe("CHK-M5-280 navigation per role", () => {
  // REQ-183 (3): Profiles for every role; the catalog admin screens for admins.
  const common = [
    "Hosts #/hosts",
    "Package search #/packages",
    "Profiles #/profiles",
  ];
  const account = ["TOTP #/account/totp", "Password #/account/password"];
  it.each([
    ["viewer", [...common, ...account]],
    ["operator", [...common, ...account]],
    [
      "admin",
      [
        ...common,
        "Upload policy #/catalog/upload",
        "Import history #/catalog/imports",
        "Rebuild catalog #/catalog/rebuild",
        "Enrolment requests #/enrolment/requests",
        "Enrolment tokens #/enrolment/tokens",
        ...account,
      ],
    ],
  ])(
    "%s sees exactly its entries, then the host list",
    async (role, entries) => {
      manager(role, true);
      render(<App />);
      expect(screen.queryByRole("navigation")).toBeNull();
      await signIn("123456");
      expect(nav()).toEqual(entries);
      expect(window.location.hash).toBe("#/hosts");
      expect(
        screen.getByRole("heading", { level: 1, name: "Hosts" }),
      ).toBeTruthy();
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
      const hosts = within(
        screen.getByRole("navigation", { name: "Main" }),
      ).getByRole("link", {
        name: "Hosts",
      });
      expect(hosts.getAttribute("aria-current")).toBe("page");
    },
  );
});

// ------------------------------------------------------------ CHK-M5-281

describe("CHK-M5-281 an admin route opened by a non-admin", () => {
  it.each(["viewer", "operator"])(
    "%s on #/enrolment/requests and #/enrolment/tokens: not available, no request",
    async (role) => {
      manager(role, true);
      render(<App />);
      await signIn("123456");
      for (const hash of ["#/enrolment/requests", "#/enrolment/tokens"]) {
        await go(hash);
        expect(
          screen.getByText("This page is not available for your role."),
        ).toBeTruthy();
        expect(
          screen.queryByRole("heading", { name: "Enrolment requests" }),
        ).toBeNull();
        expect(
          screen.queryByRole("heading", { name: "Enrolment tokens" }),
        ).toBeNull();
      }
      expect(requested().filter((r) => r.includes("/enrollment-"))).toEqual([]);
    },
  );

  it("an admin on the same hashes gets the screens", async () => {
    manager("admin", true);
    render(<App />);
    await signIn("123456");
    await go("#/enrolment/requests");
    expect(
      screen.getByRole("heading", { level: 1, name: "Enrolment requests" }),
    ).toBeTruthy();
    await go("#/enrolment/tokens");
    expect(
      screen.getByRole("heading", { level: 1, name: "Enrolment tokens" }),
    ).toBeTruthy();
    expect(requested()).toContain("GET /api/v1/enrollment-requests");
    expect(requested()).toContain("GET /api/v1/enrollment-tokens");
  });
});

// ------------------------------------------------------------ CHK-M5-282

describe("CHK-M5-282 an admin without TOTP reaches only TOTP and sign-out", () => {
  it("every hash shows the TOTP screen and no other route is requested", async () => {
    manager("admin", false);
    render(<App />);
    await signIn();
    const hashes = [
      "#/hosts",
      "#/hosts/" + ID,
      "#/packages",
      "#/enrolment/requests",
      "#/enrolment/tokens",
      "#/account/password",
      "#/account/totp",
      "#/nope",
    ];
    for (const hash of hashes) {
      await go(hash);
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
        "Set up TOTP",
      );
      expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Not now" })).toBeNull();
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    }
    expect(requested()).toEqual(["POST /api/v1/auth/login"]);
    // Completing enrolment opens the app.
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Start" })
        .closest("form") as HTMLFormElement,
    );
    await settle();
    fireEvent.change(screen.getByLabelText("Code"), {
      target: { value: "123456" },
    });
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Confirm" })
        .closest("form") as HTMLFormElement,
    );
    await settle();
    await settle();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
    expect(window.location.hash).toBe("#/hosts");
    expect(calls.at(-1)?.authorization).toBe("Bearer " + bsu("Y"));
  });
});

// ------------------------------------------------------------ CHK-M5-283

describe("CHK-M5-283 the TOTP offer for a non-admin", () => {
  it.each(["viewer", "operator"])(
    "%s sees the offer after sign-in; Not now leads to the host list; it returns after the next sign-in",
    async (role) => {
      manager(role, false);
      render(<App />);
      await signIn();
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
        "Set up TOTP",
      );
      expect(requested()).toEqual(["POST /api/v1/auth/login"]);
      fireEvent.click(screen.getByRole("button", { name: "Not now" }));
      await settle();
      expect(
        screen.getByRole("heading", { level: 1, name: "Hosts" }),
      ).toBeTruthy();
      expect(requested()).toContain("GET /api/v1/agents");
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      await settle();
      await signIn();
      expect(screen.getByRole("button", { name: "Not now" })).toBeTruthy();
    },
  );
});

// ------------------------------------------------------------ CHK-M5-284

describe("CHK-M5-284 sign-out and 401", () => {
  it.each([
    ["204", () => noContent()],
    ["500", () => problem(500, "about:blank")],
    ["a network error", () => Promise.reject(new TypeError("down"))],
  ] as const)(
    "sign-out with logout answering %s shows sign-in",
    async (_n, reply) => {
      manager("viewer", true, (c) =>
        c.path === "/api/v1/auth/logout" ? (reply() as Response) : null,
      );
      render(<App />);
      await signIn("123456");
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      await settle();
      expect(currentSession()).toBeNull();
      expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
      expect(screen.queryByRole("navigation")).toBeNull();
    },
  );

  it.each(["#/hosts", "#/packages", "#/hosts/" + ID, "#/enrolment/tokens"])(
    "a 401 on %s shows sign-in",
    async (hash) => {
      let fail = false;
      manager("admin", true, (c) =>
        fail && c.method === "GET" ? problem(401, "unauthorized") : null,
      );
      render(<App />);
      await signIn("123456");
      // Leave the route first (the password screen sends nothing), so the
      // screen under test mounts and requests again.
      await go("#/account/password");
      fail = true;
      await go(hash);
      if (hash === "#/packages") {
        fireEvent.submit(screen.getByRole("form", { name: "Search packages" }));
        await settle();
      }
      expect(currentSession()).toBeNull();
      expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    },
  );

  it("a password change shows sign-in with the password-changed note", async () => {
    manager("viewer", true, (c) =>
      c.path === "/api/v1/auth/password" ? noContent() : null,
    );
    render(<App />);
    await signIn("123456");
    await go("#/account/password");
    for (const l of [
      "Current password",
      "New password",
      "Repeat new password",
    ]) {
      fireEvent.change(screen.getByLabelText(l), {
        target: {
          value: l === "Current password" ? PASSWORD : "a-new-password-12",
        },
      });
    }
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Change password" })
        .closest("form") as HTMLFormElement,
    );
    await settle();
    expect(screen.getByRole("status").textContent).toBe(
      "Your password was changed. Sign in again.",
    );
    expect(currentSession()).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-285

describe("CHK-M5-285 a reload starts at sign-in", () => {
  it("fresh modules have no session, whatever the hash", async () => {
    manager("admin", true);
    const first = render(<App />);
    await signIn("123456");
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
    first.unmount();
    window.location.hash = "#/enrolment/tokens";
    vi.resetModules();
    const fresh = await import("./App");
    resetHttp();
    manager("admin", true);
    render(<fresh.App />);
    await settle();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(calls).toHaveLength(0);
  });

  it("before sign-in no hash mounts a screen", async () => {
    manager("admin", true);
    window.location.hash = "#/enrolment/tokens";
    render(<App />);
    await settle();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(calls).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M5-286

describe("CHK-M5-286 sign-in, three screens, sign-out: the token goes nowhere", () => {
  it("storage, cookie, IndexedDB, console, history and URL never hold it", async () => {
    manager("admin", true);
    const { container } = render(<App />);
    await signIn("123456");
    await go("#/hosts/" + ID);
    await go("#/packages");
    fireEvent.submit(screen.getByRole("form", { name: "Search packages" }));
    await settle();
    await go("#/enrolment/tokens");
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(window.location.href).not.toContain(TOKEN);
    expect(
      calls
        .filter((c) => c.path !== "/api/v1/auth/login")
        .every((c) => c.authorization === "Bearer " + TOKEN),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await settle();
    expect(currentSession()).toBeNull();
    // The afterEach checks every recorded write and the URL.
  });
});

// ------------------------------------------------------------ CHK-M5-287

describe("CHK-M5-287 hostile text on every screen", () => {
  it.each([
    ["#/hosts", "Hosts"],
    ["#/hosts/" + ID, null],
    ["#/enrolment/requests", "Enrolment requests"],
    ["#/enrolment/tokens", "Enrolment tokens"],
    ["#/packages", "Package search"],
  ])("%s renders the hostile strings literally", async (hash, heading) => {
    manager("admin", true);
    const { container } = render(<App />);
    await signIn("123456");
    await go(hash);
    if (hash === "#/packages") {
      fireEvent.submit(screen.getByRole("form", { name: "Search packages" }));
      await settle();
      fireEvent.click(screen.getByRole("button", { name: IMG }));
      await settle();
    }
    if (heading !== null) {
      expect(
        screen.getByRole("heading", { level: 1, name: heading }),
      ).toBeTruthy();
    }
    expect(container.textContent).toContain(H);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });
});

// ------------------------------------------------------------ CHK-M7-390

const M7_ADMIN = ["#/catalog/upload", "#/catalog/imports", "#/catalog/rebuild"];
const M7_ADMIN_PATHS = [
  "/api/v1/policies/import",
  "/api/v1/imports",
  "/api/v1/policies/rebuild",
  "/api/v1/tasks/",
];

/** jsdom has no DataTransfer, so a FileList-shaped object stands in. */
function fileList(file: File): FileList {
  return {
    0: file,
    length: 1,
    item: (i: number) => (i === 0 ? file : null),
  } as unknown as FileList;
}

describe("CHK-M7-390 the M7 routes per role (REQ-183 (3))", () => {
  it.each(["viewer", "operator"])(
    "%s on the catalog admin hashes: not available, no request",
    async (role) => {
      manager(role, true);
      render(<App />);
      await signIn("123456");
      for (const hash of M7_ADMIN) {
        await go(hash);
        expect(
          screen.getByText("This page is not available for your role."),
        ).toBeTruthy();
        for (const h of [
          "Upload policy",
          "Import history",
          "Rebuild catalog",
        ]) {
          expect(screen.queryByRole("heading", { name: h })).toBeNull();
        }
        expect(screen.queryByRole("button", { name: "Rebuild" })).toBeNull();
        expect(document.querySelector("input[type=file]")).toBeNull();
      }
      expect(
        requested().filter((r) => M7_ADMIN_PATHS.some((p) => r.includes(p))),
      ).toEqual([]);
    },
  );

  it.each(["viewer", "operator"])(
    "%s opens Profiles and a profile: plain views, no admin control, no mutation",
    async (role) => {
      manager(role, true);
      render(<App />);
      await signIn("123456");
      await go("#/profiles");
      expect(
        screen.getByRole("heading", { level: 1, name: "Profiles" }),
      ).toBeTruthy();
      await go("#/profiles/" + PID);
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(H);
      const main = document.querySelector("main") as HTMLElement;
      for (const b of ["Enable", "Disable", "Clear override", "Delete"]) {
        expect(within(main).queryByRole("button", { name: b })).toBeNull();
      }
      expect(requested()).toContain("GET /api/v1/policies");
      expect(requested()).toContain("GET /api/v1/policies/" + PID);
      expect(
        calls.filter((c) => c.method === "PATCH" || c.method === "DELETE"),
      ).toEqual([]);
      // the detail page marks its list's entry
      const profiles = within(
        screen.getByRole("navigation", { name: "Main" }),
      ).getByRole("link", { name: "Profiles" });
      expect(profiles.getAttribute("aria-current")).toBe("page");
      expect(document.body.textContent).toContain("Profile detail");
    },
  );

  it("an admin gets the three catalog screens and the profile actions", async () => {
    manager("admin", true);
    render(<App />);
    await signIn("123456");
    await go("#/catalog/upload");
    expect(
      screen.getByRole("heading", { level: 1, name: "Upload policy" }),
    ).toBeTruthy();
    await go("#/catalog/imports");
    expect(
      screen.getByRole("heading", { level: 1, name: "Import history" }),
    ).toBeTruthy();
    expect(requested()).toContain("GET /api/v1/imports");
    await go("#/catalog/rebuild");
    expect(
      screen.getByRole("heading", { level: 1, name: "Rebuild catalog" }),
    ).toBeTruthy();
    // a screen sends nothing until the admin acts
    expect(requested()).not.toContain("POST /api/v1/policies/rebuild");
    await go("#/profiles/" + PID);
    for (const b of ["Disable", "Clear override", "Delete"]) {
      expect(screen.getByRole("button", { name: b })).toBeTruthy();
    }
  });

  it("each M7 nav entry links to its hash and is marked current there", async () => {
    manager("admin", true);
    render(<App />);
    await signIn("123456");
    for (const [label, hash, heading] of [
      ["Profiles", "#/profiles", "Profiles"],
      ["Upload policy", "#/catalog/upload", "Upload policy"],
      ["Import history", "#/catalog/imports", "Import history"],
      ["Rebuild catalog", "#/catalog/rebuild", "Rebuild catalog"],
    ] as const) {
      const link = within(
        screen.getByRole("navigation", { name: "Main" }),
      ).getByRole("link", { name: label });
      expect(link.getAttribute("href")).toBe(hash);
      await go(hash);
      expect(
        screen.getByRole("heading", { level: 1, name: heading }),
      ).toBeTruthy();
      expect(
        within(screen.getByRole("navigation", { name: "Main" }))
          .getByRole("link", { name: label })
          .getAttribute("aria-current"),
      ).toBe("page");
    }
  });
});

// ------------------------------------------------------------ CHK-M7-393

describe("CHK-M7-393 the token on the M7 screens: never in a URL or storage", () => {
  it("profiles, a status change, an upload, the history and a rebuild", async () => {
    manager("admin", true);
    const { container } = render(<App />);
    await signIn("123456");
    await go("#/profiles");
    await go("#/profiles/" + PID);
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await settle();
    await go("#/catalog/upload");
    fireEvent.change(screen.getByLabelText(".bit file (at most 5 MiB)"), {
      target: {
        files: fileList(new File(["<Policy/>"], "a.bit", { type: "text/xml" })),
      },
    });
    fireEvent.submit(screen.getByRole("form", { name: "Upload policy" }));
    await settle();
    await go("#/catalog/imports");
    await go("#/catalog/rebuild");
    fireEvent.click(screen.getByRole("button", { name: "Rebuild" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(screen.getByRole("status").textContent).toBe("Succeeded.");
    for (const r of [
      "PATCH /api/v1/policies/" + PID,
      "POST /api/v1/policies/import",
      "GET /api/v1/imports",
      "POST /api/v1/policies/rebuild",
      "GET /api/v1/tasks/" + ID,
    ]) {
      expect(requested()).toContain(r);
    }
    const sent = calls.filter((c) => c.path !== "/api/v1/auth/login");
    expect(sent.every((c) => c.authorization === "Bearer " + TOKEN)).toBe(true);
    expect(sent.every((c) => !c.url.includes(TOKEN))).toBe(true);
    expect(sent.every((c) => !c.body.includes(TOKEN))).toBe(true);
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(window.location.href).not.toContain(TOKEN);
    // The afterEach checks storage, cookie, IndexedDB, console and history.
  });
});

// ------------------------------------------------------------ CHK-M7-392

describe("CHK-M7-392 hostile text on the M7 screens, inside the shell", () => {
  it.each([
    ["#/profiles", "Profiles"],
    ["#/profiles/" + PID, null],
    ["#/catalog/imports", "Import history"],
  ])("%s renders the hostile strings literally", async (hash, heading) => {
    manager("admin", true);
    const { container } = render(<App />);
    await signIn("123456");
    await go(hash);
    if (heading !== null) {
      expect(
        screen.getByRole("heading", { level: 1, name: heading }),
      ).toBeTruthy();
    } else {
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(H);
      expect(container.textContent).toContain(SCRIPT + " - " + H);
    }
    expect(container.textContent).toContain(H);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });

  it("an upload's findings and a rebuild's files render literally", async () => {
    manager("admin", true);
    const { container } = render(<App />);
    await signIn("123456");
    await go("#/catalog/upload");
    fireEvent.change(screen.getByLabelText(".bit file (at most 5 MiB)"), {
      target: { files: fileList(new File(["x"], H + ".bit")) },
    });
    fireEvent.submit(screen.getByRole("form", { name: "Upload policy" }));
    await settle();
    expect(
      screen.getByRole("region", { name: "Import outcome" }).textContent,
    ).toContain(H);
    await go("#/catalog/rebuild");
    fireEvent.click(screen.getByRole("button", { name: "Rebuild" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(
      screen.getByRole("region", { name: "Rebuild task" }).textContent,
    ).toContain(H);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });
});
