import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { StatusBadge } from "../components/StatusBadge";
import { formatTime } from "../format";

type Detail = components["schemas"]["AgentDetailItem"];
type OsInfo = components["schemas"]["OsInfoItem"];
type PackageLine = components["schemas"]["PackageLine"];
type Page = components["schemas"]["Page_AgentPackageItem_"];

export interface HostDetailProps {
  readonly agentId: string;
  readonly navigate: (route: Route) => void;
}

const PAGE_SIZE = 50;

type Load<T> =
  | { readonly kind: "loading" }
  | { readonly kind: "not-found" }
  | { readonly kind: "failed"; readonly problem: ProblemInfo | null }
  | { readonly kind: "ok"; readonly value: T };

function text(value: string | number | null): string {
  return value === null ? "unknown" : String(value);
}

/** A definition list of fixed labels and API values, all as text nodes. */
function Fields({ rows }: { rows: readonly (readonly [string, string])[] }) {
  return (
    <dl>
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Lines({ title, lines }: { title: string; lines: PackageLine[] }) {
  return (
    <section aria-label={title}>
      <h3>
        {title} ({lines.length})
      </h3>
      <ul>
        {lines.map((line, index) => (
          <li key={index}>
            {line.name} {line.version} {line.architecture} ({line.status})
          </li>
        ))}
      </ul>
    </section>
  );
}

function OsSection({ os }: { os: OsInfo | null }) {
  if (os === null) {
    return <p>No inventory yet.</p>;
  }
  return (
    <>
      <Fields
        rows={[
          ["OS", text(os.os_pretty_name)],
          ["OS id", text(os.os_id)],
          ["OS version id", text(os.os_version_id)],
          ["Kernel release", text(os.kernel_release)],
          ["Architecture", text(os.architecture)],
          ["CPU count", text(os.cpu_count)],
          ["Memory (MB)", text(os.memory_mb)],
          ["Uptime (s)", text(os.uptime_s)],
          ["Collected", formatTime(os.collected_at)],
        ]}
      />
      <h3>IP addresses</h3>
      <ul>
        {os.ip_addresses.map((address, index) => (
          <li key={index}>{address}</li>
        ))}
      </ul>
      <h3>Raw</h3>
      <pre>{JSON.stringify(os.raw, null, 2)}</pre>
    </>
  );
}

/** REQ-128. Mount it with `key={agentId}` so a new host starts on page 1. */
export function HostDetail({ agentId, navigate }: HostDetailProps) {
  const [detail, setDetail] = useState<Load<Detail>>({ kind: "loading" });
  const pages = useCursorPages();
  const [packages, setPackages] = useState<Load<Page>>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    api
      .GET("/api/v1/agents/{id}", { params: { path: { id: agentId } } })
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
  }, [agentId]);

  useEffect(() => {
    let active = true;
    const query =
      pages.cursor === null
        ? { limit: PAGE_SIZE }
        : { limit: PAGE_SIZE, cursor: pages.cursor };
    api
      .GET("/api/v1/agents/{id}/packages", {
        params: { path: { id: agentId }, query },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        if (data !== undefined) setPackages({ kind: "ok", value: data });
        else
          setPackages({ kind: "failed", problem: toProblem(error, response) });
      })
      .catch(() => {
        if (active) setPackages({ kind: "failed", problem: null });
      });
    return () => {
      active = false;
    };
  }, [agentId, pages.cursor]);

  const back = (
    <a
      href={formatHash({ name: "hosts" })}
      onClick={(event) => {
        event.preventDefault();
        navigate({ name: "hosts" });
      }}
    >
      Back to hosts
    </a>
  );
  if (detail.kind !== "ok") {
    return (
      <main>
        {back}
        {detail.kind === "loading" && <p>Loading.</p>}
        {detail.kind === "not-found" && <p role="alert">Host not found.</p>}
        {detail.kind === "failed" &&
          (detail.problem === null ? (
            <p role="alert">The manager is unavailable. Try again later.</p>
          ) : (
            <ProblemBanner problem={detail.problem} />
          ))}
      </main>
    );
  }
  const host = detail.value;
  const snapshot = host.last_snapshot;
  const page = packages.kind === "ok" ? packages.value : null;
  return (
    <main>
      {back}
      <h1>{host.hostname}</h1>
      <StatusBadge status={host.status} />
      <Fields
        rows={[
          ["Hostname", host.hostname],
          ["Machine-id", host.machine_id],
          ["Agent id", host.agent_id],
          ["Agent version", host.agent_version],
          ["Enrolled", formatTime(host.enrolled_at)],
          ["Last seen IP", text(host.last_seen_ip)],
          ["Last heartbeat", formatTime(host.last_heartbeat_at)],
          ["Last inventory", formatTime(host.last_inventory_at)],
          ["Token issued", formatTime(host.token_issued_at)],
          ["Token expires", formatTime(host.token_expires_at)],
          ["Token revoked", formatTime(host.token_revoked_at)],
          ["Tags", host.tags.length === 0 ? "none" : host.tags.join(", ")],
          [
            "Runner helpers",
            host.runner_helpers.length === 0
              ? "none"
              : host.runner_helpers.join(", "),
          ],
        ]}
      />
      <h2>Operating system</h2>
      <OsSection os={host.os_info} />
      {snapshot !== null && (
        <section aria-label="Added / removed since last snapshot">
          <h2>Added / removed since last snapshot</h2>
          <p>
            Snapshot {formatTime(snapshot.collected_at)},{" "}
            {snapshot.package_count} packages.
          </p>
          <Lines title="Added" lines={snapshot.added} />
          <Lines title="Removed" lines={snapshot.removed} />
        </section>
      )}
      <h2>Packages</h2>
      {packages.kind === "failed" &&
        (packages.problem === null ? (
          <p role="alert">The manager is unavailable. Try again later.</p>
        ) : (
          <ProblemBanner problem={packages.problem} />
        ))}
      {page !== null && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Version</th>
              <th>Architecture</th>
              <th>Status</th>
              <th>Source</th>
              <th>Size (KB)</th>
              <th>First seen</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((item, index) => (
              <tr key={index}>
                <td>{item.name}</td>
                <td>{item.version}</td>
                <td>{item.architecture}</td>
                <td>{item.status}</td>
                <td>{text(item.source_name)}</td>
                <td>{text(item.installed_size_kb)}</td>
                <td>{formatTime(item.first_seen_at)}</td>
                <td>{formatTime(item.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
    </main>
  );
}
