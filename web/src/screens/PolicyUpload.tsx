import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import { Findings } from "../components/Findings";
import { ProblemBanner } from "../components/ProblemBanner";

type ImportResult = components["schemas"]["ImportResult"];

export interface PolicyUploadProps {
  readonly navigate: (route: Route) => void;
}

function Outcome({
  result,
  navigate,
}: {
  readonly result: ImportResult;
  readonly navigate: (route: Route) => void;
}) {
  const ok = result.outcome === "success";
  const route: Route | null =
    result.policy_id === null
      ? null
      : { name: "profile", policyId: String(result.policy_id) };
  return (
    <section
      aria-label="Import outcome"
      className={ok ? "card card-success" : "card"}
    >
      <div className="card-head">
        <h2>{ok ? "Imported" : "Rejected"}</h2>
        <span className={ok ? "badge badge-success" : "badge badge-danger"}>
          Import {result.import_id}
        </span>
      </div>
      {ok ? (
        <p>
          {result.policy_name ?? "unknown"}, version{" "}
          {result.policy_version ?? "unknown"}: {result.plugins_added} plugins
          added, {result.plugins_updated} updated, {result.plugins_retired}{" "}
          retired. It is live now.
        </p>
      ) : (
        <p>The file was not imported; the catalog is unchanged.</p>
      )}
      {route !== null && (
        <a
          className="strong-link"
          href={formatHash(route)}
          onClick={(event) => {
            event.preventDefault();
            navigate(route);
          }}
        >
          Open the profile
        </a>
      )}
      <h3>Findings ({result.errors.length})</h3>
      <Findings findings={result.errors} label="Findings" />
    </section>
  );
}

/**
 * REQ-182 (1), TS §6.3 L1137: one `.bit` file as the multipart part `file`.
 * An admin's session may upload; it is not a TOTP-session action (TS §6.2).
 */
export function PolicyUpload({ navigate }: PolicyUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(chosen: File): Promise<void> {
    setNote(null);
    setProblem(null);
    setResult(null);
    setBusy(true);
    const form = new FormData();
    form.append("file", chosen, chosen.name);
    try {
      const { data, error, response } = await api.POST(
        "/api/v1/policies/import",
        {
          // The generated type models the binary part as a string; the
          // serializer sends the FormData, so the browser sets the boundary.
          body: { file: "" },
          bodySerializer: () => form,
        },
      );
      if (data !== undefined) setResult(data);
      else if (response.status === 413)
        setNote("The file is too large. A .bit file may be at most 5 MiB.");
      else setProblem(toProblem(error, response));
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (file === null) {
      setNote("Choose a .bit file first.");
      return;
    }
    void upload(file);
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Upload policy</h1>
          <p className="page-subtitle">
            Upload one .bit file. It is validated, and if it passes it is live
            at once. Every import is audit-logged and alerts.
          </p>
        </div>
      </div>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <form
        onSubmit={submit}
        aria-label="Upload policy"
        className="card form form-wide"
      >
        <label>
          .bit file (at most 5 MiB)
          <input
            type="file"
            accept=".bit"
            onChange={(event) => {
              setFile(event.target.files?.item(0) ?? null);
            }}
          />
        </label>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Upload
          </button>
        </div>
      </form>
      {result !== null && <Outcome result={result} navigate={navigate} />}
    </main>
  );
}
