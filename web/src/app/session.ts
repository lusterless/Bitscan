import { useSyncExternalStore } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";

type LoginResponse = components["schemas"]["LoginResponse"];
type CurrentSession = components["schemas"]["CurrentSession"];

export type Role = "viewer" | "operator" | "admin";

/** What screens may read. The UI never holds the session token. */
export interface SessionView {
  readonly role: Role;
  readonly totpEnrolled: boolean;
  readonly totpVerified: boolean;
  readonly expiresAt: string;
}

export type NextScreen = "totp-required" | "totp-offer" | "hosts";

/** "restoring" while the start-up check of the session cookie runs. */
export type SessionStatus = "restoring" | "ready";

// The bsu_ token lives only in the __Host-bitscan_session cookie, which is
// HttpOnly: no script, this one included, can read it (TS §6.2, §8.1). The
// browser sends it with every same-origin request. This module keeps only
// the token-free view, so a reload restores the view from GET /auth/session.
let current: SessionView | null = null;
let status: SessionStatus = "ready";
// Bumped whenever the session changes, so a late 401 for a request sent
// under an earlier session (before a sign-in or a TOTP confirm) is ignored.
let generation = 0;
const sentUnder = new WeakMap<Request, number>();
const listeners = new Set<() => void>();

/** TS §6.3: every cookie-authenticated request carries this header. */
export const CSRF_HEADER = "X-Bitscan-Request";

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

/** The role is a plain string in the contract (PD-29); unknown means least privilege. */
export function toRole(value: string): Role {
  switch (value) {
    case "admin":
    case "operator":
    case "viewer":
      return value;
    default:
      return "viewer";
  }
}

function replace(view: SessionView | null): void {
  current = view;
  generation += 1;
  notify();
}

function viewOf(response: LoginResponse | CurrentSession): SessionView {
  return Object.freeze({
    role: toRole(response.role),
    totpEnrolled: response.totp_enrolled,
    totpVerified: response.totp_verified,
    expiresAt: response.expires_at,
  });
}

/**
 * Sign-in and the TOTP confirm both answer a LoginResponse and set the
 * cookie; the view replaces any old session. The body's token is ignored.
 */
export function setSession(response: LoginResponse): void {
  replace(viewOf(response));
}

export function clearSession(): void {
  if (current === null) {
    return;
  }
  replace(null);
}

export function currentSession(): SessionView | null {
  return current;
}

export function sessionStatus(): SessionStatus {
  return status;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useSession(): SessionView | null {
  return useSyncExternalStore(subscribe, currentSession, currentSession);
}

export function useSessionStatus(): SessionStatus {
  return useSyncExternalStore(subscribe, sessionStatus, sessionStatus);
}

/**
 * Start-up (and reload): asks the manager whether the cookie still holds a
 * session. 200 restores the view; 403 totp_enrolment_required is an admin
 * session that must enrol TOTP first (TS §6.2), shown as such; anything else,
 * a network failure included, starts signed out.
 */
export async function restoreSession(): Promise<void> {
  status = "restoring";
  notify();
  const before = generation;
  try {
    const { data, error, response } = await api.GET("/api/v1/auth/session");
    if (generation !== before) {
      return; // signed in or out meanwhile: that wins
    }
    if (data !== undefined) {
      replace(viewOf(data));
    } else if (
      response.status === 403 &&
      typeof error === "object" &&
      error !== null &&
      (error as { type?: unknown }).type === "totp_enrolment_required"
    ) {
      replace(
        Object.freeze({
          role: "admin" as const,
          totpEnrolled: false,
          totpVerified: false,
          expiresAt: "",
        }),
      );
    }
  } catch {
    // Unreachable manager: start signed out; nothing is logged.
  } finally {
    status = "ready";
    notify();
  }
}

/** #85 (a): admins must enrol TOTP; others are offered it after every sign-in. */
export function nextScreen(view: SessionView): NextScreen {
  if (!view.totpEnrolled) {
    return view.role === "admin" ? "totp-required" : "totp-offer";
  }
  return "hosts";
}

/** Ends the UI session even when the logout call fails or is refused. */
export async function signOut(): Promise<void> {
  try {
    await api.POST("/api/v1/auth/logout");
  } catch {
    // A network failure must not keep the UI signed in; nothing is logged.
  } finally {
    clearSession();
  }
}

api.use({
  onRequest({ request }) {
    request.headers.set(CSRF_HEADER, "1");
    sentUnder.set(request, generation);
    return request;
  },
  onResponse({ request, response }) {
    // Only a 401 for the session in use ends it: a late 401 for a request
    // sent before a sign-in or a TOTP confirm replaced the session must not.
    if (
      response.status === 401 &&
      current !== null &&
      sentUnder.get(request) === generation
    ) {
      clearSession();
    }
    return response;
  },
});
