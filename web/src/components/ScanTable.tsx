import type { components } from "../api/schema";
import { formatTime } from "../format";

type Scan = components["schemas"]["ScanItem"];
export type ScanState = Scan["state"];

/**
 * Where the scan screens link to. The hash routes are TASK-251's, so the
 * screens take the links from whoever mounts them.
 */
export interface ScanLinks {
  readonly scansHref: string;
  readonly runScanHref: string;
  readonly scanHref: (scanId: string) => string;
  readonly resultsHref: (scanId: string) => string;
  /** Opens a scan's detail (after Run scan's 202, #154 (c)). */
  readonly openScan: (scanId: string) => void;
}

// A Record over the generated enum: a new state without a label fails typecheck.
const STATES: Record<ScanState, readonly [string, string]> = {
  queued: ["Queued", "badge badge-info"],
  running: ["Running", "badge badge-info"],
  completed: ["Completed", "badge badge-success"],
  partial: ["Partial", "badge badge-warning"],
  failed: ["Failed", "badge badge-danger"],
  cancelled: ["Cancelled", "badge badge-neutral"],
};

/** The six scan states (TS §4.4), in the order the filter offers them. */
export const SCAN_STATES = Object.keys(STATES) as ScanState[];

export function scanStateLabel(state: ScanState): string {
  return STATES[state][0];
}

const KINDS: Record<Scan["target_kind"], string> = {
  all: "All hosts",
  tags: "Tags",
  agents: "Chosen hosts",
};

export function ScanStateBadge({ state }: { readonly state: ScanState }) {
  return <span className={STATES[state][1]}>{STATES[state][0]}</span>;
}

/** Scan items as rows; the creation time links to the scan's detail. */
export function ScanTable({
  items,
  links,
}: {
  readonly items: readonly Scan[];
  readonly links: ScanLinks;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Created</th>
            <th>Profile</th>
            <th>Version</th>
            <th>Trigger</th>
            <th>Target</th>
            <th>State</th>
            <th>Finished</th>
          </tr>
        </thead>
        <tbody>
          {items.map((scan) => (
            <tr key={scan.scan_id}>
              <td>
                <a className="strong-link" href={links.scanHref(scan.scan_id)}>
                  {formatTime(scan.created_at)}
                </a>
              </td>
              <td className="wrap">{scan.policy_name}</td>
              <td>{scan.policy_version}</td>
              <td>{scan.trigger === "manual" ? "Manual" : "Scheduled"}</td>
              <td>
                {KINDS[scan.target_kind]} ({scan.resolved_count} hosts)
              </td>
              <td>
                <ScanStateBadge state={scan.state} />
              </td>
              <td>{formatTime(scan.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
