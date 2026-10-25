import { useSyncExternalStore } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";

type LoginResponse = components["schemas"]["LoginResponse"];

export type Role = "viewer" | "operator" | "admin";

/** What screens may read. The token is deliberately not part of it. */
export interface SessionView {
  readonly role: Role;
  readonly totpEnrolled: boolean;
  readonly totpVerified: boolean;
  readonly expiresAt: string;
}

export type NextScreen = "totp-required" | "totp-offer" | "hosts";

interface Session {
  readonly token: string;
  readonly view: SessionView;
}

// The only place the bsu_ token lives: module memory, never storage, a
// cookie, the URL or the console (TS §6.2, §8.1). A page reload loses it and
// starts signed out (#85 (c)); there is no restore path.
let current: Session | null = null;
const listeners = new Set<() => void>();

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

/** Sign-in and the TOTP confirm both answer a LoginResponse; it replaces any old session. */
export function setSession(response: LoginResponse): void {
  const view: SessionView = Object.freeze({
    role: toRole(response.role),
    totpEnrolled: response.totp_enrolled,
    totpVerified: response.totp_verified,
    expiresAt: response.expires_at,
  });
  current = { token: response.token, view };
  notify();
}

export function clearSession(): void {
  if (current === null) {
    return;
  }
  current = null;
  notify();
}

export function currentSession(): SessionView | null {
  return current === null ? null : current.view;
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

function bearer(session: Session): string {
  return "Bearer " + session.token;
}

api.use({
  onRequest({ request }) {
    if (current !== null) {
      request.headers.set("Authorization", bearer(current));
    }
    return request;
  },
  onResponse({ request, response }) {
    // Only a 401 for the token in use ends the session: a late 401 for a
    // request sent before a TOTP confirm swapped the token must not.
    if (
      response.status === 401 &&
      current !== null &&
      request.headers.get("Authorization") === bearer(current)
    ) {
      clearSession();
    }
    return response;
  },
});
