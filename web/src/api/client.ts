import createClient from "openapi-fetch";

import type { paths } from "./schema";

// Same origin only: no CORS and a CSP of 'self' (TS §6.3).
export const api = createClient<paths>({ baseUrl: "" });
