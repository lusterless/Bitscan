import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Findings } from "../components/Findings";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type Page = components["schemas"]["Page_ImportItem_"];
type Outcome = components["schemas"]["ImportItem"]["outcome"];

const PAGE_SIZE = 50;

const OUTCOME_TONES: Record<Outcome, string> = {
  success: "badge badge-success",
  skipped: "badge badge-neutral",
  rejected: "badge badge-danger",
};

/**
 * REQ-182 (4): `bit_import` rows, newest first as the server orders them
 * (#98 (h)). File names and findings come from files and stay text nodes.
 */
export function Imports() {
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
      .GET("/api/v1/imports", { params: { query } })
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
          <h1>Import history</h1>
          <p className="page-subtitle">
            Every .bit import, newest first, with its findings.
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
          <p className="empty">No imports yet.</p>
        )}
        {page !== null && page.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>File</th>
                  <th>Mode</th>
                  <th>Outcome</th>
                  <th>Version</th>
                  <th>Plugins added / updated / retired</th>
                  <th>By</th>
                  <th>Imported</th>
                  <th>Findings</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={item.import_id}>
                    <td>{item.import_id}</td>
                    <td className="mono wrap">{item.file_name}</td>
                    <td>{item.mode}</td>
                    <td>
                      <span className={OUTCOME_TONES[item.outcome]}>
                        {item.outcome}
                      </span>
                    </td>
                    <td>{item.policy_version ?? "none"}</td>
                    <td>
                      {item.plugins_added} / {item.plugins_updated} /{" "}
                      {item.plugins_retired}
                    </td>
                    <td>
                      {item.imported_by === null
                        ? "server"
                        : "user " + String(item.imported_by)}
                    </td>
                    <td>{formatTime(item.imported_at)}</td>
                    <td className="wrap">
                      {item.errors.length === 0 ? (
                        "none"
                      ) : (
                        <details>
                          <summary>{item.errors.length} findings</summary>
                          <Findings
                            findings={item.errors}
                            label={
                              "Findings of import " + String(item.import_id)
                            }
                          />
                        </details>
                      )}
                    </td>
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
