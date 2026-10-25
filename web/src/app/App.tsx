import { useState, type ReactNode } from "react";

import { SignIn } from "../screens/SignIn";
import { TotpEnrol } from "../screens/TotpEnrol";
import { formatHash, navigate, useRoute, type Route } from "./router";
import { navFor, RouteView } from "./routes";
import {
  nextScreen,
  signOut,
  useSession,
  type Role,
  type SessionView,
} from "./session";

const HOSTS: Route = Object.freeze({ name: "hosts" });

function goToHosts(): void {
  navigate(HOSTS);
}

function SignOutButton() {
  return (
    <button
      type="button"
      onClick={() => {
        // signOut() clears the session even when logout fails (REQ-120 (4)).
        void signOut();
      }}
    >
      Sign out
    </button>
  );
}

function isActive(entry: Route, route: Route): boolean {
  return (
    entry.name === route.name ||
    (entry.name === "hosts" && route.name === "host")
  );
}

function Shell({
  role,
  route,
  children,
}: {
  readonly role: Role | null;
  readonly route: Route | null;
  readonly children: ReactNode;
}) {
  return (
    <>
      <header>
        <strong>Bitscan</strong>
        {role !== null && route !== null && (
          <nav aria-label="Main">
            <ul>
              {navFor(role).map((entry) => (
                <li key={entry.route.name}>
                  <a
                    href={formatHash(entry.route)}
                    aria-current={
                      isActive(entry.route, route) ? "page" : undefined
                    }
                  >
                    {entry.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        )}
        <SignOutButton />
      </header>
      {/* Each screen renders its own <main>, so the shell does not. */}
      <div>{children}</div>
    </>
  );
}

/**
 * The app shell (REQ-133, REQ-120, REQ-122). The session token stays in
 * session.ts; this component reads only the token-free SessionView.
 */
export function App() {
  const session = useSession();
  const route = useRoute();
  const [passwordChanged, setPasswordChanged] = useState(false);
  // The offer is shown once per signed-in session (a new view per sign-in).
  const [offerSkipped, setOfferSkipped] = useState<SessionView | null>(null);

  if (session === null) {
    // No session (never signed in, signed out, a 401 or a reload): sign-in,
    // whatever the hash says.
    const noticeProps = passwordChanged
      ? { notice: "password-changed" as const }
      : {};
    return (
      <SignIn
        onSignedIn={() => {
          setPasswordChanged(false);
          goToHosts();
        }}
        {...noticeProps}
      />
    );
  }

  const next = nextScreen(session);
  if (next === "totp-required") {
    // TS §6.2 L1089: an admin without TOTP gets only TOTP and sign-out.
    return (
      <Shell role={null} route={null}>
        <TotpEnrol mode="required" onDone={goToHosts} />
      </Shell>
    );
  }
  if (next === "totp-offer" && offerSkipped !== session) {
    // #85 (a): offered after every sign-in; "Not now" leads to the host list.
    return (
      <Shell role={null} route={null}>
        <TotpEnrol
          mode="offer"
          onDone={goToHosts}
          onSkip={() => {
            setOfferSkipped(session);
            goToHosts();
          }}
        />
      </Shell>
    );
  }

  return (
    <Shell role={session.role} route={route}>
      <RouteView
        route={route}
        role={session.role}
        onPasswordChanged={() => {
          setPasswordChanged(true);
        }}
      />
    </Shell>
  );
}
