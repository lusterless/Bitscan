import type { components } from "../api/schema";

export type Verdict = NonNullable<
  components["schemas"]["ScanResultItem"]["result"]
>;

// A Record over the generated enum: a new verdict without a label or tone
// fails `npm run typecheck`.
const LABELS: Record<Verdict, string> = {
  PASS: "PASS",
  FAIL: "FAIL",
  ERROR: "ERROR",
};

const TONES: Record<Verdict, string> = {
  PASS: "badge badge-success",
  FAIL: "badge badge-danger",
  ERROR: "badge badge-warning",
};

/** A plugin with no result in its unit (TS §4.4 L585). */
export const NOT_RUN_LABEL = "Not run";

function Badge({ verdict }: { readonly verdict: Verdict | null }) {
  if (verdict === null) {
    return <span className="badge badge-neutral">{NOT_RUN_LABEL}</span>;
  }
  return <span className={TONES[verdict]}>{LABELS[verdict]}</span>;
}

export interface ResultBadgeProps {
  /** The current (effective) verdict; null is Not run. */
  readonly result: Verdict | null;
  /** The stored verdict the agent's output first gave (TS §4.5 L603). */
  readonly originalResult: Verdict | null;
  /** True when the result has been re-evaluated (`reevaluated_at` set). */
  readonly reevaluated: boolean;
}

/**
 * The current verdict and, when the result has been re-evaluated, the
 * original one beside it, even when the two are equal
 * (`.claude/rules/web-ui.md`: show both after a re-evaluation).
 */
export function ResultBadge({
  result,
  originalResult,
  reevaluated,
}: ResultBadgeProps) {
  if (!reevaluated || originalResult === null) {
    return <Badge verdict={result} />;
  }
  return (
    <span className="result-verdicts">
      <Badge verdict={result} />{" "}
      <span className="result-original muted">
        original <Badge verdict={originalResult} />
      </span>
    </span>
  );
}
