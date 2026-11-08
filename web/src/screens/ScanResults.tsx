import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { downloadResultsCsv, type ResultsCsvQuery } from "../app/download";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { ResultBadge } from "../components/ResultBadge";
import type { ScanLinks } from "../components/ScanTable";
import { formatTime } from "../format";

type Host = components["schemas"]["HostSummary"];
type Item =
  | components["schemas"]["ScanResultItem"]
  | components["schemas"]["ScanResultItemWithOutput"];
type Status = NonNullable<ResultsCsvQuery["status"]>;

const PAGE_SIZE = 50;
const UNAVAILABLE = "The manager is unavailable. Try again later.";
const STATUSES: readonly (readonly [Status, string])[] = [
  ["PASS", "PASS"],
  ["FAIL", "FAIL"],
  ["ERROR", "ERROR"],
  ["NOT_RUN", "Not run"],
];

function toStatus(value: string): Status | null {
  return STATUSES.find(([status]) => status === value)?.[0] ?? null;
}

/** The REQ-267 filters; the CSV export sends the same ones (REQ-281 (3)). */
function toFilters(status: Status | null, agentId: string): ResultsCsvQuery {
  return {
    ...(status === null ? {} : { status }),
    ...(agentId === "" ? {} : { agent_id: agentId }),
  };
}

function flags(item: Item): string {
  const set = [
    item.retry ? "retry" : "",
    item.timed_out === true ? "timed out" : "",
    item.truncated === true ? "truncated" : "",
  ].filter((flag) => flag !== "");
  return set.length === 0 ? "none" : set.join(", ");
}

/** Raw output, only when the API sent the keys (operator and admin, TS §6.2). */
function Output({ item }: { readonly item: Item }) {
  if (!("stdout" in item)) return null;
  return (
    <details>
      <summary>Output</summary>
      <h4>stdout</h4>
      <pre className="code-block">{item.stdout ?? ""}</pre>
      <h4>stderr</h4>
      <pre className="code-block">{item.stderr ?? ""}</pre>
    </details>
  );
}

export interface ScanResultsProps {
  readonly scanId: string;
  readonly links: ScanLinks;
}

/**
 * REQ-281. Mount it with `key={scanId}`. Every value is a text node; stdout
 * and stderr appear only when the response holds them.
 */
export function ScanResults({ scanId, links }: ScanResultsProps) {
  const [hosts, setHosts] = useState<readonly Host[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [agentId, setAgentId] = useState("");
  const pages = useCursorPages();
  const [items, setItems] = useState<readonly Item[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let active = true;
    // Only for the host filter's choices.
    api
      .GET("/api/v1/scans/{id}", { params: { path: { id: scanId } } })
      .then(({ data }) => {
        if (active && data !== undefined) setHosts(data.hosts);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [scanId]);

  useEffect(() => {
    let active = true;
    const query = toFilters(status, agentId);
    const cursor = pages.cursor === null ? {} : { cursor: pages.cursor };
    api
      .GET("/api/v1/scans/{id}/results", {
        params: {
          path: { id: scanId },
          query: { ...query, limit: PAGE_SIZE, ...cursor },
        },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        setUnreachable(false);
        setItems(data?.items ?? null);
        setNext(data?.next_cursor ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setUnreachable(true);
      });
    return () => {
      active = false;
    };
  }, [scanId, status, agentId, pages.cursor]);

  async function exportCsv(): Promise<void> {
    setExporting(true);
    try {
      setProblem(await downloadResultsCsv(scanId, toFilters(status, agentId)));
    } catch {
      setUnreachable(true);
    } finally {
      setExporting(false);
    }
  }

  const output = items?.some((item) => "stdout" in item) ?? false;
  return (
    <main className="page">
      <a className="back-link" href={links.scanHref(scanId)}>
        Back to the scan
      </a>
      <div className="page-header">
        <div>
          <h1>Results</h1>
          <p className="page-subtitle">Scan {scanId}</p>
        </div>
        <div className="page-actions">
          <label className="inline-field">
            Status
            <select
              value={status ?? ""}
              onChange={(event) => {
                setStatus(toStatus(event.target.value));
                pages.reset();
              }}
            >
              <option value="">All</option>
              {STATUSES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Host
            <select
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                pages.reset();
              }}
            >
              <option value="">All</option>
              {hosts.map((host) => (
                <option key={host.agent_id} value={host.agent_id}>
                  {host.hostname}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-sm"
            disabled={exporting}
            onClick={() => void exportCsv()}
          >
            Export CSV
          </button>
        </div>
      </div>
      {unreachable && (
        <p role="alert" className="callout callout-danger">
          {UNAVAILABLE}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <div className="card card-flush">
        {items === null && !unreachable && problem === null && (
          <p className="empty">Loading.</p>
        )}
        {items !== null && items.length === 0 && (
          <p className="empty">No results.</p>
        )}
        {items !== null && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Host</th>
                  <th>Plugin</th>
                  <th>Result</th>
                  <th>Detail</th>
                  <th>Exit code</th>
                  <th>Flags</th>
                  <th>Finished</th>
                  {output && <th>Output</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const reevaluated = item.reevaluated_at !== null;
                  return (
                    <tr key={item.agent_id + " " + item.plugin_uuid}>
                      <td className="wrap">{item.hostname}</td>
                      <td className="wrap">{item.plugin_name}</td>
                      <td>
                        <ResultBadge
                          result={item.result}
                          originalResult={item.original_result}
                          reevaluated={reevaluated}
                        />
                      </td>
                      <td className="wrap">
                        {item.eval_detail ?? ""}
                        {reevaluated && item.original_eval_detail !== null && (
                          <p className="muted">
                            Original: {item.original_eval_detail}
                          </p>
                        )}
                      </td>
                      <td>{item.exit_code ?? ""}</td>
                      <td>{flags(item)}</td>
                      <td>
                        {item.finished_at === null
                          ? ""
                          : formatTime(item.finished_at)}
                      </td>
                      {output && (
                        <td>
                          <Output item={item} />
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot">
          <Pager pages={pages} nextCursor={next} />
        </div>
      </div>
    </main>
  );
}
