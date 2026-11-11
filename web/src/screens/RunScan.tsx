import { useEffect, useRef, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { ProblemBanner } from "../components/ProblemBanner";
import type { ScanLinks } from "../components/ScanTable";
import {
  ALL_HOSTS,
  TargetPicker,
  toTarget,
  type TargetValue,
} from "../components/TargetPicker";

type Policy = components["schemas"]["PolicyItem"];

export interface RunScanProps {
  /** The profile chosen beforehand (from a profile's page), or null. */
  readonly policyId: string | null;
  readonly links: ScanLinks;
}

/** REQ-279, #154. Mounted for operators and admins only (TASK-251). */
export function RunScan({ policyId, links }: RunScanProps) {
  const [policies, setPolicies] = useState<readonly Policy[] | null>(null);
  const [chosen, setChosen] = useState(policyId ?? "");
  const [target, setTarget] = useState<TargetValue>(ALL_HOSTS);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [busy, setBusy] = useState(false);
  // #154 (b): one key per submission, kept only to retry it after a network
  // error; any answer or any change to the form starts a new one.
  const key = useRef<string | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    api
      .GET("/api/v1/policies", {
        params: { query: { status: "enabled", limit: 500 } },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        if (data === undefined) setProblem(toProblem(error, response));
        setPolicies(data?.items ?? []);
      })
      .catch(() => {
        if (active) setNote("The manager is unavailable. Try again later.");
      });
    return () => {
      active = false;
    };
  }, []);

  function edit(run: () => void): void {
    key.current = null;
    run();
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (inFlight.current) return;
    const body = toTarget(target);
    const policy = policies?.find((p) => String(p.policy_id) === chosen);
    setProblem(null);
    if (policy === undefined) {
      setNote("Choose an enabled profile.");
      return;
    }
    if (typeof body === "string") {
      setNote(body);
      return;
    }
    setNote(null);
    key.current ??= crypto.randomUUID();
    inFlight.current = true;
    setBusy(true);
    try {
      const { data, error, response } = await api.POST("/api/v1/scans", {
        params: { header: { "Idempotency-Key": key.current } },
        body: { policy_id: policy.policy_id, target: body },
      });
      key.current = null;
      if (data !== undefined) links.openScan(data.scan_id);
      else setProblem(toProblem(error, response));
    } catch {
      setNote("The manager could not be reached. Submit again to retry.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="page page-narrow">
      <a className="back-link" href={links.scansHref}>
        Back to scans
      </a>
      <h1>Run scan</h1>
      <p className="page-subtitle">
        Hosts pick up the scan at their next job pull.
      </p>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <form
        aria-label="Run scan"
        className="card form form-wide"
        onSubmit={(event) => void submit(event)}
      >
        <label>
          Profile
          <select
            value={chosen}
            onChange={(event) => {
              edit(() => setChosen(event.target.value));
            }}
          >
            <option value="">Choose an enabled profile</option>
            {policies?.map((policy) => (
              <option key={policy.policy_id} value={String(policy.policy_id)}>
                {policy.policy_name}
              </option>
            ))}
          </select>
        </label>
        <TargetPicker
          value={target}
          onChange={(value) => {
            edit(() => setTarget(value));
          }}
        />
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Run scan
          </button>
        </div>
      </form>
    </main>
  );
}
