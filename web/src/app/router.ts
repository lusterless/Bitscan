import { useMemo, useSyncExternalStore } from "react";

/** Hash routes only (PD-28 (d)): the manager serves `/` and `/assets/*`, nothing else. */
export type Route =
  | { readonly name: "hosts" }
  | { readonly name: "host"; readonly agentId: string }
  | { readonly name: "packages" }
  | { readonly name: "enrolment-requests" }
  | { readonly name: "enrolment-tokens" }
  | { readonly name: "totp" }
  | { readonly name: "password" };

export type RouteName = Route["name"];

const HOSTS: Route = Object.freeze({ name: "hosts" });
const PACKAGES: Route = Object.freeze({ name: "packages" });
const ENROLMENT_REQUESTS: Route = Object.freeze({ name: "enrolment-requests" });
const ENROLMENT_TOKENS: Route = Object.freeze({ name: "enrolment-tokens" });
const TOTP: Route = Object.freeze({ name: "totp" });
const PASSWORD: Route = Object.freeze({ name: "password" });

const HOST_PREFIX = "/hosts/";

function isHex(ch: string): boolean {
  return (
    (ch >= "0" && ch <= "9") ||
    (ch >= "a" && ch <= "f") ||
    (ch >= "A" && ch <= "F")
  );
}

/** The hyphenated 8-4-4-4-12 form only, checked without a regular expression. */
export function isUuid(value: string): boolean {
  if (value.length !== 36) {
    return false;
  }
  for (let i = 0; i < 36; i++) {
    const ch = value.charAt(i);
    const hyphen = i === 8 || i === 13 || i === 18 || i === 23;
    if (hyphen ? ch !== "-" : !isHex(ch)) {
      return false;
    }
  }
  return true;
}

/** Anything unknown or malformed (extra segments, a query, a bad id) is the host list. */
export function parseHash(hash: string): Route {
  const path = hash.startsWith("#") ? hash.slice(1) : hash;
  switch (path) {
    case "":
    case "/":
    case "/hosts":
      return HOSTS;
    case "/packages":
      return PACKAGES;
    case "/enrolment/requests":
      return ENROLMENT_REQUESTS;
    case "/enrolment/tokens":
      return ENROLMENT_TOKENS;
    case "/account/totp":
      return TOTP;
    case "/account/password":
      return PASSWORD;
  }
  if (path.startsWith(HOST_PREFIX)) {
    const id = path.slice(HOST_PREFIX.length);
    if (isUuid(id)) {
      return { name: "host", agentId: id.toLowerCase() };
    }
  }
  return HOSTS;
}

export function formatHash(route: Route): string {
  switch (route.name) {
    case "hosts":
      return "#/hosts";
    case "host":
      return "#" + HOST_PREFIX + route.agentId;
    case "packages":
      return "#/packages";
    case "enrolment-requests":
      return "#/enrolment/requests";
    case "enrolment-tokens":
      return "#/enrolment/tokens";
    case "totp":
      return "#/account/totp";
    case "password":
      return "#/account/password";
    default: {
      const unhandled: never = route;
      return unhandled;
    }
  }
}

export function navigate(route: Route): void {
  window.location.hash = formatHash(route);
}

function subscribe(listener: () => void): () => void {
  window.addEventListener("hashchange", listener);
  return () => {
    window.removeEventListener("hashchange", listener);
  };
}

function currentHash(): string {
  return window.location.hash;
}

export function useRoute(): Route {
  // The snapshot is the hash string, so React sees a stable value between changes.
  const hash = useSyncExternalStore(subscribe, currentHash, () => "");
  return useMemo(() => parseHash(hash), [hash]);
}
