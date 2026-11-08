// TASK-256 TEST (TP-M11-14): CHK-M11-275, plant CHK-M11-375 (table half).
// Expected values: #145 (a) (scan item fields; state is scan.state);
// TS §4.4 L582 (the six scan states); TS §6.3 L1141 (RFC 3339 UTC),
// L1143 (plain text).
import "../test/harness";
import {
  SCRIPT,
  IMG,
  mockLinks,
  noInjectedMarkup,
  scanItem,
  uuid,
  at,
} from "../test/m11";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatTime } from "../format";
import {
  SCAN_STATES,
  ScanStateBadge,
  ScanTable,
  scanStateLabel,
} from "./ScanTable";

function cells(row: HTMLElement): string[] {
  return Array.from(row.querySelectorAll("td")).map((td) =>
    (td.textContent ?? "").replace(/\s+/g, " ").trim(),
  );
}

describe("CHK-M11-275 ScanStateBadge", () => {
  it("offers exactly the six scan states", () => {
    expect([...SCAN_STATES].sort()).toEqual([
      "cancelled",
      "completed",
      "failed",
      "partial",
      "queued",
      "running",
    ]);
  });

  it("each state has its own label", () => {
    const labels = SCAN_STATES.map(scanStateLabel);
    expect(new Set(labels).size).toBe(6);
    expect(scanStateLabel("partial")).toBe("Partial");
    expect(scanStateLabel("cancelled")).toBe("Cancelled");
    for (const s of SCAN_STATES) {
      const { container, unmount } = render(<ScanStateBadge state={s} />);
      expect(container.textContent).toBe(scanStateLabel(s));
      unmount();
    }
  });
});

describe("CHK-M11-275 ScanTable", () => {
  it("one row per scan with its fields, linking to the detail via ScanLinks", () => {
    const links = mockLinks();
    const items = [
      scanItem(1),
      scanItem(2, {
        trigger: "scheduled",
        schedule_id: 4,
        state: "running",
        target_kind: "tags",
        resolved_count: 12,
        finished_at: null,
        policy_version: 9,
      }),
    ];
    render(<ScanTable items={items} links={links} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(cells(at(rows, 0))).toEqual([
      formatTime("2026-11-01T10:00:00Z"),
      "CIS Ubuntu 24.04 1",
      "3",
      "Manual",
      "All hosts (4 hosts)",
      "Completed",
      formatTime("2026-11-01T10:05:00Z"),
    ]);
    const second = cells(at(rows, 1));
    expect(second.slice(1, 6)).toEqual([
      "CIS Ubuntu 24.04 2",
      "9",
      "Scheduled",
      "Tags (12 hosts)",
      "Running",
    ]);
    const link = at(rows, 1).querySelector("a");
    expect(link?.getAttribute("href")).toBe("#/test-scan/" + uuid(1002));
  });

  it("a <script> policy name renders as text (plant CHK-M11-375)", () => {
    const { container } = render(
      <ScanTable
        items={[
          scanItem(1, { policy_name: SCRIPT }),
          scanItem(2, { policy_name: IMG }),
        ]}
        links={mockLinks()}
      />,
    );
    expect(screen.getByText(SCRIPT)).toBeTruthy();
    expect(screen.getByText(IMG)).toBeTruthy();
    expect(noInjectedMarkup(container)).toEqual({ scripts: 0, imgs: 0 });
  });

  it("an empty list has no body rows (the screens show their own empty text)", () => {
    render(<ScanTable items={[]} links={mockLinks()} />);
    expect(screen.getAllByRole("row")).toHaveLength(1);
  });
});
