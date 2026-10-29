import type { ReactNode } from "react";

export type IconName =
  | "hosts"
  | "packages"
  | "requests"
  | "tokens"
  | "totp"
  | "password"
  | "profiles"
  | "upload"
  | "imports"
  | "rebuild"
  | "sign-out"
  | "menu"
  | "close"
  | "sidebar"
  | "chevron"
  | "back"
  | "download"
  | "search";

// Stroke paths on a 24 x 24 grid. Inline SVG elements only: the CSP
// (`default-src 'self'`) blocks data: URLs, and no <title> is added, so an
// icon adds no text to the link or button around it.
const PATHS: Record<IconName, ReactNode> = {
  hosts: (
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 7.5h.01M7 16.5h.01" />
    </>
  ),
  packages: (
    <>
      <path d="M21 8l-9-5-9 5 9 5 9-5z" />
      <path d="M3 8v8l9 5 9-5V8M12 13v8" />
    </>
  ),
  requests: (
    <>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </>
  ),
  tokens: (
    <>
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="M10.7 12.3L20 3M16 7l3 3M14 9l2 2" />
    </>
  ),
  totp: (
    <>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  password: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  profiles: (
    <>
      <path d="M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1z" />
      <path d="M16 5h2a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2" />
      <path d="M9 13l2 2 4-4" />
    </>
  ),
  upload: (
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
  ),
  imports: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 3" />
    </>
  ),
  rebuild: (
    <>
      <path d="M21 12a9 9 0 0 1-15.5 6.2M3 12a9 9 0 0 1 15.5-6.2" />
      <path d="M18.5 2v4h-4M5.5 22v-4h4" />
    </>
  ),
  "sign-out": (
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
  ),
  menu: <path d="M3 6h18M3 12h18M3 18h18" />,
  close: <path d="M18 6L6 18M6 6l12 12" />,
  sidebar: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </>
  ),
  chevron: <path d="M9 6l6 6-6 6" />,
  back: <path d="M19 12H5M12 19l-7-7 7-7" />,
  download: (
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" />
    </>
  ),
};

export function Icon({ name }: { readonly name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

/** The Bitscan mark: a scan sweep over a host. */
export function Logo() {
  return (
    <svg
      className="logo"
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="32" height="32" rx="8" fill="#16a34a" />
      <circle
        cx="16"
        cy="16"
        r="9"
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeOpacity="0.45"
      />
      <path
        d="M16 7a9 9 0 0 1 9 9"
        fill="none"
        stroke="#fff"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M16 16l6-6"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="16" cy="16" r="2.5" fill="#fff" />
    </svg>
  );
}
