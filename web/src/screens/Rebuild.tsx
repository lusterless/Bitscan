import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Confirm } from "../components/Confirm";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type Task = components["schemas"]["TaskItem"];
type TaskResult = components["schemas"]["TaskResult"];

/** How long to wait between two `GET /tasks/{id}` while the task runs. */
export const POLL_MS = 2000;

const UNAVAILABLE = "The manager is unavailable. Try again later.";

function ids(values: readonly (number | string)[]): string {
  return values.length === 0 ? "none" : values.join(", ");
}

function Files({ result }: { readonly result: TaskResult }) {
  return (
    <>
      {result.files.length > 0 && (
        <div className="table-wrap">
          <table className="table" aria-label="Files">
            <thead>
              <tr>
                <th>File</th>
                <th>Outcome</th>
                <th>Import</th>
                <th>Policy</th>
                <th>Version</th>
              </tr>
            </thead>
            <tbody>
              {result.files.map((file, index) => (
                <tr key={index}>
                  <td className="mono wrap">{file.source_file}</td>
                  <td>{file.outcome}</td>
                  <td>{file.import_id ?? "none"}</td>
                  <td>{file.policy_id ?? "none"}</td>
                  <td>{file.policy_version ?? "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="fields">
        <div>
          <dt>Files</dt>
          <dd>{result.files.length}</dd>
        </div>
        <div>
          <dt>Not imported</dt>
          <dd className="mono">{ids(result.not_imported)}</dd>
        </div>
        <div>
          <dt>Deleted policies</dt>
          <dd>{ids(result.deleted_policy_ids)}</dd>
        </div>
        <div>
          <dt>Plugins retired</dt>
          <dd>{result.plugins_retired}</dd>
        </div>
        <div>
          <dt>Leftovers removed</dt>
          <dd className="mono">{ids(result.removed_leftovers)}</dd>
        </div>
      </dl>
    </>
  );
}

/**
 * REQ-182 (3), TS §4.2: a rebuild needs a TOTP-verified admin session; a
 * refusal shows the sign-in-again prompt and never asks for an API token.
 * After the 202 the task is polled until it is `succeeded` or `failed`.
 */
export function Rebuild() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (taskId === null) return;
    const id = taskId;
    let active = true;
    let timer: number | undefined;
    function poll(): void {
      api
        .GET("/api/v1/tasks/{id}", { params: { path: { id } } })
        .then(({ data, error, response }) => {
          if (!active) return;
          if (data === undefined) {
            setProblem(toProblem(error, response));
            return;
          }
          setTask(data);
          if (data.state === "running")
            timer = window.setTimeout(poll, POLL_MS);
        })
        .catch(() => {
          if (active) setNote(UNAVAILABLE);
        });
    }
    poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [taskId]);

  async function start(): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const { data, error, response } = await api.POST(
        "/api/v1/policies/rebuild",
      );
      if (data === undefined) {
        setProblem(toProblem(error, response));
      } else {
        setTask(null);
        setTaskId(data.task_id);
      }
    } catch {
      setNote(UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }

  const running =
    taskId !== null && (task === null || task.state === "running");
  const result = task?.result ?? null;
  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Rebuild catalog</h1>
          <p className="page-subtitle">
            Re-imports every file in both policy folders. A rejected file keeps
            its catalog rows; policies whose files are gone are deleted.
          </p>
        </div>
        <div className="page-actions">
          <Confirm
            tone="primary"
            label="Rebuild"
            message="Rebuild the catalog from both policy folders now?"
            disabled={busy || running}
            onConfirm={() => {
              void start();
            }}
          />
        </div>
      </div>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      {taskId !== null && (
        <section className="card" aria-label="Rebuild task">
          <h2>Task {taskId}</h2>
          <p role="status">
            {task === null || task.state === "running"
              ? "Running."
              : task.state === "succeeded"
                ? "Succeeded."
                : "Failed."}
          </p>
          {task !== null && (
            <p className="muted">
              Started {formatTime(task.started_at)}, finished{" "}
              {task.finished_at === null
                ? "not yet"
                : formatTime(task.finished_at)}
              .
            </p>
          )}
          {result !== null &&
            ("error" in result ? (
              <p className="callout callout-danger">{result.error}</p>
            ) : (
              <Files result={result} />
            ))}
        </section>
      )}
    </main>
  );
}
