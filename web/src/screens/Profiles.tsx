import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type Page = components["schemas"]["Page_PolicyItem_"];
type PolicyStatus = components["schemas"]["PolicyItem"]["policy_status"];

/** #9: the list takes `enabled` or `disabled` only; deleted policies never appear. */
type StatusFilter = PolicyStatus | "all";

const PAGE_SIZE = 50;

// A Record over the generated enum: a new status fails `npm run typecheck`.
const STATUS_LABELS: Record<PolicyStatus, string> = {
  enabled: "Enabled",
  disabled: "Disabled",
};

const STATUS_TONES: Record<PolicyStatus, string> = {
  enabled: "badge badge-success",
  disabled: "badge badge-neutral",
};

function toFilter(value: string): StatusFilter {
  return value === "enabled" || value === "disabled" ? value : "all";
}

export interface ProfilesProps {
  /** Opens a profile's detail; the route is wired in TASK-173. */
  readonly onOpen?: (policyId: number) => void;
}

/**
 * REQ-181: every role sees the compliance profiles (TS §4.3). Every value
 * from the API is rendered as a text node (TS §6.3); there is no HTML path.
 */
export function Profiles({ onOpen }: ProfilesProps) {
  const pages = useCursorPages();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    const query: {
      limit: number;
      cursor?: string;
      status?: PolicyStatus;
    } = { limit: PAGE_SIZE };
    if (pages.cursor !== null) query.cursor = pages.cursor;
    if (status !== "all") query.status = status;
    api
      .GET("/api/v1/policies", { params: { query } })
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
  }, [pages.cursor, status]);

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Profiles</h1>
          <p className="page-subtitle">
            Compliance profiles loaded from <span className="mono">.bit</span>{" "}
            files. Each policy is one selectable profile.
          </p>
        </div>
      </div>
      <form
        aria-label="Filter profiles"
        className="card filters"
        onSubmit={(event) => {
          event.preventDefault();
        }}
      >
        <fieldset className="filter-group filter-group-last">
          <legend>Filter</legend>
          <label>
            Status
            <select
              value={status}
              onChange={(event) => {
                setStatus(toFilter(event.target.value));
                pages.reset();
              }}
            >
              <option value="all">all</option>
              <option value="enabled">enabled</option>
              <option value="disabled">disabled</option>
            </select>
          </label>
        </fieldset>
      </form>
      {unreachable && (
        <p role="alert" className="callout callout-danger">
          The manager is unavailable. Try again later.
        </p>
      )}
      <ProblemBanner problem={problem} />
      <div className="card card-flush">
        {page === null && !unreachable && problem === null && (
          <p className="empty">Loading.</p>
        )}
        {page !== null && page.items.length === 0 && (
          <p className="empty">No profiles.</p>
        )}
        {page !== null && page.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Status</th>
                  <th>Family</th>
                  <th>Version</th>
                  <th>Plugins</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((policy) => (
                  <tr key={policy.policy_id}>
                    <td className="wrap">
                      {onOpen === undefined ? (
                        policy.policy_name
                      ) : (
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => {
                            onOpen(policy.policy_id);
                          }}
                        >
                          {policy.policy_name}
                        </button>
                      )}
                    </td>
                    <td className="wrap">{policy.policy_description}</td>
                    <td>
                      <span className={STATUS_TONES[policy.policy_status]}>
                        {STATUS_LABELS[policy.policy_status]}
                      </span>
                      {policy.status_overridden && (
                        <span className="muted"> (set by an admin)</span>
                      )}
                    </td>
                    <td className="wrap">{policy.family_name}</td>
                    <td>{policy.version}</td>
                    <td>{policy.plugin_count}</td>
                    <td>{formatTime(policy.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
        </div>
      </div>
    </main>
  );
}
