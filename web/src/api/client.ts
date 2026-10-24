import createClient from "openapi-fetch";

import type { paths } from "./schema";

// Same origin only: no CORS and a CSP of 'self' (TS §6.3). The OpenAPI paths
// already carry the `/api/v1` prefix (TS §6), so `baseUrl` stays empty.
export const api = createClient<paths>({ baseUrl: "" });

// Compile-time recheck of the empty `baseUrl` (REQ-059, rechecked for M3 in
// REQ-089): every path except the health routes, which sit outside `/api/v1`
// (open question #5), must start with `/api/v1/`. The metrics route is
// `/api/v1/metrics` (#70), so `HealthPath` is unchanged. A new path without the
// prefix fails `npm run typecheck` here.
type HealthPath = "/healthz" | "/readyz";
type AssertTrue<T extends true> = T;
export type UserPathsArePrefixed = AssertTrue<
  [Exclude<keyof paths, HealthPath>] extends [`/api/v1/${string}`]
    ? true
    : false
>;
