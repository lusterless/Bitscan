import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash } from "../app/router";
import type { Role } from "../app/session";
import { Confirm } from "../components/Confirm";
import { ProblemBanner } from "../components/ProblemBanner";
import { ScanStateBadge, type ScanLinks } from "../components/ScanTable";
import { Score } from "../components/Score";
import { describeTarget } from "../components/TargetPicker";
import { formatTime } from "../format";

type Detail = components["schemas"]["ScanDetailItem"];
type HostJob = components["schemas"]["HostJob"];
/** What openapi-fetch answers; `error` is the parsed refusal body. */
interface Answer {
  readonly data?: unknown;
  readonly error?: unknown;
  readonly response: Response;
}

type Load =
  | { readonly kind: "loading" }
  | { readonly kind: "not-found" }
  | { readonly kind: "failed"; readonly problem: ProblemInfo | null }
  | { readonly kind: "ok"; readonly value: Detail };

const UNAVAILABLE = "The manager is unavailable. Try again later.";

function Fields({ rows }: { rows: readonly (readonly [string, string])[] }) {
  return (
    <dl className="fields">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The unit's jobs, original first, then its retry (#145 (b)). */
function jobsText(jobs: readonly HostJob[]): string {
  return jobs
    .map((job) => (job.retry_of === null ? job.state : "retry " + job.state))
    .join(", ");
}

export interface ScanDetailProps {
  readonly scanId: string;
  readonly role: Role;
  readonly links: ScanLinks;
}

/**
 * REQ-280. Mount it with `key={scanId}`. Cancel is offered to operators and
 * admins while the scan is unfinished, Re-evaluate to admins; the server
 * decides (TS §6.2). Re-evaluate needs a TOTP-verified session: a refusal
 * shows the sign-in-again prompt, never a field for an API token.
 */
export function ScanDetail({ scanId, role, links }: ScanDetailProps) {
  const [detail, setDetail] = useState<Load>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { id: scanId } } };

  useEffect(() => {
    let active = true;
    api
      .GET("/api/v1/scans/{id}", { params: { path: { id: scanId } } })
      .then(({ data, error, response }) => {
        if (!active) return;
        if (data !== undefined) setDetail({ kind: "ok", value: data });
        else if (response.status === 404) setDetail({ kind: "not-found" });
        else setDetail({ kind: "failed", problem: toProblem(error, response) });
      })
      .catch(() => {
        if (active) setDetail({ kind: "failed", problem: null });
      });
    return () => {
      active = false;
    };
  }, [scanId, reload]);

  /** Reloads only after a success: a refusal sends no other request. */
  async function act<T extends Answer>(
    run: () => Promise<T>,
    done: (data: NonNullable<T["data"]>) => string,
  ): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const { data, error, response } = await run();
      if (data !== undefined && data !== null) {
        setNote(done(data));
        setReload((n) => n + 1);
      } else if (response.status === 404) setNote("Scan not found.");
      else setProblem(toProblem(error, response));
    } catch {
      setNote(UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }

  const back = (
    <a className="back-link" href={links.scansHref}>
      Back to scans
    </a>
  );
  if (detail.kind !== "ok") {
    return (
      <main className="page">
        {back}
        {detail.kind === "loading" && <p className="muted">Loading.</p>}
        {detail.kind === "not-found" && (
          <p role="alert" className="callout callout-danger">
            Scan not found.
          </p>
        )}
        {detail.kind === "failed" &&
          (detail.problem === null ? (
            <p role="alert" className="callout callout-danger">
              {UNAVAILABLE}
            </p>
          ) : (
            <ProblemBanner problem={detail.problem} />
          ))}
      </main>
    );
  }
  const scan = detail.value;
  return (
    <main className="page">
      {back}
      <div className="page-header">
        <div>
          <div className="title-row">
            <h1>{scan.policy_name}</h1>
            <ScanStateBadge state={scan.state} />
          </div>
          <p className="page-subtitle">
            Scan {scan.scan_id} · created {formatTime(scan.created_at)}
          </p>
        </div>
        <div className="page-actions">
          <a className="btn btn-sm" href={links.resultsHref(scan.scan_id)}>
            Results
          </a>
          {role !== "viewer" && scan.finished_at === null && (
            <Confirm
              tone="danger"
              label="Cancel scan"
              message="Cancel this scan? Its queued and running jobs are cancelled and their results are no longer accepted."
              disabled={busy}
              onConfirm={() => {
                void act(
                  () => api.POST("/api/v1/scans/{id}/cancel", path),
                  (data) =>
                    "Scan cancelled: " +
                    String(data.cancelled_jobs) +
                    " jobs cancelled.",
                );
              }}
            />
          )}
          {role === "admin" && (
            <Confirm
              label="Re-evaluate"
              message="Re-evaluate this scan against the profile's current version? New verdicts are added; the original results never change."
              disabled={busy}
              onConfirm={() => {
                void act(
                  () => api.POST("/api/v1/scans/{id}/reevaluate", path),
                  (data) =>
                    "Re-evaluated against version " +
                    String(data.policy_version) +
                    ": " +
                    String(data.rows_added) +
                    " verdicts added.",
                );
              }}
            />
          )}
        </div>
      </div>
      {note !== null && (
        <p role="status" className="callout callout-warning">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <section className="card" aria-labelledby="scan-fields">
        <h2 id="scan-fields">Scan</h2>
        <Fields
          rows={[
            ["Profile", scan.policy_name],
            ["Profile version", String(scan.policy_version)],
            ["Trigger", scan.trigger === "manual" ? "Manual" : "Scheduled"],
            [
              "Schedule",
              scan.schedule_id === null ? "none" : String(scan.schedule_id),
            ],
            [
              "Requested by (user id)",
              scan.requested_by === null ? "system" : String(scan.requested_by),
            ],
            ["Target", describeTarget(scan.target)],
            ["Hosts targeted", String(scan.resolved_count)],
            ["Created", formatTime(scan.created_at)],
            [
              "Finished",
              scan.finished_at === null
                ? "not finished"
                : formatTime(scan.finished_at),
            ],
          ]}
        />
      </section>
      <section className="card card-flush" aria-labelledby="scan-hosts">
        <h2 id="scan-hosts" className="card-title">
          Hosts ({scan.hosts.length})
        </h2>
        {scan.hosts.length === 0 ? (
          <p className="empty">No host has a job in this scan.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Host</th>
                  <th>Jobs</th>
                  <th>Passed</th>
                  <th>Failed</th>
                  <th>Not run</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {scan.hosts.map((host) => (
                  <tr key={host.agent_id}>
                    <td>
                      <a
                        className="strong-link"
                        href={formatHash({
                          name: "host",
                          agentId: host.agent_id,
                        })}
                      >
                        {host.hostname}
                      </a>
                    </td>
                    <td>{jobsText(host.jobs)}</td>
                    <td>{host.passed}</td>
                    <td>{host.failed}</td>
                    <td>{host.not_run}</td>
                    <td>
                      <Score score={host.score} errors={host.errors} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
