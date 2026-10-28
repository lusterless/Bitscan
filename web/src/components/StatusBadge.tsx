import type { components } from "../api/schema";

export type AgentStatus = components["schemas"]["AgentItem"]["status"];

// A Record over the generated enum (REQ-117): a status without a label, or a
// new enum value, fails `npm run typecheck` (REQ-127 (2)).
const LABELS: Record<AgentStatus, string> = {
  awaiting_approval: "Awaiting approval",
  enrolled: "Enrolled",
  online: "Online",
  stale: "Stale",
  offline: "Offline",
  decommissioned: "Decommissioned",
};

const TONES: Record<AgentStatus, string> = {
  awaiting_approval: "badge badge-warning",
  enrolled: "badge badge-info",
  online: "badge badge-success",
  stale: "badge badge-warning",
  offline: "badge badge-danger",
  decommissioned: "badge badge-neutral",
};

export interface StatusBadgeProps {
  readonly status: AgentStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className={TONES[status]}>{LABELS[status]}</span>;
}
