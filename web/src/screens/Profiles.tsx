import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type Page = components["schemas"]["Page_PolicyItem_"];
type PolicyStatus = components["schemas"]["PolicyItem"]["policy_status"];
/** "all" sends no `status`; the list never holds deleted policies (#9). */
type Filter = PolicyStatus | "all";

export interface ProfilesProps {
  readonly navigate: (route: Route) => void;
}

const PAGE_SIZE = 50;

function toFilter(value: string): Filter {
  return value === "enabled" || value === "disabled" ? value : "all";
}

/** The effective status, and whether an admin's override set it (TS §4.3). */
export function PolicyStatusBadge({
  status,
  overridden,
}: {
  readonly status: PolicyStatus;
  readonly overridden: boolean;
}) {
  const label = status === "enabled" ? "Enabled" : "Disabled";
  return (
    <span
      className={
        status === "enabled" ? "badge badge-success" : "badge badge-neutral"
      }
    >
      {overridden ? label + " (override)" : label}
    </span>
  );
}

/** REQ-181: every value from the API is rendered as a text node. */
export function Profiles({ navigate }: ProfilesProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    const base = filter === "all" ? {} : { status: filter };
    const query =
      pages.cursor === null
        ? { ...base, limit: PAGE_SIZE }
        : { ...base, limit: PAGE_SIZE, cursor: pages.cursor };
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
  }, [filter, pages.cursor]);

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Profiles</h1>
          <p className="page-subtitle">
            Compliance profiles loaded from .bit files. Select a profile for its
            plugins.
          </p>
        </div>
        <div className="page-actions">
          <label className="inline-field">
            Status
            <select
              value={filter}
              onChange={(event) => {
                setFilter(toFilter(event.target.value));
                pages.reset();
              }}
            >
              <option value="all">All</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
        </div>
      </div>
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
                {page.items.map((item) => {
                  const route: Route = {
                    name: "profile",
                    policyId: String(item.policy_id),
                  };
                  return (
                    <tr key={item.policy_id}>
                      <td>
                        <a
                          className="strong-link"
                          href={formatHash(route)}
                          onClick={(event) => {
                            event.preventDefault();
                            navigate(route);
                          }}
                        >
                          {item.policy_name}
                        </a>
                      </td>
                      <td className="wrap">{item.policy_description}</td>
                      <td>
                        <PolicyStatusBadge
                          status={item.policy_status}
                          overridden={item.status_overridden}
                        />
                      </td>
                      <td className="wrap">{item.family_name}</td>
                      <td>{item.version}</td>
                      <td>{item.plugin_count}</td>
                      <td>{formatTime(item.updated_at)}</td>
                    </tr>
                  );
                })}
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
