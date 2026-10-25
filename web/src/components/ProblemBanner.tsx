import { messageFor, type ProblemInfo } from "../app/problems";
import { formatHash } from "../app/router";
import { signOut } from "../app/session";

export interface ProblemBannerProps {
  /** Nothing is rendered for null. */
  readonly problem: ProblemInfo | null;
}

/**
 * REQ-126: the fixed message for the problem, then the server's `detail` as a
 * text node. A TOTP-session refusal offers only a fresh sign-in with password
 * and code (#85 (b)); there is never a field for an API token.
 */
export function ProblemBanner({ problem }: ProblemBannerProps) {
  if (problem === null) {
    return null;
  }
  const message = messageFor(problem);
  return (
    <div role="alert">
      <p>{message.text}</p>
      {problem.detail !== null && <p>{problem.detail}</p>}
      {message.action === "sign-in-again" && (
        <button
          type="button"
          onClick={() => {
            void signOut();
          }}
        >
          Sign in again
        </button>
      )}
      {message.action === "totp-enrol" && (
        <a href={formatHash({ name: "totp" })}>Set up TOTP</a>
      )}
    </div>
  );
}
