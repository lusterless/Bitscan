// TASK-117 TEST (TP-M5-10): CHK-M5-190 to CHK-M5-193.
// Expected values: TS §6.3 L1134 (cursor pagination, only next_cursor is
// returned), L1141 (stored text rendered as plain text only); REQ-126 (the
// plan TASK-116 messages; sign in again, never an API token); REQ-127 (null
// times show "never"); TASK-117 interface (Previous/Next in nav "Pages",
// Confirm as an inline alertdialog, formatTime in UTC).
import {
  answer,
  bsu,
  calls,
  loginResponse,
  noContent,
  resetHttp,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { currentSession, setSession } from "../app/session";
import { formatTime } from "../format";
import { Confirm } from "./Confirm";
import { Pager, useCursorPages } from "./Pager";
import { ProblemBanner } from "./ProblemBanner";

function isDisabled(el: HTMLElement): boolean {
  return (el as HTMLButtonElement).disabled;
}

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

beforeEach(() => {
  resetHttp();
});

// ------------------------------------------------------------ CHK-M5-190

/** A fake server holding `total` items, `size` per page, opaque cursors. */
function server(total: number, size: number) {
  const items = Array.from({ length: total }, (_, i) => "item-" + String(i));
  const asked: (string | null)[] = [];
  const issued = new Set<string>();
  return {
    asked,
    issued,
    page(cursor: string | null): {
      items: string[];
      next_cursor: string | null;
    } {
      asked.push(cursor);
      if (cursor !== null && !issued.has(cursor)) {
        throw new Error("a cursor the server never issued: " + cursor);
      }
      const start = cursor === null ? 0 : Number(cursor.slice(7));
      const end = Math.min(start + size, total);
      let next: string | null = null;
      if (end < total) {
        next = "opaque-" + String(end);
        issued.add(next);
      }
      return { items: items.slice(start, end), next_cursor: next };
    },
  };
}

function List({ srv }: { srv: ReturnType<typeof server> }) {
  const pages = useCursorPages();
  const [page, setPage] = useState<{
    items: string[];
    next_cursor: string | null;
  }>({
    items: [],
    next_cursor: null,
  });
  useEffect(() => {
    setPage(srv.page(pages.cursor));
  }, [pages.cursor, srv]);
  return (
    <div>
      <ul aria-label="Items">
        {page.items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
      <Pager pages={pages} nextCursor={page.next_cursor} />
      <button type="button" onClick={pages.reset}>
        Reset
      </button>
    </div>
  );
}

function shown(): string[] {
  return within(screen.getByRole("list", { name: "Items" }))
    .queryAllByRole("listitem")
    .map((li) => li.textContent ?? "");
}

function buttons() {
  const nav = screen.getByRole("navigation", { name: "Pages" });
  return {
    previous: within(nav).getByRole("button", { name: "Previous" }),
    next: within(nav).getByRole("button", { name: "Next" }),
  };
}

describe("CHK-M5-190 Pager walks N + 1 items with page size N", () => {
  it.each([1, 2, 3, 5])("N = %i, forwards then back", (n) => {
    const srv = server(n + 1, n);
    render(<List srv={srv} />);
    const firstPage = shown();
    expect(firstPage).toHaveLength(n);
    expect(isDisabled(buttons().previous)).toBe(true);
    expect(isDisabled(buttons().next)).toBe(false);
    fireEvent.click(buttons().next);
    expect(shown()).toEqual(["item-" + String(n)]);
    expect(isDisabled(buttons().next)).toBe(true);
    expect(isDisabled(buttons().previous)).toBe(false);
    const all = [...firstPage, ...shown()];
    expect(new Set(all).size).toBe(n + 1);
    fireEvent.click(buttons().previous);
    expect(shown()).toEqual(firstPage);
    expect(isDisabled(buttons().previous)).toBe(true);
    // Only cursors the server returned, and null for the first page.
    for (const c of srv.asked) {
      expect(c === null || srv.issued.has(c)).toBe(true);
    }
    expect(srv.asked.at(-1)).toBeNull();
  });

  it("a long walk shows each item once, and back retraces every page", () => {
    const srv = server(10, 3);
    render(<List srv={srv} />);
    const pagesSeen: string[][] = [shown()];
    // Bounded: a pager that never ends must fail, not hang.
    for (let i = 0; i < 10 && !isDisabled(buttons().next); i++) {
      fireEvent.click(buttons().next);
      pagesSeen.push(shown());
    }
    expect(isDisabled(buttons().next)).toBe(true);
    expect(pagesSeen.flat()).toEqual(
      Array.from({ length: 10 }, (_, i) => "item-" + String(i)),
    );
    for (let i = pagesSeen.length - 2; i >= 0; i--) {
      fireEvent.click(buttons().previous);
      expect(shown()).toEqual(pagesSeen[i]);
    }
    expect(isDisabled(buttons().previous)).toBe(true);
  });

  it("reset goes back to the first page", () => {
    const srv = server(7, 2);
    render(<List srv={srv} />);
    fireEvent.click(buttons().next);
    fireEvent.click(buttons().next);
    expect(shown()).toEqual(["item-4", "item-5"]);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(shown()).toEqual(["item-0", "item-1"]);
    expect(isDisabled(buttons().previous)).toBe(true);
  });

  it("a single page has both buttons disabled; disabled disables both", () => {
    const pages = {
      cursor: null,
      hasPrevious: true,
      next: vi.fn(),
      previous: vi.fn(),
      reset: vi.fn(),
    };
    const { rerender } = render(
      <Pager pages={pages} nextCursor="c" disabled />,
    );
    expect(isDisabled(buttons().previous)).toBe(true);
    expect(isDisabled(buttons().next)).toBe(true);
    rerender(
      <Pager pages={{ ...pages, hasPrevious: false }} nextCursor={null} />,
    );
    expect(isDisabled(buttons().previous)).toBe(true);
    expect(isDisabled(buttons().next)).toBe(true);
    rerender(<Pager pages={pages} nextCursor="c-77" />);
    fireEvent.click(buttons().next);
    expect(pages.next).toHaveBeenCalledWith("c-77");
    fireEvent.click(buttons().previous);
    expect(pages.previous).toHaveBeenCalledTimes(1);
  });
});

// ------------------------------------------------------------ CHK-M5-191

function info(status: number, type: string, detail: string | null = null) {
  return { status, type, detail, retryAfterS: null };
}

describe("CHK-M5-191 ProblemBanner", () => {
  it("renders nothing for null", () => {
    const { container } = render(<ProblemBanner problem={null} />);
    expect(container.innerHTML).toBe("");
  });

  it.each([
    [info(403, "forbidden"), "Your role does not allow this."],
    [
      info(503, "audit_sink_unavailable"),
      "Sensitive actions are paused while the audit log cannot be shipped. Try again later.",
    ],
    [info(403, "totp_enrolment_required"), "Set up TOTP to continue."],
    [info(401, "unauthorized"), "Your session has ended. Sign in again."],
    [info(503, "about:blank"), "The manager is unavailable. Try again later."],
    [info(400, "invalid_request"), "Request failed (status 400)."],
  ])("shows the REQ-126 message for %j", (p, text) => {
    render(<ProblemBanner problem={p} />);
    expect(screen.getByRole("alert").textContent).toContain(text);
  });

  it("shows a hostile detail as literal text, creating no element", () => {
    const { container } = render(
      <ProblemBanner problem={info(400, "invalid_request", HOSTILE)} />,
    );
    expect(screen.getByText(HOSTILE)).toBeTruthy();
    expect(container.querySelectorAll("img, script")).toHaveLength(0);
  });

  it("totp_session_required: a Sign in again button that signs out, no token field", async () => {
    setSession(loginResponse("admin", true, bsu("S")));
    answer(() => noContent());
    const { container } = render(
      <ProblemBanner
        problem={info(403, "totp_session_required", "need TOTP")}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(
      "This action needs a sign-in with your TOTP code. Sign in again with your password and code.",
    );
    expect(alert.textContent?.toLowerCase()).not.toMatch(/api token|bsk_/);
    expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Sign in again" }));
    });
    await vi.waitFor(() => expect(currentSession()).toBeNull());
    expect(calls.map((c) => c.method + " " + c.path)).toEqual([
      "POST /api/v1/auth/logout",
    ]);
  });

  it("totp_enrolment_required links to the TOTP screen", () => {
    render(<ProblemBanner problem={info(403, "totp_enrolment_required")} />);
    expect(
      screen.getByRole("link", { name: "Set up TOTP" }).getAttribute("href"),
    ).toBe("#/account/totp");
  });

  it("other problems offer no action", () => {
    render(<ProblemBanner problem={info(403, "forbidden", "x")} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

// ------------------------------------------------------------ CHK-M5-192

describe("CHK-M5-192 Confirm", () => {
  it("calls the action only after confirmation, once per confirmation", () => {
    const action = vi.fn();
    render(<Confirm label="Revoke" message={HOSTILE} onConfirm={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(action).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog", { name: "Revoke" });
    expect(within(dialog).getByText(HOSTILE)).toBeTruthy();
    expect(dialog.querySelectorAll("img, script")).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(action).toHaveBeenCalledTimes(2);
  });

  it("never calls it on cancel", () => {
    const action = vi.fn();
    render(
      <Confirm
        label="Reject"
        message="Sure?"
        confirmLabel="Yes, reject"
        onConfirm={action}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("disabled blocks opening and confirming", () => {
    const action = vi.fn();
    const { rerender } = render(
      <Confirm label="Approve" message="m" onConfirm={action} disabled />,
    );
    expect(isDisabled(screen.getByRole("button", { name: "Approve" }))).toBe(
      true,
    );
    rerender(<Confirm label="Approve" message="m" onConfirm={action} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    rerender(
      <Confirm label="Approve" message="m" onConfirm={action} disabled />,
    );
    expect(isDisabled(screen.getByRole("button", { name: "Confirm" }))).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(action).not.toHaveBeenCalled();
  });
});

// ------------------------------------------------------------ CHK-M5-193

describe("CHK-M5-193 formatTime", () => {
  it.each([
    [null, "never"],
    ["2026-10-24T12:03:04Z", "2026-10-24 12:03:04 UTC"],
    ["2026-10-24T12:03:04.123456Z", "2026-10-24 12:03:04 UTC"],
    ["2026-01-02T03:04:05+08:00", "2026-01-01 19:04:05 UTC"],
    ["1999-12-31T23:59:59Z", "1999-12-31 23:59:59 UTC"],
    ["not a time", "not a time"],
    [HOSTILE, HOSTILE],
  ])("%j -> %j", (value, want) => {
    expect(formatTime(value)).toBe(want);
  });

  it("is deterministic whatever the local zone", () => {
    try {
      vi.stubEnv("TZ", "Pacific/Kiritimati");
      const a = formatTime("2026-10-24T23:30:00Z");
      vi.stubEnv("TZ", "America/Adak");
      const b = formatTime("2026-10-24T23:30:00Z");
      expect(new Date("2026-10-24T23:30:00Z").getHours()).not.toBe(23);
      expect(a).toBe("2026-10-24 23:30:00 UTC");
      expect(b).toBe(a);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
