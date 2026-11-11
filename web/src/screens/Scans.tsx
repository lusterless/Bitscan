import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components, operations } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { isUuid } from "../app/router";
import type { Role } from "../app/session";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import {
  SCAN_STATES,
  ScanTable,
  scanStateLabel,
  type ScanLinks,
  type ScanState,
} from "../components/ScanTable";

type Page = components["schemas"]["Page_ScanItem_"];
type Policy = components["schemas"]["PolicyItem"];
type Query = NonNullable<
  operations["list_scans_api_v1_scans_get"]["parameters"]["query"]
>;
const PAGE_SIZE = 50;
const UNAVAILABLE = "The manager is unavailable. Try again later.";

function toState(value: string): ScanState | null {
  return SCAN_STATES.find((state) => state === value) ?? null;
}

interface Filters {
  readonly policyId: string;
  readonly agentId: string;
  readonly state: string;
  readonly after: string;
  readonly before: string;
}

const NO_FILTERS: Filters = {
  policyId: "",
  agentId: "",
  state: "",
  after: "",
  before: "",
};

/** A `YYYY-MM-DD` date input as midnight UTC, RFC 3339 with an offset. */
function dayStart(day: string): string | null {
  const value = day + "T00:00:00Z";
  return day.length === 10 && !Number.isNaN(Date.parse(value)) ? value : null;
}

/** The REQ-264 query for the filters, or null when one is malformed. */
function toQuery(filters: Filters): Query | null {
  const query: Query = {};
  if (filters.policyId !== "") query.policy_id = Number(filters.policyId);
  if (filters.agentId !== "") {
    if (!isUuid(filters.agentId.trim())) return null;
    query.agent_id = filters.agentId.trim().toLowerCase();
  }
  const state = toState(filters.state);
  if (state !== null) query.state = state;
  for (const [day, key] of [
    [filters.after, "created_after"],
    [filters.before, "created_before"],
  ] as const) {
    if (day === "") continue;
    const time = dayStart(day);
    if (time === null) return null;
    query[key] = time;
  }
  return query;
}

export interface ScansProps {
  readonly role: Role;
  readonly links: ScanLinks;
}

/** REQ-279: every role lists scans; operators and admins are offered Run scan. */
export function Scans({ role, links }: ScansProps) {
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [query, setQuery] = useState<Query>({});
  const [invalid, setInvalid] = useState(false);
  const [policies, setPolicies] = useState<readonly Policy[]>([]);
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    // Only for the filter's choices; without it the filter offers "All".
    api
      .GET("/api/v1/policies", { params: { query: { limit: 500 } } })
      .then(({ data }) => {
        if (active && data !== undefined) setPolicies(data.items);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const cursor = pages.cursor === null ? {} : { cursor: pages.cursor };
    api
      .GET("/api/v1/scans", {
        params: { query: { ...query, limit: PAGE_SIZE, ...cursor } },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        setUnreachable(false);
        setPage(data ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setUnreachable(true);
      });
    return () => {
      active = false;
    };
  }, [query, pages.cursor]);

  function apply(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const next = toQuery(draft);
    setInvalid(next === null);
    if (next === null) return;
    setQuery(next);
    pages.reset();
  }

  function field(key: keyof Filters, value: string): void {
    setDraft((old) => ({ ...old, [key]: value }));
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Scans</h1>
          <p className="page-subtitle">
            Compliance scans, newest first. Select a scan for its hosts, score
            and results.
          </p>
        </div>
        {role !== "viewer" && (
          <div className="page-actions">
            <a className="btn btn-primary" href={links.runScanHref}>
              Run scan
            </a>
          </div>
        )}
      </div>
      <form aria-label="Filter scans" className="card filters" onSubmit={apply}>
        <fieldset className="filter-group">
          <legend>Filters</legend>
          <label>
            Profile
            <select
              value={draft.policyId}
              onChange={(event) => {
                field("policyId", event.target.value);
              }}
            >
              <option value="">All</option>
              {policies.map((policy) => (
                <option key={policy.policy_id} value={String(policy.policy_id)}>
                  {policy.policy_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Host id
            <input
              value={draft.agentId}
              onChange={(event) => {
                field("agentId", event.target.value);
              }}
            />
          </label>
          <label>
            State
            <select
              value={draft.state}
              onChange={(event) => {
                field("state", event.target.value);
              }}
            >
              <option value="">All</option>
              {SCAN_STATES.map((state) => (
                <option key={state} value={state}>
                  {scanStateLabel(state)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Created on or after (UTC)
            <input
              type="date"
              value={draft.after}
              onChange={(event) => {
                field("after", event.target.value);
              }}
            />
          </label>
          <label>
            Created before (UTC)
            <input
              type="date"
              value={draft.before}
              onChange={(event) => {
                field("before", event.target.value);
              }}
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-sm">
              Apply
            </button>
          </div>
        </fieldset>
      </form>
      {invalid && (
        <p role="alert" className="callout callout-danger">
          The host id must be a UUID and the dates must be valid.
        </p>
      )}
      {unreachable && (
        <p role="alert" className="callout callout-danger">
          {UNAVAILABLE}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <div className="card card-flush">
        {page === null && !unreachable && problem === null && (
          <p className="empty">Loading.</p>
        )}
        {page !== null && page.items.length === 0 && (
          <p className="empty">No scans.</p>
        )}
        {page !== null && page.items.length > 0 && (
          <ScanTable items={page.items} links={links} />
        )}
        <div className="card-foot">
          <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
        </div>
      </div>
    </main>
  );
}
