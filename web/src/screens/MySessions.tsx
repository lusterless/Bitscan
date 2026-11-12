import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { clearSession } from "../app/session";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type SessionItem = components["schemas"]["SessionItem"];

// One page holds every session a user is likely to have (max limit, TS §6.3).
const PAGE_SIZE = 500;

/**
 * TS §6.2 (owner decision 2026-11-12): the caller's own active web
 * sessions, with a way to end any of them. Ending this session signs out.
 */
export function MySessions() {
  const [items, setItems] = useState<readonly SessionItem[] | null>(null);
  const [more, setMore] = useState(false);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      const { data, error, response } = await api.GET("/api/v1/auth/sessions", {
        params: { query: { limit: PAGE_SIZE } },
      });
      setUnreachable(false);
      if (data === undefined) {
        setProblem(toProblem(error, response));
        return;
      }
      setProblem(null);
      setItems(data.items);
      setMore(data.next_cursor !== null);
    } catch {
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** True when the session ended (or was already gone). */
  async function end(item: SessionItem): Promise<boolean> {
    const { error, response } = await api.DELETE(
      "/api/v1/auth/sessions/{session_id}",
      { params: { path: { session_id: item.session_id } } },
    );
    if (response.status === 204 || response.status === 404) {
      return true;
    }
    setProblem(toProblem(error, response));
    return false;
  }

  async function run(targets: readonly SessionItem[]): Promise<void> {
    setBusy(true);
    setNotice(null);
    setProblem(null);
    try {
      let ended = 0;
      for (const item of targets) {
        if (!(await end(item))) {
          break;
        }
        ended += 1;
        if (item.current) {
          // This browser's session is over: back to sign-in.
          clearSession();
          return;
        }
      }
      if (ended > 0) {
        setNotice(
          ended === 1 ? "1 session ended." : String(ended) + " sessions ended.",
        );
      }
      await load();
    } catch {
      setUnreachable(true);
    } finally {
      setBusy(false);
    }
  }

  const others = (items ?? []).filter((item) => !item.current);

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>My sessions</h1>
          <p className="page-subtitle">
            Where you are signed in to the web UI. Ending a session signs that
            browser out. API tokens are not listed here.
          </p>
        </div>
        <div className="page-actions">
          <button
            type="button"
            className="btn"
            disabled={busy || others.length === 0}
            onClick={() => {
              void run(others);
            }}
          >
            End all other sessions
          </button>
        </div>
      </div>
      {unreachable && (
        <p role="alert" className="callout callout-danger">
          The manager is unavailable. Try again later.
        </p>
      )}
      {notice !== null && (
        <p role="status" className="callout callout-success">
          {notice}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <div className="card card-flush">
        {items === null && !unreachable && problem === null && (
          <p className="empty">Loading.</p>
        )}
        {items !== null && items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Signed in</th>
                  <th>Last used</th>
                  <th>Expires</th>
                  <th>TOTP-verified</th>
                  <th className="sticky-end" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.session_id}>
                    <td>
                      {item.current ? (
                        <span className="badge badge-success">
                          This session
                        </span>
                      ) : (
                        String(item.session_id)
                      )}
                    </td>
                    <td>{formatTime(item.created_at)}</td>
                    <td>{formatTime(item.last_used_at)}</td>
                    <td>{formatTime(item.expires_at)}</td>
                    <td>{item.totp_verified ? "yes" : "no"}</td>
                    <td className="sticky-end">
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy}
                        aria-label={
                          item.current
                            ? "End this session"
                            : "End session " + String(item.session_id)
                        }
                        onClick={() => {
                          void run([item]);
                        }}
                      >
                        {item.current ? "Sign out" : "End"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {more && (
          <p className="card-foot">
            Only the first {PAGE_SIZE} sessions are shown.
          </p>
        )}
      </div>
    </main>
  );
}
