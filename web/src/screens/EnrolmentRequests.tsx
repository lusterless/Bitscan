import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Confirm } from "../components/Confirm";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { StatusBadge } from "../components/StatusBadge";
import { formatTime } from "../format";

type RequestItem = components["schemas"]["RequestItem"];
type MatchItem = components["schemas"]["MatchItem"];
type Page = components["schemas"]["Page_RequestItem_"];
type State = "pending" | "decided";
type Decision = "approve" | "reject";

const PAGE_SIZE = 50;

function kindLabel(kind: string): string {
  switch (kind) {
    case "new":
      return "New host";
    case "reenrol":
      return "Re-enrolment of an existing agent";
    default:
      return kind;
  }
}

/** Why an agent is listed (TS §3.2 L192): a clone shares the machine-id. */
function matchReason(request: RequestItem, match: MatchItem): string {
  const machine = match.machine_id === request.machine_id;
  const host = match.hostname === request.hostname;
  if (machine && host) return "same hostname and machine-id";
  return machine ? "same machine-id" : host ? "same hostname" : "match";
}

/** REQ-125: every value from the API is rendered as a text node. */
export function EnrolmentRequests() {
  const [state, setState] = useState<State>("pending");
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [listProblem, setListProblem] = useState<ProblemInfo | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    const query =
      pages.cursor === null
        ? { state, limit: PAGE_SIZE }
        : { state, limit: PAGE_SIZE, cursor: pages.cursor };
    api
      .GET("/api/v1/enrollment-requests", { params: { query } })
      .then(({ data, error, response }) => {
        if (!active) return;
        setPage(data ?? null);
        setListProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setNote("The manager is unavailable. Try again later.");
      });
    return () => {
      active = false;
    };
  }, [state, pages.cursor, reload]);

  async function decide(requestId: number, decision: Decision): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const params = { params: { path: { request_id: requestId } } };
      const { error, response } =
        decision === "approve"
          ? await api.POST(
              "/api/v1/enrollment-requests/{request_id}/approve",
              params,
            )
          : await api.POST(
              "/api/v1/enrollment-requests/{request_id}/reject",
              params,
            );
      if (response.status === 409) {
        setNote("This request was already decided.");
      } else if (!response.ok) {
        setProblem(toProblem(error, response));
      }
      setReload((n) => n + 1);
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Enrolment requests</h1>
          <p className="page-subtitle">
            Hosts waiting to join the fleet. Check the hostname, source IP and
            any matching agent before you approve.
          </p>
        </div>
        <div className="page-actions">
          <label className="inline-field">
            Show
            <select
              value={state}
              onChange={(event) => {
                setState(
                  event.target.value === "decided" ? "decided" : "pending",
                );
                pages.reset();
              }}
            >
              <option value="pending">Pending</option>
              <option value="decided">Decided</option>
            </select>
          </label>
        </div>
      </div>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <ProblemBanner problem={listProblem} />
      {page !== null && page.items.length === 0 && (
        <p className="card empty">No requests.</p>
      )}
      <div className="stack">
        {page?.items.map((request) => (
          <article
            key={request.request_id}
            aria-label={request.hostname}
            className="card request"
          >
            <div className="card-head">
              <h2>{request.hostname}</h2>
              <span
                className={
                  request.kind === "new"
                    ? "badge badge-info"
                    : "badge badge-warning"
                }
              >
                {request.kind === "new"
                  ? "New"
                  : request.kind === "reenrol"
                    ? "Re-enrolment"
                    : request.kind}
              </span>
            </div>
            <dl className="fields fields-flat">
              <dt>Kind</dt>
              <dd>{kindLabel(request.kind)}</dd>
              <dt>Source IP</dt>
              <dd>{request.source_ip}</dd>
              <dt>OS</dt>
              <dd>{request.os_pretty_name ?? "unknown"}</dd>
              <dt>Agent version</dt>
              <dd>{request.agent_version}</dd>
              <dt>Machine-id</dt>
              <dd>{request.machine_id}</dd>
              <dt>Requested</dt>
              <dd>{formatTime(request.requested_at)}</dd>
              {request.decision !== null && (
                <>
                  <dt>Decision</dt>
                  <dd>
                    {request.decision} by user {request.decided_by ?? "unknown"}{" "}
                    at {formatTime(request.decided_at)}
                  </dd>
                </>
              )}
            </dl>
            {request.matches.length > 0 && (
              <section
                aria-label="Matching agents"
                className="callout callout-warning"
              >
                <p role="note">
                  Warning: {request.matches.length} existing agent(s) share this
                  hostname or machine-id. A cloned image shares the machine-id.
                </p>
                <ul>
                  {request.matches.map((match) => (
                    <li key={match.agent_id}>
                      {match.hostname} ({matchReason(request, match)}),
                      machine-id {match.machine_id}, status{" "}
                      <StatusBadge status={match.status} />
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {request.decision === null && (
              <div className="actions">
                <Confirm
                  tone="primary"
                  label="Approve"
                  message={"Approve the enrolment of " + request.hostname + "?"}
                  disabled={busy}
                  onConfirm={() => {
                    void decide(request.request_id, "approve");
                  }}
                />
                <Confirm
                  tone="danger"
                  label="Reject"
                  message={"Reject the enrolment of " + request.hostname + "?"}
                  disabled={busy}
                  onConfirm={() => {
                    void decide(request.request_id, "reject");
                  }}
                />
              </div>
            )}
          </article>
        ))}
      </div>
      <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
    </main>
  );
}
