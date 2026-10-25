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

export interface StatusBadgeProps {
  readonly status: AgentStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span>{LABELS[status]}</span>;
}
