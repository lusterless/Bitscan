import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Confirm } from "../components/Confirm";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { describeTarget } from "../components/TargetPicker";
import { formatTime } from "../format";
import { ScheduleForm } from "./ScheduleForm";

type Page = components["schemas"]["Page_ScheduleItem_"];
type Schedule = components["schemas"]["ScheduleItem"];
type Policy = components["schemas"]["PolicyItem"];

const PAGE_SIZE = 50;
const UNAVAILABLE = "The manager is unavailable. Try again later.";

/** null: no form; "new": the create form; a schedule: its edit form. */
type Editing = null | "new" | Schedule;

/**
 * REQ-282. Mounted for operators and admins only (TASK-251; every
 * `/scan-schedules` route is operator, #122 (i)).
 */
export function Schedules() {
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [reload, setReload] = useState(0);
  const [policies, setPolicies] = useState<readonly Policy[]>([]);
  const [editing, setEditing] = useState<Editing>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    // Profile names for the list, and the create form's choices.
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
      .GET("/api/v1/scan-schedules", {
        params: { query: { limit: PAGE_SIZE, ...cursor } },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        setPage(data ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setNote(UNAVAILABLE);
      });
    return () => {
      active = false;
    };
  }, [pages.cursor, reload]);

  function policyName(policyId: number): string {
    const policy = policies.find((p) => p.policy_id === policyId);
    return policy?.policy_name ?? "Profile " + String(policyId);
  }

  async function remove(schedule: Schedule): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const { error, response } = await api.DELETE(
        "/api/v1/scan-schedules/{id}",
        { params: { path: { id: String(schedule.schedule_id) } } },
      );
      if (response.ok) setReload((n) => n + 1);
      else setProblem(toProblem(error, response));
    } catch {
      setNote(UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Schedules</h1>
          <p className="page-subtitle">
            Scheduled scans. Runs missed while the manager was down are not made
            up.
          </p>
        </div>
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setEditing("new");
            }}
          >
            New schedule
          </button>
        </div>
      </div>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      {editing !== null && (
        <ScheduleForm
          key={editing === "new" ? "new" : editing.schedule_id}
          schedule={editing === "new" ? null : editing}
          policies={policies}
          onSaved={() => {
            setEditing(null);
            setReload((n) => n + 1);
          }}
          onCancel={() => {
            setEditing(null);
          }}
        />
      )}
      <div className="card card-flush">
        {page !== null && page.items.length === 0 && (
          <p className="empty">No schedules.</p>
        )}
        {page !== null && page.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Profile</th>
                  <th>Target</th>
                  <th>Cron</th>
                  <th>Time zone</th>
                  <th>Enabled</th>
                  <th>Last run</th>
                  <th>Next run</th>
                  <th className="sticky-end" />
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={item.schedule_id}>
                    <td className="wrap strong">{item.name}</td>
                    <td className="wrap">{policyName(item.policy_id)}</td>
                    <td className="wrap">{describeTarget(item.target)}</td>
                    <td className="mono">{item.cron}</td>
                    <td>{item.timezone}</td>
                    <td>{item.enabled ? "yes" : "no"}</td>
                    <td>{formatTime(item.last_run_at)}</td>
                    <td>{formatTime(item.next_run_at)}</td>
                    <td className="sticky-end">
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy}
                        onClick={() => {
                          setEditing(item);
                        }}
                      >
                        Edit
                      </button>
                      <Confirm
                        tone="danger"
                        label="Delete"
                        message={
                          "Delete schedule " +
                          item.name +
                          "? Its past scans stay; no new scan is queued from it."
                        }
                        disabled={busy}
                        onConfirm={() => {
                          void remove(item);
                        }}
                      />
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
