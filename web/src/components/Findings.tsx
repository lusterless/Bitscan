import type { components } from "../api/schema";

type Finding = components["schemas"]["ImportFinding"];

export interface FindingsProps {
  readonly findings: readonly Finding[];
  /** The table's accessible name. */
  readonly label: string;
}

/**
 * The SR §3.5 findings of one import, warnings included (#110). Line,
 * element, code and message come from the file and stay text nodes (TS §6.3).
 */
export function Findings({ findings, label }: FindingsProps) {
  if (findings.length === 0) {
    return <p className="muted">No findings.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="table" aria-label={label}>
        <thead>
          <tr>
            <th>Line</th>
            <th>Element</th>
            <th>Code</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, index) => (
            <tr key={index}>
              <td>{finding.line === null ? "none" : finding.line}</td>
              <td className="mono wrap">{finding.element ?? "file"}</td>
              <td className="mono">{finding.code}</td>
              <td className="wrap">{finding.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
