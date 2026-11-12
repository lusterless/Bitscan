// TASK-125 TEST (TP-M5-18): CHK-M5-274 to CHK-M5-276 (the unit half; the
// screen half is in src/screens/PackageSearch.test.tsx).
// Expected values: REQ-131 (1)-(4); TS §7.3 L1224, §6.3 L1142 (the server
// escapes, the UI does not change the CSV); #84 (c) (packages.csv); TS §6.2
// L1076 (every call carries the bearer, so the export cannot be a plain link).
import {
  answer,
  bsu,
  calls,
  callsTo,
  loginResponse,
  problem,
  queryOf,
  resetHttp,
  type Call,
} from "../test/harness";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CSV_FILE_NAME,
  downloadCsv,
  downloadResultsCsv,
  resultsCsvFileName,
  saveBlob,
} from "./download";
import { clearSession, currentSession, setSession } from "./session";

const CSV = "/api/v1/packages/search.csv";
const CR = String.fromCharCode(13);
const LF = String.fromCharCode(10);
// The bytes a server would send: CRLF, a quoted formula cell, non-ASCII.
const BODY =
  "name,version,architecture,host_count" +
  CR +
  LF +
  '"\'=HYPERLINK(""http://x"")",1.0,amd64,2' +
  CR +
  LF +
  "pакет-ü-日本,1:2.0~rc1,all,1" +
  CR +
  LF;

interface Saved {
  readonly blobs: Blob[];
  readonly created: string[];
  readonly revoked: string[];
  readonly clicked: { href: string; download: string; attached: boolean }[];
}

function stubSaving(): Saved {
  const saved: Saved = { blobs: [], created: [], revoked: [], clicked: [] };
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (b: Blob) => {
      saved.blobs.push(b);
      const url = "blob:https://manager.test/" + String(saved.blobs.length);
      saved.created.push(url);
      return url;
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: (u: string) => {
      saved.revoked.push(u);
    },
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.clicked.push({
      href: this.getAttribute("href") ?? "",
      download: this.download,
      attached: document.body.contains(this),
    });
  });
  return saved;
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("viewer", true, bsu("V")));
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  clearSession();
});

describe("CHK-M5-274 the export request", () => {
  it("goes through the client with the bearer and exactly the given query", async () => {
    stubSaving();
    answer(
      () =>
        new Response(BODY, {
          status: 200,
          headers: { "Content-Type": "text/csv; charset=utf-8" },
        }),
    );
    const query = {
      q: "ssl",
      version: "1.0",
      version_op: "ge",
      arch: "amd64",
      status: "any",
      os: "ubuntu:24.04",
      tag: "db",
      host: "web",
      agent_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
      group_by: "host",
    } as const;
    await expect(downloadCsv(query)).resolves.toBeNull();
    expect(calls).toHaveLength(1);
    const call = calls[0] as Call;
    expect(call.method).toBe("GET");
    expect(call.path).toBe(CSV);
    expect(call.authorization).toBeNull();
    expect(call.csrf).toBe("1");
    expect(queryOf(call)).toEqual(query);
    expect(call.query.has("limit")).toBe(false);
    expect(call.query.has("cursor")).toBe(false);
  });
});

describe("CHK-M5-275 the saved file", () => {
  it("is the response body byte for byte, named packages.csv, and its URL is revoked after the click", async () => {
    const saved = stubSaving();
    answer(
      () =>
        new Response(new TextEncoder().encode(BODY), {
          status: 200,
          headers: { "Content-Type": "text/csv; charset=utf-8" },
        }),
    );
    await downloadCsv({ group_by: "package" });
    expect(saved.blobs).toHaveLength(1);
    const bytes = new Uint8Array(await (saved.blobs[0] as Blob).arrayBuffer());
    expect(Array.from(bytes)).toEqual(
      Array.from(new TextEncoder().encode(BODY)),
    );
    expect(CSV_FILE_NAME).toBe("packages.csv");
    expect(saved.clicked).toEqual([
      { href: saved.created[0], download: "packages.csv", attached: true },
    ]);
    // The temporary link is removed again.
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(saved.revoked).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(saved.revoked).toEqual([saved.created[0]]);
  });

  it("saveBlob alone: create, click, remove, revoke on the next task", async () => {
    const saved = stubSaving();
    const blob = new Blob(["a,b" + CR + LF]);
    saveBlob(blob, "x.csv");
    expect(saved.blobs[0]).toBe(blob);
    expect(saved.clicked[0]?.download).toBe("x.csv");
    expect(saved.revoked).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(saved.revoked).toEqual(saved.created);
  });
});

describe("CHK-M5-276 a refusal", () => {
  it("a 400 returns its problem with the detail and saves nothing", async () => {
    const saved = stubSaving();
    answer(() =>
      problem(
        400,
        "invalid_request",
        "Invalid request: more than 100000 rows; narrow the filters",
      ),
    );
    const result = await downloadCsv({});
    expect(result).toEqual({
      status: 400,
      type: "invalid_request",
      detail: "Invalid request: more than 100000 rows; narrow the filters",
      retryAfterS: null,
    });
    expect(saved.blobs).toHaveLength(0);
    expect(saved.clicked).toHaveLength(0);
    expect(callsTo(CSV)).toHaveLength(1);
  });

  it("a 401 ends the session (the middleware sees the export too)", async () => {
    stubSaving();
    answer(() => problem(401, "unauthorized"));
    const result = await downloadCsv({});
    expect(result?.status).toBe(401);
    const { currentSession } = await import("./session");
    expect(currentSession()).toBeNull();
  });
});

// ---------------------------------------------------------------- M11
// TASK-239 TEST (TP-M11-07): CHK-M11-263, CHK-M11-264, plant CHK-M11-378.
// Expected values: REQ-281 (3) (export calls /api/v1/scans/{id}/results.csv
// with the current filters and saves the blob as scan-<id>-results.csv);
// #146 (d) (Content-Disposition filename "scan-<scan_id>-results.csv", the
// 100,000-row cap refused as 400 before any CSV byte); TS §6.3 L1144 (the
// server escapes; the UI saves the bytes unchanged); TS §6.2 L1076 (bearer).

const SCAN = "0f8fad5b-d9cb-469f-a165-70867728950e";
const AGENT = "7c9e6679-7425-40de-944b-e07fc1f90ae7";
const RESULTS_CSV = "/api/v1/scans/" + SCAN + "/results.csv";
const RESULTS_BODY =
  "hostname,agent_id,plugin_uuid,plugin_name,result" +
  CR +
  LF +
  '"<script>x</script>",' +
  AGENT +
  ",u,\"'=cmd|' /C calc'!A0\",FAIL" +
  CR +
  LF +
  "hôte-日本," +
  AGENT +
  ",u,ok,PASS" +
  CR +
  LF;

function csvAnswer(headers: Record<string, string> = {}): Response {
  return new Response(new TextEncoder().encode(RESULTS_BODY), {
    status: 200,
    headers: { "Content-Type": "text/csv; charset=utf-8", ...headers },
  });
}

describe("CHK-M11-263 the results export request", () => {
  it("one GET through the client with the bearer and exactly the filters", async () => {
    stubSaving();
    answer(() => csvAnswer());
    await expect(
      downloadResultsCsv(SCAN, { status: "FAIL", agent_id: AGENT }),
    ).resolves.toBeNull();
    expect(calls).toHaveLength(1);
    const call = calls[0] as Call;
    expect(call.method).toBe("GET");
    expect(call.path).toBe(RESULTS_CSV);
    expect(call.authorization).toBeNull();
    expect(call.csrf).toBe("1");
    expect(queryOf(call)).toEqual({ status: "FAIL", agent_id: AGENT });
  });

  it("no filters sends no query at all (no limit, no cursor)", async () => {
    stubSaving();
    answer(() => csvAnswer());
    await downloadResultsCsv(SCAN, {});
    const call = calls[0] as Call;
    expect(call.path).toBe(RESULTS_CSV);
    expect(call.url).toBe(RESULTS_CSV);
  });

  it("NOT_RUN is sent as given", async () => {
    stubSaving();
    answer(() => csvAnswer());
    await downloadResultsCsv(SCAN, { status: "NOT_RUN" });
    expect(queryOf(calls[0] as Call)).toEqual({ status: "NOT_RUN" });
  });
});

describe("CHK-M11-263 the saved results file (plant CHK-M11-378)", () => {
  it("is a Blob of the body byte for byte, named scan-<id>-results.csv, URL revoked after the click", async () => {
    const saved = stubSaving();
    answer(() => csvAnswer());
    await downloadResultsCsv(SCAN, { status: "FAIL" });
    expect(saved.blobs).toHaveLength(1);
    const blob = saved.blobs[0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(Array.from(bytes)).toEqual(
      Array.from(new TextEncoder().encode(RESULTS_BODY)),
    );
    expect(saved.clicked).toEqual([
      {
        href: saved.created[0],
        download: "scan-" + SCAN + "-results.csv",
        attached: true,
      },
    ]);
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(saved.revoked).toEqual([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(saved.revoked).toEqual([saved.created[0]]);
  });

  it("the name is the canonical lower-case id (#146 (d)) whatever case the screen holds", async () => {
    expect(resultsCsvFileName(SCAN.toUpperCase())).toBe(
      "scan-" + SCAN + "-results.csv",
    );
    const saved = stubSaving();
    answer(() => csvAnswer());
    await downloadResultsCsv(SCAN.toUpperCase(), {});
    expect(saved.clicked[0]?.download).toBe("scan-" + SCAN + "-results.csv");
  });

  it("a hostile Content-Disposition never becomes the file name", async () => {
    const saved = stubSaving();
    answer(() =>
      csvAnswer({
        "Content-Disposition": 'attachment; filename="../../evil.exe"',
      }),
    );
    await downloadResultsCsv(SCAN, {});
    expect(saved.clicked.map((c) => c.download)).toEqual([
      "scan-" + SCAN + "-results.csv",
    ]);
  });

  it("the M5 packages export keeps its own name", async () => {
    const saved = stubSaving();
    answer(() => csvAnswer());
    await downloadCsv({});
    expect(saved.clicked[0]?.download).toBe(CSV_FILE_NAME);
    expect((calls[0] as Call).path).toBe(CSV);
  });
});

describe("CHK-M11-264 a refused results export", () => {
  it("the 100,000-row 400 returns its detail and saves nothing", async () => {
    const saved = stubSaving();
    const detail = "Invalid request: more than 100000 rows; narrow the filters";
    answer(() => problem(400, "invalid_request", detail));
    await expect(downloadResultsCsv(SCAN, {})).resolves.toEqual({
      status: 400,
      type: "invalid_request",
      detail,
      retryAfterS: null,
    });
    expect(saved.blobs).toHaveLength(0);
    expect(saved.clicked).toHaveLength(0);
    expect(callsTo(RESULTS_CSV)).toHaveLength(1);
  });

  it("a 404 returns not_found and saves nothing", async () => {
    const saved = stubSaving();
    answer(() => problem(404, "not_found", "Not found."));
    const result = await downloadResultsCsv(SCAN, {});
    expect(result?.status).toBe(404);
    expect(result?.type).toBe("not_found");
    expect(saved.blobs).toHaveLength(0);
  });

  it("a 401 ends the session", async () => {
    stubSaving();
    answer(() => problem(401, "unauthorized"));
    const result = await downloadResultsCsv(SCAN, {});
    expect(result?.status).toBe(401);
    expect(currentSession()).toBeNull();
  });
});
