import { EnrolmentRequests } from "../screens/EnrolmentRequests";
import { EnrolmentTokens } from "../screens/EnrolmentTokens";
import { HostDetail } from "../screens/HostDetail";
import { Hosts } from "../screens/Hosts";
import { PackageSearch } from "../screens/PackageSearch";
import { PasswordChange } from "../screens/PasswordChange";
import { TotpEnrol } from "../screens/TotpEnrol";
import { navigate, type Route, type RouteName } from "./router";
import type { Role } from "./session";

const EVERYONE: readonly Role[] = Object.freeze([
  "viewer",
  "operator",
  "admin",
]);
const ADMIN: readonly Role[] = Object.freeze(["admin"]);

/**
 * REQ-133: the roles that may open each route. This only decides what the UI
 * offers; the server still enforces every rule (TS §6.2).
 */
export const ROUTE_ROLES: Readonly<Record<RouteName, readonly Role[]>> =
  Object.freeze({
    hosts: EVERYONE,
    host: EVERYONE,
    packages: EVERYONE,
    "enrolment-requests": ADMIN,
    "enrolment-tokens": ADMIN,
    totp: EVERYONE,
    password: EVERYONE,
  });

export function isAllowed(name: RouteName, role: Role): boolean {
  return ROUTE_ROLES[name].includes(role);
}

export interface NavEntry {
  readonly route: Route;
  readonly label: string;
}

const NAV: readonly NavEntry[] = Object.freeze([
  { route: { name: "hosts" }, label: "Hosts" },
  { route: { name: "packages" }, label: "Package search" },
  { route: { name: "enrolment-requests" }, label: "Enrolment requests" },
  { route: { name: "enrolment-tokens" }, label: "Enrolment tokens" },
  { route: { name: "totp" }, label: "TOTP" },
  { route: { name: "password" }, label: "Password" },
]);

export function navFor(role: Role): readonly NavEntry[] {
  return NAV.filter((entry) => isAllowed(entry.route.name, role));
}

const HOSTS: Route = Object.freeze({ name: "hosts" });

function NotAvailable() {
  return (
    <main aria-label="Not available">
      <h1>Not available</h1>
      <p>This page is not available for your role.</p>
    </main>
  );
}

export interface RouteViewProps {
  readonly route: Route;
  readonly role: Role;
  /** PasswordChange has already cleared the session when this is called. */
  readonly onPasswordChanged: () => void;
}

/**
 * The screen for a route. A route the role may not open renders only the
 * role page, so its screen is never mounted and sends no request.
 */
export function RouteView({ route, role, onPasswordChanged }: RouteViewProps) {
  if (!isAllowed(route.name, role)) {
    return <NotAvailable />;
  }
  switch (route.name) {
    case "hosts":
      return <Hosts navigate={navigate} />;
    case "host":
      // A new key per host, so another host starts on its first package page.
      return (
        <HostDetail
          key={route.agentId}
          agentId={route.agentId}
          navigate={navigate}
        />
      );
    case "packages":
      return <PackageSearch navigate={navigate} />;
    case "enrolment-requests":
      return <EnrolmentRequests />;
    case "enrolment-tokens":
      return <EnrolmentTokens />;
    case "totp":
      return (
        <TotpEnrol
          mode="manage"
          onDone={() => {
            navigate(HOSTS);
          }}
        />
      );
    case "password":
      return <PasswordChange onChanged={onPasswordChanged} />;
    default: {
      const unhandled: never = route;
      return unhandled;
    }
  }
}
