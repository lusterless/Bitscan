import { useMemo, useSyncExternalStore } from "react";

/** Hash routes only (PD-28 (d)): the manager serves `/` and `/assets/*`, nothing else. */
export type Route =
  | { readonly name: "hosts" }
  | { readonly name: "host"; readonly agentId: string }
  | { readonly name: "packages" }
  | { readonly name: "profiles" }
  | { readonly name: "profile"; readonly policyId: string }
  | { readonly name: "policy-upload" }
  | { readonly name: "imports" }
  | { readonly name: "rebuild" }
  | { readonly name: "enrolment-requests" }
  | { readonly name: "enrolment-tokens" }
  | { readonly name: "totp" }
  | { readonly name: "password" }
  | { readonly name: "sessions" }
  | { readonly name: "scans" }
  | { readonly name: "scan"; readonly scanId: string }
  | { readonly name: "scan-results"; readonly scanId: string }
  | { readonly name: "run-scan"; readonly policyId: string | null }
  | { readonly name: "schedules" };

export type RouteName = Route["name"];

const HOSTS: Route = Object.freeze({ name: "hosts" });
const PACKAGES: Route = Object.freeze({ name: "packages" });
const PROFILES: Route = Object.freeze({ name: "profiles" });
const POLICY_UPLOAD: Route = Object.freeze({ name: "policy-upload" });
const IMPORTS: Route = Object.freeze({ name: "imports" });
const REBUILD: Route = Object.freeze({ name: "rebuild" });
const ENROLMENT_REQUESTS: Route = Object.freeze({ name: "enrolment-requests" });
const ENROLMENT_TOKENS: Route = Object.freeze({ name: "enrolment-tokens" });
const TOTP: Route = Object.freeze({ name: "totp" });
const PASSWORD: Route = Object.freeze({ name: "password" });
const SESSIONS: Route = Object.freeze({ name: "sessions" });
const SCANS: Route = Object.freeze({ name: "scans" });
const RUN_SCAN: Route = Object.freeze({ name: "run-scan", policyId: null });
const SCHEDULES: Route = Object.freeze({ name: "schedules" });

const HOST_PREFIX = "/hosts/";
const PROFILE_PREFIX = "/profiles/";
const SCAN_PREFIX = "/scans/";
const RUN_SCAN_PREFIX = "/scans/run/";
const RESULTS_SUFFIX = "/results";

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

/**
 * A catalog key (TS §6.3 L1139) as the API's path pattern takes it: 1 to 20
 * ASCII digits. It stays a string, so an id above 2^53 is not rounded.
 */
export function isPolicyId(value: string): boolean {
  if (value.length < 1 || value.length > 20) {
    return false;
  }
  for (const ch of value) {
    if (ch < "0" || ch > "9") {
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
    case "/profiles":
      return PROFILES;
    case "/catalog/upload":
      return POLICY_UPLOAD;
    case "/catalog/imports":
      return IMPORTS;
    case "/catalog/rebuild":
      return REBUILD;
    case "/enrolment/requests":
      return ENROLMENT_REQUESTS;
    case "/enrolment/tokens":
      return ENROLMENT_TOKENS;
    case "/account/totp":
      return TOTP;
    case "/account/password":
      return PASSWORD;
    case "/account/sessions":
      return SESSIONS;
    case "/scans":
      return SCANS;
    case "/scans/run":
      return RUN_SCAN;
    case "/schedules":
      return SCHEDULES;
  }
  if (path.startsWith(HOST_PREFIX)) {
    const id = path.slice(HOST_PREFIX.length);
    if (isUuid(id)) {
      return { name: "host", agentId: id.toLowerCase() };
    }
  }
  if (path.startsWith(PROFILE_PREFIX)) {
    const id = path.slice(PROFILE_PREFIX.length);
    if (isPolicyId(id)) {
      return { name: "profile", policyId: id };
    }
  }
  if (path.startsWith(RUN_SCAN_PREFIX)) {
    const id = path.slice(RUN_SCAN_PREFIX.length);
    return isPolicyId(id) ? { name: "run-scan", policyId: id } : HOSTS;
  }
  if (path.startsWith(SCAN_PREFIX)) {
    const rest = path.slice(SCAN_PREFIX.length);
    const results = rest.endsWith(RESULTS_SUFFIX);
    const id = results ? rest.slice(0, -RESULTS_SUFFIX.length) : rest;
    if (isUuid(id)) {
      const scanId = id.toLowerCase();
      return results
        ? { name: "scan-results", scanId }
        : { name: "scan", scanId };
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
    case "profiles":
      return "#/profiles";
    case "profile":
      return "#" + PROFILE_PREFIX + route.policyId;
    case "policy-upload":
      return "#/catalog/upload";
    case "imports":
      return "#/catalog/imports";
    case "rebuild":
      return "#/catalog/rebuild";
    case "enrolment-requests":
      return "#/enrolment/requests";
    case "enrolment-tokens":
      return "#/enrolment/tokens";
    case "totp":
      return "#/account/totp";
    case "password":
      return "#/account/password";
    case "sessions":
      return "#/account/sessions";
    case "scans":
      return "#/scans";
    case "scan":
      return "#" + SCAN_PREFIX + route.scanId;
    case "scan-results":
      return "#" + SCAN_PREFIX + route.scanId + RESULTS_SUFFIX;
    case "run-scan":
      return route.policyId === null
        ? "#/scans/run"
        : "#" + RUN_SCAN_PREFIX + route.policyId;
    case "schedules":
      return "#/schedules";
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
