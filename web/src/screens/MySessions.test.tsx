// The "My sessions" page (owner decision 2026-11-12).
// Expected values: TS §6.2 (GET /auth/sessions lists the caller's own active
// web sessions; DELETE /auth/sessions/{id} ends one; ending the current one
// signs out), §6.3 (X-Bitscan-Request on every call; plain-text rendering).
import {
  answer,
  bsu,
  calls,
  json,
  loginResponse,
  noContent,
  problem,
  resetHttp,
  type Call,
} from "../test/harness";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, currentSession, setSession } from "../app/session";
import { MySessions } from "./MySessions";

const LIST = "/api/v1/auth/sessions";

function item(id: number, current = false) {
  return {
    session_id: id,
    created_at: "2026-11-12T08:00:00Z",
    last_used_at: "2026-11-12T09:00:00Z",
    expires_at: "2026-11-13T08:00:00Z",
    totp_verified: current,
    current,
  };
}

let rows = [item(3, true), item(5), item(9)];

function server(onDelete: (call: Call) => Response = () => noContent()) {
  answer((call) => {
    if (call.path === LIST && call.method === "GET") {
      return json(200, { items: rows, next_cursor: null });
    }
    if (call.path.startsWith(LIST + "/") && call.method === "DELETE") {
      const id = Number(call.path.slice(LIST.length + 1));
      const reply = onDelete(call);
      if (reply.status === 204) {
        rows = rows.filter((r) => r.session_id !== id);
      }
      return reply;
    }
    return json(599, { type: "unexpected" });
  });
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  resetHttp();
  rows = [item(3, true), item(5), item(9)];
  setSession(loginResponse("viewer", true, bsu("S")));
});

afterEach(() => {
  clearSession();
});

describe("My sessions", () => {
  it("lists the sessions with one GET (limit 500) and marks this one", async () => {
    server();
    render(<MySessions />);
    await settle();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "GET",
      path: LIST,
      authorization: null,
      csrf: "1",
    });
    expect(calls[0]?.query.get("limit")).toBe("500");
    expect(screen.getByText("This session")).toBeTruthy();
    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3
  });

  it("End ends one other session, then lists again", async () => {
    server();
    render(<MySessions />);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "End session 5" }));
    await settle();
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes.map((c) => c.path)).toEqual([LIST + "/5"]);
    expect(deletes[0]?.csrf).toBe("1");
    expect(screen.getByRole("status").textContent).toBe("1 session ended.");
    expect(screen.queryByRole("button", { name: "End session 5" })).toBeNull();
    expect(currentSession()).not.toBeNull();
  });

  it("End all other sessions leaves this one", async () => {
    server();
    render(<MySessions />);
    await settle();
    fireEvent.click(
      screen.getByRole("button", { name: "End all other sessions" }),
    );
    await settle();
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes.map((c) => c.path)).toEqual([LIST + "/5", LIST + "/9"]);
    expect(screen.getByRole("status").textContent).toBe("2 sessions ended.");
    expect(currentSession()).not.toBeNull();
  });

  it("ending this session signs out", async () => {
    server();
    render(<MySessions />);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "End this session" }));
    await settle();
    expect(
      calls.filter((c) => c.method === "DELETE").map((c) => c.path),
    ).toEqual([LIST + "/3"]);
    expect(currentSession()).toBeNull();
  });

  it("a refusal shows the problem and stops", async () => {
    server(() => problem(503, "audit_sink_unavailable"));
    render(<MySessions />);
    await settle();
    fireEvent.click(
      screen.getByRole("button", { name: "End all other sessions" }),
    );
    await settle();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
    expect(screen.queryByRole("status")).toBeNull();
    expect(currentSession()).not.toBeNull();
  });

  it("with only this session, End all other sessions is disabled", async () => {
    rows = [item(3, true)];
    server();
    render(<MySessions />);
    await settle();
    const button = screen.getByRole("button", {
      name: "End all other sessions",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
