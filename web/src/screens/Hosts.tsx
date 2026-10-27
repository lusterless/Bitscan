import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { StatusBadge } from "../components/StatusBadge";
import { formatTime } from "../format";

type Page = components["schemas"]["Page_AgentItem_"];

export interface HostsProps {
  readonly navigate: (route: Route) => void;
}

const PAGE_SIZE = 50;

function list(values: readonly string[]): string {
  return values.length === 0 ? "none" : values.join(", ");
}

/** REQ-127: every value from the API is rendered as a text node. */
export function Hosts({ navigate }: HostsProps) {
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    const query =
      pages.cursor === null
        ? { limit: PAGE_SIZE }
        : { limit: PAGE_SIZE, cursor: pages.cursor };
    api
      .GET("/api/v1/agents", { params: { query } })
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
  }, [pages.cursor]);

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Hosts</h1>
          <p className="page-subtitle">
            Enrolled agents, their status and their last check-in. Select a
            hostname for its inventory.
          </p>
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
          <p className="empty">No hosts yet.</p>
        )}
        {page !== null && page.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Hostname</th>
                  <th>Status</th>
                  <th>OS</th>
                  <th>Agent version</th>
                  <th>Last heartbeat</th>
                  <th>Last inventory</th>
                  <th>Tags</th>
                  <th>Runner helpers</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((host) => {
                  const route: Route = { name: "host", agentId: host.agent_id };
                  return (
                    <tr key={host.agent_id}>
                      <td>
                        <a
                          className="strong-link"
                          href={formatHash(route)}
                          onClick={(event) => {
                            event.preventDefault();
                            navigate(route);
                          }}
                        >
                          {host.hostname}
                        </a>
                      </td>
                      <td>
                        <StatusBadge status={host.status} />
                      </td>
                      <td className="wrap">
                        {host.os_pretty_name ?? "unknown"}
                      </td>
                      <td className="mono">{host.agent_version}</td>
                      <td>{formatTime(host.last_heartbeat_at)}</td>
                      <td>{formatTime(host.last_inventory_at)}</td>
                      <td className="wrap">{list(host.tags)}</td>
                      <td className="wrap">{list(host.runner_helpers)}</td>
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
