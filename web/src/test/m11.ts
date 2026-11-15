// M11 test builders (tester-owned; TP-M11-14). Import "./harness" first in
// every test file, then this module.
import { act } from "@testing-library/react";
import { vi } from "vitest";

import type { components } from "../api/schema";
import type { ScanLinks } from "../components/ScanTable";

type S = components["schemas"];
export type ScanItem = S["ScanItem"];
export type ScanDetailItem = S["ScanDetailItem"];
export type HostSummary = S["HostSummary"];
export type ResultItem = S["ScanResultItem"];
export type ResultWithOutput = S["ScanResultItemWithOutput"];
export type PolicyItem = S["PolicyItem"];
export type ScheduleItem = S["ScheduleItem"];
export type AgentItem = S["AgentItem"];

export const SCRIPT = "<script>alert(1)</script>";
export const IMG = "<img src=x onerror=alert(1)>";

export const SCAN = "0f8fad5b-d9cb-469f-a165-70867728950e";
export const SCAN2 = "1b4e28ba-2fa1-41d2-883f-0016d3cca427";

export function uuid(i: number): string {
  return "7c9e6679-7425-40de-944b-" + String(i).padStart(12, "0");
}

/** Lets every pending promise and React update run. */
export async function settle(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
  });
}

export interface MockLinks extends ScanLinks {
  readonly opened: string[];
}

/** ScanLinks with recognisable hrefs; openScan records its ids. */
export function mockLinks(): MockLinks {
  const opened: string[] = [];
  return {
    opened,
    scansHref: "#/test-scans",
    runScanHref: "#/test-run-scan",
    scanHref: (id) => "#/test-scan/" + id,
    resultsHref: (id) => "#/test-results/" + id,
    openScan: vi.fn((id: string) => {
      opened.push(id);
    }),
  };
}

export function scanItem(i: number, extra: Partial<ScanItem> = {}): ScanItem {
  return {
    scan_id: uuid(1000 + i),
    policy_id: 7,
    policy_name: "CIS Ubuntu 24.04 " + String(i),
    policy_version: 3,
    trigger: "manual",
    schedule_id: null,
    requested_by: 2,
    state: "completed",
    target_kind: "all",
    resolved_count: 4,
    created_at: "2026-11-01T10:00:00Z",
    finished_at: "2026-11-01T10:05:00Z",
    ...extra,
  };
}

export function host(i: number, extra: Partial<HostSummary> = {}): HostSummary {
  return {
    agent_id: uuid(i),
    hostname: "host-" + String(i),
    jobs: [
      {
        job_id: uuid(5000 + i),
        state: "completed",
        retry_of: null,
        dispatched_at: "2026-11-01T10:01:00Z",
        started_at: "2026-11-01T10:01:10Z",
        finished_at: "2026-11-01T10:02:00Z",
        cancel_reason: null,
      },
    ],
    passed: 3,
    failed: 1,
    errors: 5,
    not_run: 2,
    score: 0.75,
    ...extra,
  };
}

export function detail(extra: Partial<ScanDetailItem> = {}): ScanDetailItem {
  return {
    ...scanItem(0, { scan_id: SCAN }),
    target: { all: true },
    hosts: [host(1)],
    ...extra,
  };
}

export function resultItem(
  i: number,
  extra: Partial<ResultItem> = {},
): ResultItem {
  return {
    agent_id: uuid(1),
    hostname: "host-1",
    job_id: uuid(5001),
    retry: false,
    plugin_uuid: uuid(9000 + i),
    plugin_name: "Plugin " + String(i),
    result: "PASS",
    eval_detail: null,
    original_result: "PASS",
    original_eval_detail: null,
    reeval_policy_version: null,
    reevaluated_by: null,
    reevaluated_at: null,
    operator: "Equals",
    expected: "no",
    execute: "sshd -T | grep permitrootlogin",
    exit_code: 0,
    timed_out: false,
    truncated: false,
    started_at: "2026-11-01T10:01:10Z",
    finished_at: "2026-11-01T10:01:11Z",
    received_at: "2026-11-01T10:01:12Z",
    ...extra,
  };
}

export function withOutput(
  item: ResultItem,
  stdout: string | null,
  stderr: string | null,
): ResultWithOutput {
  return { ...item, stdout, stderr };
}

export function policy(
  id: number,
  extra: Partial<PolicyItem> = {},
): PolicyItem {
  return {
    policy_id: id,
    policy_name: "Profile " + String(id),
    policy_description: "d",
    policy_status: "enabled",
    file_status: "enabled",
    family_id: 1,
    family_name: "CIS Ubuntu 24.04",
    format_version: "1.0",
    imported_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    plugin_count: 3,
    source_file: "cis.bit",
    status_overridden: false,
    version: 1,
    ...extra,
  };
}

export function schedule(
  id: number,
  extra: Partial<ScheduleItem> = {},
): ScheduleItem {
  return {
    schedule_id: id,
    name: "Nightly " + String(id),
    policy_id: 7,
    target: { tags: ["prod-web"] },
    cron: "0 2 * * *",
    timezone: "UTC",
    enabled: true,
    last_run_at: null,
    next_run_at: "2026-11-09T02:00:00Z",
    created_by: 2,
    ...extra,
  };
}

export function agentItem(
  i: number,
  extra: Partial<AgentItem> = {},
): AgentItem {
  return {
    agent_id: uuid(i),
    hostname: "host-" + String(i),
    status: "online",
    os_id: "ubuntu",
    os_version_id: "24.04",
    os_pretty_name: "Ubuntu 24.04.1 LTS",
    agent_version: "0.2.0",
    last_heartbeat_at: "2026-11-08T10:00:00Z",
    last_inventory_at: "2026-11-08T09:00:00Z",
    tags: [],
    runner_helpers: [],
    ...extra,
  };
}

/** A page of `items` after the opaque cursor `p-<start>`. */
export function pageOf<T>(
  items: readonly T[],
  cursor: string | undefined,
  size: number,
): { items: T[]; next_cursor: string | null } {
  const start = cursor === undefined ? 0 : Number(cursor.slice(2));
  const end = Math.min(start + size, items.length);
  return {
    items: items.slice(start, end),
    next_cursor: end < items.length ? "p-" + String(end) : null,
  };
}

/** Asserts no element of `root` carries markup from API text. */
export function noInjectedMarkup(root: ParentNode): {
  scripts: number;
  imgs: number;
} {
  return {
    scripts: root.querySelectorAll("script").length,
    imgs: root.querySelectorAll("img").length,
  };
}

/** `items[i]`, failing the test when it is missing (no `!` in tests). */
export function at<T>(items: readonly T[], i: number): T {
  const item = items[i];
  if (item === undefined) {
    throw new Error("no item " + String(i) + " of " + String(items.length));
  }
  return item;
}
