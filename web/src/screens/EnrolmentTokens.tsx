import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Confirm } from "../components/Confirm";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type CreatedToken = components["schemas"]["CreatedToken"];
type Page = components["schemas"]["Page_TokenItem_"];

const PAGE_SIZE = 50;

/** A whole number within [min, max], or null. The server checks again. */
function wholeNumber(text: string, min: number, max: number): number | null {
  const value = Number(text);
  return text.trim() !== "" &&
    Number.isInteger(value) &&
    value >= min &&
    value <= max
    ? value
    : null;
}

function cidrList(text: string): string[] | null {
  const list = text.split(/[\s,]+/).filter((part) => part !== "");
  return list.length === 0 ? null : list;
}

/**
 * REQ-124. The created bse_ token is kept only in `created` and dropped when
 * the result is closed or the screen unmounts; the list never holds a token.
 */
export function EnrolmentTokens() {
  const [maxUses, setMaxUses] = useState("1");
  const [hours, setHours] = useState("24");
  const [cidrs, setCidrs] = useState("");
  const [autoApprove, setAutoApprove] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [listProblem, setListProblem] = useState<ProblemInfo | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    const query =
      pages.cursor === null
        ? { limit: PAGE_SIZE }
        : { limit: PAGE_SIZE, cursor: pages.cursor };
    api
      .GET("/api/v1/enrollment-tokens", { params: { query } })
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
  }, [pages.cursor, reload]);

  async function act(run: () => Promise<ProblemInfo | null>): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      setProblem(await run());
      setReload((n) => n + 1);
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  function create(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const max_uses = wholeNumber(maxUses, 1, 10_000);
    const expires_in_hours = wholeNumber(hours, 1, 720);
    if (max_uses === null || expires_in_hours === null) {
      setNote("Max uses must be 1 to 10,000 and the expiry 1 to 720 hours.");
      return;
    }
    const body = {
      max_uses,
      expires_in_hours,
      allowed_cidrs: cidrList(cidrs),
      auto_approve: autoApprove,
    };
    void act(async () => {
      const { data, error, response } = await api.POST(
        "/api/v1/enrollment-tokens",
        { body },
      );
      if (data === undefined) return toProblem(error, response);
      setCopied(false);
      setCreated(data);
      return null;
    });
  }

  function revoke(tokenId: number): void {
    void act(async () => {
      const { error, response } = await api.DELETE(
        "/api/v1/enrollment-tokens/{token_id}",
        { params: { path: { token_id: tokenId } } },
      );
      return response.ok ? null : toProblem(error, response);
    });
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Enrolment tokens</h1>
          <p className="page-subtitle">
            Tokens let new hosts enrol. Each token has a use limit and an
            expiry, and can be limited to CIDRs.
          </p>
        </div>
      </div>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <div className="split">
        {created !== null ? (
          <section
            aria-label="New enrolment token"
            className="card card-success"
          >
            <h2>Token created</h2>
            <p className="callout callout-warning">
              Copy this token now. It is shown only once.
            </p>
            <div className="secret-row">
              <code className="secret">{created.token}</code>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  // Inside a promise, so a missing Clipboard API is caught too.
                  const token = created.token;
                  void Promise.resolve()
                    .then(() => navigator.clipboard.writeText(token))
                    .then(() => {
                      setCopied(true);
                    })
                    .catch(() => {
                      setCopied(false);
                    });
                }}
              >
                Copy
              </button>
            </div>
            {copied && (
              <span role="status" className="status-ok">
                Copied.
              </span>
            )}
            <p className="muted">
              Token {created.token_id}: up to {created.max_uses} uses, expires{" "}
              {formatTime(created.expires_at)}.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setCreated(null);
                setCopied(false);
              }}
            >
              Done
            </button>
          </section>
        ) : (
          <form
            onSubmit={create}
            aria-label="Create enrolment token"
            className="card form form-wide"
          >
            <h2>New token</h2>
            <p className="hint">
              A multi-use token should set max uses to the expected number of
              hosts and set allowed CIDRs.
            </p>
            <p className="hint">
              Creating a token with auto-approve or more than 100 uses raises an
              alert.
            </p>
            <label>
              Max uses (1 to 10,000)
              <input
                type="number"
                min={1}
                max={10_000}
                value={maxUses}
                onChange={(event) => {
                  setMaxUses(event.target.value);
                }}
              />
            </label>
            <label>
              Expires in hours (1 to 720)
              <input
                type="number"
                min={1}
                max={720}
                value={hours}
                onChange={(event) => {
                  setHours(event.target.value);
                }}
              />
            </label>
            <label>
              Allowed CIDRs (optional, one per line)
              <textarea
                value={cidrs}
                onChange={(event) => {
                  setCidrs(event.target.value);
                }}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={autoApprove}
                onChange={(event) => {
                  setAutoApprove(event.target.checked);
                }}
              />
              Auto-approve new hosts
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>
                Create token
              </button>
            </div>
          </form>
        )}
        <section className="card card-flush" aria-labelledby="tokens-title">
          <h2 id="tokens-title" className="card-title">
            Tokens
          </h2>
          <ProblemBanner problem={listProblem} />
          {page !== null && page.items.length === 0 && (
            <p className="empty">No enrolment tokens yet.</p>
          )}
          {page !== null && page.items.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Uses</th>
                    <th>Auto-approve</th>
                    <th>Allowed CIDRs</th>
                    <th>Expires</th>
                    <th>Created</th>
                    <th>Created by (user id)</th>
                    <th>Revoked</th>
                    <th className="sticky-end" />
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((item) => (
                    <tr key={item.token_id}>
                      <td>{item.token_id}</td>
                      <td>
                        {item.uses} / {item.max_uses}
                      </td>
                      <td>{item.auto_approve ? "yes" : "no"}</td>
                      <td className="wrap">
                        {item.allowed_cidrs?.join(", ") ?? "any"}
                      </td>
                      <td>{formatTime(item.expires_at)}</td>
                      <td>{formatTime(item.created_at)}</td>
                      <td>{item.created_by}</td>
                      <td>
                        {item.revoked_at === null
                          ? "not revoked"
                          : formatTime(item.revoked_at)}
                      </td>
                      <td className="sticky-end">
                        {item.revoked_at === null && (
                          <Confirm
                            tone="danger"
                            label="Revoke"
                            message={
                              "Revoke enrolment token " +
                              String(item.token_id) +
                              "? Hosts can no longer enrol with it."
                            }
                            disabled={busy}
                            onConfirm={() => {
                              revoke(item.token_id);
                            }}
                          />
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
        </section>
      </div>
    </main>
  );
}
