import { formatErrorCount, formatScore } from "../format";

export interface ScoreProps {
  /** The host score from the API: a number in [0, 1], or null. */
  readonly score: number | null;
  /** The host's ERROR count, shown beside the score (TS §4.5 L604). */
  readonly errors: number;
}

/**
 * A host score per #149: "75.0 %" (rounded down) or "n/a", with the error
 * count beside it, whatever the score.
 */
export function Score({ score, errors }: ScoreProps) {
  return (
    <span className="score">
      <span className="score-value">{formatScore(score)}</span>{" "}
      <span className="score-errors muted">{formatErrorCount(errors)}</span>
    </span>
  );
}
