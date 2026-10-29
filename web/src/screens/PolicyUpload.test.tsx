// TASK-171 TEST (TP-M7-29): CHK-M7-314.
// Expected values: REQ-182 (1), (5) and the TASK-171 row (a 413 and a 409 show
// their messages); TS §6.3 L1137 (`multipart/form-data` with one file field,
// `file`), L1138 (`.bit` 5 MB, larger bodies get 413), L1141 (plain text);
// TS §4.3 L550 and #98 (d), (e) (200 for both outcomes; 409
// `policy_managed_on_server`); #102 (d) (the start-up 503); #110 (warnings in
// `errors`); SR §3.5 (finding = line, element, code, message).
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
import { PolicyUpload } from "./PolicyUpload";

const IMPORT = "/api/v1/policies/import";
const SCRIPT = "<script>alert(1)</script>";
const IMG = "<img src=x onerror=alert(1)>";
const TOKEN = bsu("U");
const STARTING = "The catalog is starting; retry shortly.";

// Bytes that a text re-encoding or a JSON body would change: CRLF, a tab, a
// non-ASCII letter, and the canonical start of a .bit file.
const CONTENT =
  '<?xml version="1.0" encoding="UTF-8"?>\r\n<Policy formatVersion="1.0">\té</Policy>\n';

interface Finding {
  line: number | null;
  element: string | null;
  code: string;
  message: string;
}

function result(extra: Record<string, unknown> = {}) {
  return {
    import_id: 41,
    outcome: "success",
    policy_id: 7,
    policy_name: "CIS Ubuntu 24.04 Level 1 - Server",
    policy_version: 3,
    plugins_added: 2,
    plugins_updated: 5,
    plugins_retired: 1,
    errors: [] as Finding[],
    ...extra,
  };
}

const navigate = vi.fn();

beforeEach(() => {
  resetHttp();
  navigate.mockReset();
  setSession(loginResponse("admin", true, TOKEN));
});

afterEach(() => {
  clearSession();
});

async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

function mount(): ReturnType<typeof render> {
  return render(<PolicyUpload navigate={navigate} />);
}

/** jsdom has no DataTransfer, so a FileList-shaped object stands in. */
function fileList(...files: File[]): FileList {
  const list: Record<number, File> & {
    length: number;
    item(i: number): File | null;
  } = {
    length: files.length,
    item: (i: number) => files[i] ?? null,
  };
  files.forEach((f, i) => {
    list[i] = f;
  });
  return list as unknown as FileList;
}

function choose(file: File): void {
  const input = screen.getByLabelText(".bit file (at most 5 MiB)");
  fireEvent.change(input, { target: { files: fileList(file) } });
}

async function submit(): Promise<void> {
  fireEvent.submit(screen.getByRole("form", { name: "Upload policy" }));
  await settle();
}

async function upload(file: File, reply: (c: Call) => Response): Promise<void> {
  answer(reply);
  choose(file);
  await submit();
}

function bitFile(name = "cis.bit", content = CONTENT): File {
  return new File([content], name, { type: "application/xml" });
}

/** Every FormData entry of the call as [name, file name, text]. */
async function entries(call: Call): Promise<[string, string | null, string][]> {
  expect(call.form, "the body is a FormData").not.toBeNull();
  const out: [string, string | null, string][] = [];
  for (const [name, value] of (call.form as FormData).entries()) {
    if (typeof value === "string") {
      out.push([name, null, value]);
    } else {
      out.push([name, value.name, await readText(value)]);
    }
  }
  return out;
}

function readText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("read failed"));
    reader.readAsText(blob);
  });
}

// ------------------------------------------------------------ CHK-M7-314

describe("CHK-M7-314 (a) the request: one multipart part `file` with the file's bytes", () => {
  it("sends exactly one POST with one `file` part holding the chosen file", async () => {
    mount();
    await upload(bitFile(), () => json(200, result()));
    expect(calls.map((c) => c.method + " " + c.path)).toEqual([
      "POST " + IMPORT,
    ]);
    const call = callsTo(IMPORT, "POST")[0] as Call;
    expect(call.authorization).toBe("Bearer " + TOKEN);
    // openapi-fetch set no JSON type: the multipart boundary is the runtime's.
    expect(call.contentType?.toLowerCase()).toMatch(
      /^multipart\/form-data; *boundary=/,
    );
    expect(await entries(call)).toEqual([["file", "cis.bit", CONTENT]]);
    expect(call.body).not.toContain('{"file"');
  });

  it("the file's own name is what is sent, whatever it holds (the server decides, #99 (d))", async () => {
    mount();
    await upload(bitFile("x y.bit", "other"), () => json(200, result()));
    expect(await entries(callsTo(IMPORT, "POST")[0] as Call)).toEqual([
      ["file", "x y.bit", "other"],
    ]);
  });

  it("no file chosen: a note and no request", async () => {
    answer(() => json(200, result()));
    mount();
    await submit();
    expect(calls).toHaveLength(0);
    expect(screen.getByRole("alert").textContent).toBe(
      "Choose a .bit file first.",
    );
  });

  it("the file input accepts .bit and the form holds no token or password field", () => {
    const { container } = mount();
    const inputs = container.querySelectorAll("input");
    expect(inputs).toHaveLength(1);
    expect(inputs[0]?.getAttribute("type")).toBe("file");
    expect(inputs[0]?.getAttribute("accept")).toBe(".bit");
    expect(document.body.textContent?.toLowerCase()).not.toMatch(
      /api token|bsk_/,
    );
  });
});

describe("CHK-M7-314 (b) the outcome", () => {
  it("success: Imported, the policy name, version and counts, and a link to the profile", async () => {
    mount();
    await upload(bitFile(), () => json(200, result()));
    const out = screen.getByRole("region", { name: "Import outcome" });
    expect(within(out).getByRole("heading", { level: 2 }).textContent).toBe(
      "Imported",
    );
    const text = out.textContent ?? "";
    expect(text).toContain("Import 41");
    expect(text).toContain(
      "CIS Ubuntu 24.04 Level 1 - Server, version 3: 2 plugins added, 5 updated, 1 retired.",
    );
    expect(text).toContain("Findings (0)");
    expect(text).toContain("No findings.");
    const link = within(out).getByRole("link", { name: "Open the profile" });
    expect(link.getAttribute("href")).toBe("#/profiles/7");
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith({ name: "profile", policyId: "7" });
  });

  it("success with warnings (#110): the warnings are listed", async () => {
    mount();
    await upload(bitFile(), () =>
      json(
        200,
        result({
          errors: [
            {
              line: 12,
              element: "Policy/PluginsGroups/Plugin[2]/Execute",
              code: "BIT101",
              message: "warn text",
            },
          ],
        }),
      ),
    );
    const table = screen.getByRole("table", { name: "Findings" });
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent)),
    ).toEqual([
      ["12", "Policy/PluginsGroups/Plugin[2]/Execute", "BIT101", "warn text"],
    ]);
  });

  it("rejected: Rejected, the catalog is unchanged, every finding's line, element, code and message", async () => {
    const errors: Finding[] = [
      { line: null, element: null, code: "BIT001", message: "not XML" },
      {
        line: 3,
        element: "Policy/PolicyName",
        code: "BIT003",
        message: "PolicyName is empty",
      },
      {
        line: 40,
        element: "Policy/PluginsGroups/Plugin[12]/Operator",
        code: "BIT010",
        message: "unknown operator",
      },
    ];
    mount();
    await upload(bitFile(), () =>
      json(
        200,
        result({
          outcome: "rejected",
          policy_id: null,
          policy_name: null,
          policy_version: null,
          plugins_added: 0,
          plugins_updated: 0,
          plugins_retired: 0,
          errors,
        }),
      ),
    );
    const out = screen.getByRole("region", { name: "Import outcome" });
    expect(within(out).getByRole("heading", { level: 2 }).textContent).toBe(
      "Rejected",
    );
    expect(out.textContent).toContain(
      "The file was not imported; the catalog is unchanged.",
    );
    expect(out.textContent).toContain("Findings (3)");
    expect(within(out).queryByRole("link")).toBeNull();
    const rows = within(within(out).getByRole("table", { name: "Findings" }))
      .getAllByRole("row")
      .slice(1)
      .map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent));
    expect(rows).toEqual([
      ["none", "file", "BIT001", "not XML"],
      ["3", "Policy/PolicyName", "BIT003", "PolicyName is empty"],
      [
        "40",
        "Policy/PluginsGroups/Plugin[12]/Operator",
        "BIT010",
        "unknown operator",
      ],
    ]);
    expect(out.textContent).not.toContain("Imported");
  });

  it("a second upload replaces the first outcome", async () => {
    mount();
    await upload(bitFile(), () => json(200, result()));
    await upload(bitFile(), () =>
      json(
        200,
        result({
          outcome: "rejected",
          policy_id: null,
          policy_name: null,
          policy_version: null,
          errors: [{ line: 1, element: null, code: "BIT002", message: "m" }],
        }),
      ),
    );
    expect(
      screen.getAllByRole("region", { name: "Import outcome" }),
    ).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "Rejected",
    );
    expect(callsTo(IMPORT, "POST")).toHaveLength(2);
  });
});

describe("CHK-M7-314 (c) refusals", () => {
  it("413: the size message", async () => {
    mount();
    await upload(bitFile(), () => problem(413, "too_large", "too big"));
    expect(screen.getByRole("alert").textContent).toBe(
      "The file is too large. A .bit file may be at most 5 MiB.",
    );
    expect(screen.queryByRole("region", { name: "Import outcome" })).toBeNull();
  });

  it("409 policy_managed_on_server: the server-folder message", async () => {
    mount();
    await upload(bitFile(), () =>
      problem(409, "policy_managed_on_server", "managed"),
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "This policy is managed in the server folder. Change or remove its file on the server.",
    );
    expect(screen.queryByRole("region", { name: "Import outcome" })).toBeNull();
  });

  it("503 at start-up (#102 (d)): the catalog-starting message", async () => {
    mount();
    await upload(bitFile(), () =>
      problem(503, "about:blank", STARTING, { "Retry-After": "10" }),
    );
    expect(screen.getByRole("alert").firstChild?.textContent).toBe(STARTING);
  });

  it("403 forbidden: the role message", async () => {
    mount();
    await upload(bitFile(), () => problem(403, "forbidden"));
    expect(screen.getByRole("alert").textContent).toContain(
      "Your role does not allow this.",
    );
  });

  it("a network failure: unavailable", async () => {
    mount();
    await upload(
      bitFile(),
      () => Promise.reject(new TypeError("down")) as never,
    );
    expect(screen.getByRole("alert").textContent).toBe(
      "The manager is unavailable. Try again later.",
    );
  });
});

describe("CHK-M7-314 (d) hostile text (REQ-182 (5))", () => {
  it("policy name, finding element, code and message render literally", async () => {
    const H = SCRIPT + IMG;
    const { container } = mount();
    await upload(bitFile(H + ".bit"), () =>
      json(
        200,
        result({
          policy_name: H,
          errors: [{ line: 1, element: H, code: IMG, message: H }],
        }),
      ),
    );
    const out = screen.getByRole("region", { name: "Import outcome" });
    expect(out.textContent).toContain(H + ", version 3");
    const cells = [
      ...within(out)
        .getByRole("table", { name: "Findings" })
        .querySelectorAll("tbody td"),
    ].map((td) => td.textContent);
    expect(cells).toEqual(["1", H, IMG, H]);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
    expect(document.querySelectorAll("script, img")).toHaveLength(0);
  });

  it("a hostile server detail on a refusal renders literally", async () => {
    const { container } = mount();
    await upload(bitFile(), () =>
      problem(409, "policy_managed_on_server", IMG + SCRIPT),
    );
    expect(screen.getByRole("alert").textContent).toContain(IMG + SCRIPT);
    expect(container.querySelectorAll("script, img")).toHaveLength(0);
  });
});
