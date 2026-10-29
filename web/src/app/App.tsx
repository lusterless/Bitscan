import { useEffect, useState, type ReactNode } from "react";

import { Icon, Logo } from "../components/Icon";
import { SignIn } from "../screens/SignIn";
import { TotpEnrol } from "../screens/TotpEnrol";
import { formatHash, navigate, useRoute, type Route } from "./router";
import {
  entryFor,
  NAV_GROUPS,
  navFor,
  RouteView,
  type NavGroup,
} from "./routes";
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
      className="btn btn-ghost"
      onClick={() => {
        // signOut() clears the session even when logout fails (REQ-120 (4)).
        void signOut();
      }}
    >
      <Icon name="sign-out" />
      Sign out
    </button>
  );
}

/** A detail page (host, profile) marks its list's entry. */
function isActive(entry: Route, route: Route): boolean {
  return entryFor(route)?.route.name === entry.name;
}

function crumbLabel(route: Route, label: string): string {
  if (route.name === "host") return "Host detail";
  return route.name === "profile" ? "Profile detail" : label;
}

const ROLE_LABELS: Record<Role, string> = {
  viewer: "Viewer",
  operator: "Operator",
  admin: "Admin",
};

function Brand() {
  return (
    <span className="brand">
      <Logo />
      <span className="brand-name">Bitscan</span>
    </span>
  );
}

/**
 * Sign-in and the TOTP-only screens: no navigation at all (TS §6.2 L1089),
 * just the brand and the screen in a centred card.
 */
function AuthLayout({
  children,
  signOut: withSignOut = false,
}: {
  readonly children: ReactNode;
  readonly signOut?: boolean;
}) {
  return (
    <div className="auth">
      <div className="auth-panel">
        <div className="auth-brand">
          <Brand />
          {withSignOut && <SignOutButton />}
        </div>
        <div className="auth-card">{children}</div>
        <p className="auth-foot">
          Fleet inventory and compliance for Ubuntu hosts
        </p>
      </div>
    </div>
  );
}

function Sidebar({
  role,
  route,
  collapsed,
  open,
  onToggleCollapsed,
  onClose,
}: {
  readonly role: Role;
  readonly route: Route;
  readonly collapsed: boolean;
  readonly open: boolean;
  readonly onToggleCollapsed: () => void;
  readonly onClose: () => void;
}) {
  // Every section starts open; the state lives in memory only.
  const [closed, setClosed] = useState<ReadonlySet<NavGroup>>(new Set());
  const entries = navFor(role);
  const classes =
    "sidebar" + (collapsed ? " is-collapsed" : "") + (open ? " is-open" : "");
  return (
    <aside id="sidebar" className={classes}>
      <div className="sidebar-head">
        <Brand />
        <button
          type="button"
          className="icon-btn sidebar-collapse"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
          onClick={onToggleCollapsed}
        >
          <Icon name="sidebar" />
        </button>
        <button
          type="button"
          className="icon-btn sidebar-close"
          aria-label="Close menu"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <nav aria-label="Main" className="sidebar-nav">
        {NAV_GROUPS.map((group) => {
          const items = entries.filter((entry) => entry.group === group);
          if (items.length === 0) return null;
          const expanded = collapsed || !closed.has(group);
          const listId = "nav-" + group.toLowerCase();
          return (
            <div
              key={group}
              className={
                "nav-group" + (group === "Account" ? " nav-group-last" : "")
              }
            >
              <button
                type="button"
                className="nav-group-toggle"
                aria-expanded={expanded}
                aria-controls={listId}
                onClick={() => {
                  setClosed((now) => {
                    const next = new Set(now);
                    if (next.has(group)) next.delete(group);
                    else next.add(group);
                    return next;
                  });
                }}
              >
                <span>{group}</span>
                <Icon name="chevron" />
              </button>
              {expanded && (
                <ul id={listId} className="nav-list">
                  {items.map((entry) => (
                    <li key={entry.route.name}>
                      <a
                        className="nav-link"
                        href={formatHash(entry.route)}
                        title={collapsed ? entry.label : undefined}
                        aria-current={
                          isActive(entry.route, route) ? "page" : undefined
                        }
                        onClick={onClose}
                      >
                        <Icon name={entry.icon} />
                        <span className="nav-label">{entry.label}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}

function Shell({
  role,
  route,
  children,
}: {
  readonly role: Role;
  readonly route: Route;
  readonly children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState(false);
  const entry = entryFor(route);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={"app" + (collapsed ? " is-collapsed" : "")}>
      <Sidebar
        role={role}
        route={route}
        collapsed={collapsed}
        open={open}
        onToggleCollapsed={() => {
          setCollapsed((c) => !c);
        }}
        onClose={() => {
          setOpen(false);
        }}
      />
      {open && (
        <button
          type="button"
          className="backdrop"
          aria-label="Close menu"
          tabIndex={-1}
          onClick={() => {
            setOpen(false);
          }}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn menu-btn"
            aria-label="Open menu"
            aria-controls="sidebar"
            aria-expanded={open}
            onClick={() => {
              setOpen(true);
            }}
          >
            <Icon name="menu" />
          </button>
          <span className="crumbs">
            {entry !== null && (
              <>
                <span className="crumb-group">{entry.group}</span>
                <Icon name="chevron" />
                <span className="crumb-page">
                  {crumbLabel(route, entry.label)}
                </span>
              </>
            )}
          </span>
          <span className="topbar-actions">
            <span className="role-chip">{ROLE_LABELS[role]}</span>
            <SignOutButton />
          </span>
        </header>
        {/* Each screen renders its own <main>, so the shell does not. */}
        <div className="content">{children}</div>
      </div>
    </div>
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
      <AuthLayout>
        <SignIn
          onSignedIn={() => {
            setPasswordChanged(false);
            goToHosts();
          }}
          {...noticeProps}
        />
      </AuthLayout>
    );
  }

  const next = nextScreen(session);
  if (next === "totp-required") {
    // TS §6.2 L1089: an admin without TOTP gets only TOTP and sign-out.
    return (
      <AuthLayout signOut>
        <TotpEnrol mode="required" onDone={goToHosts} />
      </AuthLayout>
    );
  }
  if (next === "totp-offer" && offerSkipped !== session) {
    // #85 (a): offered after every sign-in; "Not now" leads to the host list.
    return (
      <AuthLayout signOut>
        <TotpEnrol
          mode="offer"
          onDone={goToHosts}
          onSkip={() => {
            setOfferSkipped(session);
            goToHosts();
          }}
        />
      </AuthLayout>
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
