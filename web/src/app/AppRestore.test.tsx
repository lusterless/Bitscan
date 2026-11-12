// A reload keeps the session (owner decision 2026-11-12; TS §6.2): while the
// start-up GET /auth/session runs the shell shows only "Loading…"; a 200
// opens the hash route signed in; a 401 shows sign-in.
import {
  answer,
  calls,
  deferred,
  json,
  problem,
  resetHttp,
} from "../test/harness";

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { clearSession, currentSession, restoreSession } from "./session";

const CURRENT = {
  role: "viewer",
  totp_enrolled: true,
  totp_verified: true,
  expires_at: "2026-11-13T08:00:00Z",
};

beforeEach(() => {
  resetHttp();
  clearSession();
  window.location.hash = "#/account/sessions";
});

afterEach(() => {
  clearSession();
  window.location.hash = "";
});

describe("start-up restore", () => {
  it("shows Loading… until the answer, then the page the hash names", async () => {
    const pending = deferred();
    answer((call) =>
      call.path === "/api/v1/auth/session"
        ? pending.promise
        : json(200, { items: [], next_cursor: null }),
    );
    const done = restoreSession();
    render(<App />);
    expect(screen.getByRole("status").textContent).toBe("Loading…");
    expect(screen.queryByLabelText("Password")).toBeNull();
    await act(async () => {
      pending.resolve(json(200, CURRENT));
      await done;
    });
    expect(currentSession()?.role).toBe("viewer");
    await vi.waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
        "My sessions",
      ),
    );
    expect(calls[0]?.path).toBe("/api/v1/auth/session");
  });

  it("a 401 shows sign-in", async () => {
    answer(() => problem(401, "unauthorized"));
    const done = restoreSession();
    render(<App />);
    await act(async () => {
      await done;
    });
    expect(currentSession()).toBeNull();
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });
});
