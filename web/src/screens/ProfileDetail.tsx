import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import type { Role } from "../app/session";
import { Confirm } from "../components/Confirm";
import { Icon } from "../components/Icon";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";
import { PolicyStatusBadge } from "./Profiles";

type Detail = components["schemas"]["PolicyDetailItem"];
type Plugin = components["schemas"]["PolicyPluginItem"];
type Change = components["schemas"]["PatchPolicy"];
/** What openapi-fetch answers; `error` is the parsed refusal body. */
interface Answer {
  readonly error?: unknown;
  readonly response: Response;
}

export interface ProfileDetailProps {
  readonly policyId: string;
  readonly role: Role;
  readonly navigate: (route: Route) => void;
}

type Load =
  | { readonly kind: "loading" }
  | { readonly kind: "not-found" }
  | { readonly kind: "failed"; readonly problem: ProblemInfo | null }
  | { readonly kind: "ok"; readonly value: Detail };

const UNAVAILABLE = "The manager is unavailable. Try again later.";

/** Fixed labels and API values, all as text nodes. */
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

function PluginCard({ plugin }: { plugin: Plugin }) {
  return (
    <article aria-label={plugin.display_name} className="card">
      <div className="card-head">
        <h3>{plugin.display_name}</h3>
        {plugin.state === "retired" && (
          <span className="badge badge-neutral">Retired</span>
        )}
      </div>
      <p className="wrap">{plugin.plugin_description}</p>
      <Fields
        rows={[
          ["Control", plugin.control_ref ?? "none"],
          ["Operator", plugin.operator],
          ["Expected result", plugin.expected_result],
          ["Timeout (s)", String(plugin.timeout_s)],
          ["Plugin id", plugin.plugin_uuid],
        ]}
      />
      <h4>Execute</h4>
      <pre className="code-block">{plugin.execute}</pre>
    </article>
  );
}

/** REQ-168's three bodies: the opposite status (an override), and clearing it. */
function statusActions(policy: Detail): [string, Change, string][] {
  const actions: [string, Change, string][] =
    policy.policy_status === "disabled"
      ? [["Enable", { policy_status: "enabled" }, "Profile enabled."]]
      : [["Disable", { policy_status: "disabled" }, "Profile disabled."]];
  if (policy.status_overridden) {
    actions.push([
      "Clear override",
      { status_overridden: false },
      "Override cleared.",
    ]);
  }
  return actions;
}

/**
 * REQ-181, REQ-182 (2). Mount it with `key={policyId}`. Status actions and
 * delete are offered to admins only; Run scan with this profile chosen to
 * operators and admins while it is enabled (REQ-279, #154 (c)); the server
 * decides (TS §6.2). Delete
 * needs a TOTP-verified session: a refusal shows the sign-in-again prompt.
 */
export function ProfileDetail({
  policyId,
  role,
  navigate,
}: ProfileDetailProps) {
  const [detail, setDetail] = useState<Load>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const path = { params: { path: { id: policyId } } };

  useEffect(() => {
    let active = true;
    api
      .GET("/api/v1/policies/{id}", { params: { path: { id: policyId } } })
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
  }, [policyId, reload]);

  async function act(run: () => Promise<Answer>, done: string) {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const { error, response } = await run();
      const info = response.ok ? null : toProblem(error, response);
      // #98 (c), (e): screen texts for 409 `conflict` and 404; any other
      // refusal (`policy_managed_on_server`, a TOTP session) is the banner's.
      if (info === null) setNote(done);
      else if (info.status === 409 && info.type === "conflict")
        setNote("This profile is deleted.");
      else if (info.status === 404) setNote("Profile not found.");
      else setProblem(info);
      setReload((n) => n + 1);
    } catch {
      setNote(UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }

  function patch(body: Change, done: string): void {
    void act(() => api.PATCH("/api/v1/policies/{id}", { ...path, body }), done);
  }

  const back = (
    <a
      className="back-link"
      href={formatHash({ name: "profiles" })}
      onClick={(event) => {
        event.preventDefault();
        navigate({ name: "profiles" });
      }}
    >
      <Icon name="back" />
      Back to profiles
    </a>
  );
  if (detail.kind !== "ok") {
    return (
      <main className="page">
        {back}
        {detail.kind === "loading" && <p className="muted">Loading.</p>}
        {detail.kind === "not-found" && (
          <p role="alert" className="callout callout-danger">
            Profile not found.
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
  const policy = detail.value;
  const deleted = policy.deleted_at !== null;
  const plugins = [...policy.plugins].sort(
    (a, b) => a.sort_order - b.sort_order,
  );
  return (
    <main className="page">
      {back}
      <div className="page-header">
        <div>
          <div className="title-row">
            <h1>{policy.policy_name}</h1>
            {deleted ? (
              <span className="badge badge-danger">Deleted</span>
            ) : (
              <PolicyStatusBadge
                status={policy.policy_status}
                overridden={policy.status_overridden}
              />
            )}
          </div>
          <p className="page-subtitle">{policy.policy_description}</p>
        </div>
        {role !== "viewer" && !deleted && (
          <div className="page-actions">
            {policy.policy_status === "enabled" && (
              <a
                className="btn btn-sm btn-primary"
                href={formatHash({ name: "run-scan", policyId })}
              >
                Run scan
              </a>
            )}
            {role === "admin" && (
              <>
                {statusActions(policy).map(([label, body, done]) => (
                  <button
                    key={label}
                    type="button"
                    className="btn btn-sm"
                    disabled={busy}
                    onClick={() => {
                      patch(body, done);
                    }}
                  >
                    {label}
                  </button>
                ))}
                <Confirm
                  tone="danger"
                  label="Delete"
                  message={
                    "Delete profile " +
                    policy.policy_name +
                    "? It leaves selection, its queued jobs are cancelled, its schedules are disabled and its plugins are retired."
                  }
                  disabled={busy}
                  onConfirm={() => {
                    void act(
                      () => api.DELETE("/api/v1/policies/{id}", path),
                      "Profile deleted.",
                    );
                  }}
                />
              </>
            )}
          </div>
        )}
      </div>
      {note !== null && (
        <p role="status" className="callout callout-warning">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <section className="card" aria-labelledby="profile-fields">
        <h2 id="profile-fields">Profile</h2>
        <Fields
          rows={[
            ["Family", policy.family_name],
            ["Status", policy.policy_status],
            ["Status in the file", policy.file_status],
            ["Admin override", policy.status_overridden ? "yes" : "no"],
            ["Version", String(policy.version)],
            ["Format version", policy.format_version],
            ["Source file", policy.source_file],
            ["Imported", formatTime(policy.imported_at)],
            ["Updated", formatTime(policy.updated_at)],
            ["Deleted", deleted ? formatTime(policy.deleted_at) : "no"],
          ]}
        />
      </section>
      <section className="stack" aria-labelledby="profile-plugins">
        <h2 id="profile-plugins">Plugins ({plugins.length})</h2>
        {plugins.map((plugin) => (
          <PluginCard key={plugin.plugin_uuid} plugin={plugin} />
        ))}
      </section>
    </main>
  );
}
