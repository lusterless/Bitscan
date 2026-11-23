import { useEffect, useRef, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { ProblemBanner } from "../components/ProblemBanner";
import type { Role } from "../app/session";
import type { ScanLinks } from "../components/ScanTable";
import {
  ALL_HOSTS,
  TargetPicker,
  toTarget,
  type TargetValue,
} from "../components/TargetPicker";

type Policy = components["schemas"]["PolicyItem"];
type Kubeconfig = components["schemas"]["KubeconfigItem"];
type CmaxTarget = "auto" | "standalone" | "slurm" | "k8s";

/** TS §3.8, §4.4: a profile of this family is a ClusterMAX profile. */
export const CLUSTERMAX_FAMILY = "Clustermax";

/** TS §3.8: the allow-listed variables, in the spec's order. */
export const CMAX_VARS = [
  "CLUSTERMAX_K8S_GPU_DRA",
  "CLUSTERMAX_K8S_GPU_DRA_DEVICE_CLASS",
  "CLUSTERMAX_K8S_GPU_DRA_DRIVER",
  "CLUSTERMAX_AUDIT_K8S_NAMESPACE",
  "CLUSTERMAX_AUDIT_TENANT_NAMESPACE",
] as const;

const CMAX_TARGETS: readonly (readonly [CmaxTarget, string])[] = [
  ["auto", "Auto"],
  ["standalone", "Standalone"],
  ["slurm", "Slurm"],
  ["k8s", "Kubernetes"],
];

export interface RunScanProps {
  /** The profile chosen beforehand (from a profile's page), or null. */
  readonly policyId: string | null;
  readonly role: Role;
  readonly links: ScanLinks;
}

/** The ClusterMAX options of one scan (TS §4.4); blank variables are left out. */
function cmaxBody(
  target: CmaxTarget,
  kubeconfigId: string,
  vars: Readonly<Record<string, string>>,
): components["schemas"]["CmaxOptions"] {
  const set: Record<string, string> = {};
  for (const name of CMAX_VARS) {
    const value = (vars[name] ?? "").trim();
    if (value !== "") set[name] = value;
  }
  return kubeconfigId === ""
    ? { target, vars: set }
    : { target: "k8s", kubeconfig_id: Number(kubeconfigId), vars: set };
}

/** REQ-279, #154. Mounted for operators and admins only (TASK-251). */
export function RunScan({ policyId, role, links }: RunScanProps) {
  const [policies, setPolicies] = useState<readonly Policy[] | null>(null);
  const [chosen, setChosen] = useState(policyId ?? "");
  const [target, setTarget] = useState<TargetValue>(ALL_HOSTS);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [cmaxTarget, setCmaxTarget] = useState<CmaxTarget>("auto");
  const [kubeconfigs, setKubeconfigs] = useState<readonly Kubeconfig[]>([]);
  const [kubeconfigId, setKubeconfigId] = useState("");
  const [vars, setVars] = useState<Record<string, string>>({});
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

  // TS §6.2: only admins list kubeconfigs and start ClusterMAX scans.
  useEffect(() => {
    if (role !== "admin") return;
    let active = true;
    api
      .GET("/api/v1/kubeconfigs", { params: { query: { limit: 500 } } })
      .then(({ data }) => {
        if (active && data !== undefined)
          setKubeconfigs(data.items.filter((k) => k.deleted_at === null));
      })
      .catch(() => {
        if (active) setKubeconfigs([]);
      });
    return () => {
      active = false;
    };
  }, [role]);

  const selected = policies?.find((p) => String(p.policy_id) === chosen);
  const isCmax = selected?.family_name === CLUSTERMAX_FAMILY;

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
        body: {
          policy_id: policy.policy_id,
          target: body,
          ...(policy.family_name === CLUSTERMAX_FAMILY
            ? { cmax: cmaxBody(cmaxTarget, kubeconfigId, vars) }
            : {}),
        },
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
        {isCmax && role !== "admin" && (
          <p role="alert" className="callout callout-warning">
            Only an admin can run a ClusterMAX scan.
          </p>
        )}
        {isCmax && role === "admin" && (
          <fieldset className="fieldset" aria-label="ClusterMAX">
            <legend>ClusterMAX</legend>
            <label>
              Kubeconfig
              <select
                value={kubeconfigId}
                onChange={(event) => {
                  edit(() => setKubeconfigId(event.target.value));
                }}
              >
                <option value="">None</option>
                {kubeconfigs.map((k) => (
                  <option key={k.kubeconfig_id} value={String(k.kubeconfig_id)}>
                    {k.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Target
              <select
                value={kubeconfigId === "" ? cmaxTarget : "k8s"}
                disabled={kubeconfigId !== ""}
                onChange={(event) => {
                  edit(() => setCmaxTarget(event.target.value as CmaxTarget));
                }}
              >
                {CMAX_TARGETS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {CMAX_VARS.map((name) => (
              <label key={name}>
                {name}
                <input
                  className="mono"
                  value={vars[name] ?? ""}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => {
                    const value = event.target.value;
                    edit(() => setVars((v) => ({ ...v, [name]: value })));
                  }}
                />
              </label>
            ))}
          </fieldset>
        )}
        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || (isCmax && role !== "admin")}
          >
            Run scan
          </button>
        </div>
      </form>
    </main>
  );
}
