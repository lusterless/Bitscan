import { EnrolmentRequests } from "../screens/EnrolmentRequests";
import { EnrolmentTokens } from "../screens/EnrolmentTokens";
import { HostDetail } from "../screens/HostDetail";
import { Hosts } from "../screens/Hosts";
import { PackageSearch } from "../screens/PackageSearch";
import { PasswordChange } from "../screens/PasswordChange";
import { TotpEnrol } from "../screens/TotpEnrol";
import type { IconName } from "../components/Icon";
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

/** The sidebar sections, in display order. */
export type NavGroup = "Fleet" | "Enrolment" | "Account";

export const NAV_GROUPS: readonly NavGroup[] = Object.freeze([
  "Fleet",
  "Enrolment",
  "Account",
]);

export interface NavEntry {
  readonly route: Route;
  readonly label: string;
  readonly group: NavGroup;
  readonly icon: IconName;
}

const NAV: readonly NavEntry[] = Object.freeze([
  { route: { name: "hosts" }, label: "Hosts", group: "Fleet", icon: "hosts" },
  {
    route: { name: "packages" },
    label: "Package search",
    group: "Fleet",
    icon: "packages",
  },
  {
    route: { name: "enrolment-requests" },
    label: "Enrolment requests",
    group: "Enrolment",
    icon: "requests",
  },
  {
    route: { name: "enrolment-tokens" },
    label: "Enrolment tokens",
    group: "Enrolment",
    icon: "tokens",
  },
  { route: { name: "totp" }, label: "TOTP", group: "Account", icon: "totp" },
  {
    route: { name: "password" },
    label: "Password",
    group: "Account",
    icon: "password",
  },
]);

export function navFor(role: Role): readonly NavEntry[] {
  return NAV.filter((entry) => isAllowed(entry.route.name, role));
}

/** The nav entry a route belongs to; a host page belongs to Hosts. */
export function entryFor(route: Route): NavEntry | null {
  const name = route.name === "host" ? "hosts" : route.name;
  return NAV.find((entry) => entry.route.name === name) ?? null;
}

const HOSTS: Route = Object.freeze({ name: "hosts" });

function NotAvailable() {
  return (
    <main aria-label="Not available" className="page page-narrow">
      <div className="card empty-state">
        <h1>Not available</h1>
        <p>This page is not available for your role.</p>
      </div>
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
