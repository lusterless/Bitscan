import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import { toProblem, type ProblemInfo } from "../app/problems";
import {
  currentSession,
  nextScreen,
  setSession,
  type NextScreen,
} from "../app/session";
import { ProblemBanner } from "../components/ProblemBanner";

export interface SignInProps {
  readonly onSignedIn: (next: NextScreen) => void;
  readonly notice?: "password-changed";
}

type Failure =
  | { readonly kind: "rejected" }
  | { readonly kind: "unreachable" }
  | { readonly kind: "problem"; readonly problem: ProblemInfo };

// setTimeout fires at once for delays over 2^31 - 1 ms.
const MAX_TIMER_MS = 2_147_483_647;

/**
 * REQ-121. The password and code live only in this component's state and are
 * emptied after every attempt; on success the token goes to the session store
 * (TASK-116) and nowhere else.
 */
export function SignIn({ onSignedIn, notice }: SignInProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [waitS, setWaitS] = useState<number | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    if (waitS === null) {
      return;
    }
    const timer = setTimeout(
      () => {
        setWaitS(null);
      },
      Math.min(waitS * 1000, MAX_TIMER_MS),
    );
    return () => {
      clearTimeout(timer);
    };
  }, [waitS]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const body = {
      username,
      password,
      totp_code: code === "" ? null : code,
    };
    setPassword("");
    setCode("");
    setFailure(null);
    setBusy(true);
    try {
      const { data, error, response } = await api.POST("/api/v1/auth/login", {
        body,
      });
      if (data !== undefined) {
        setSession(data);
        const view = currentSession();
        if (view !== null) {
          onSignedIn(nextScreen(view));
        }
        return;
      }
      if (response.status === 401) {
        // #48: every refused sign-in looks the same, so `detail` is not shown.
        setFailure({ kind: "rejected" });
        return;
      }
      const problem = toProblem(error, response);
      if (response.status === 429 && problem.retryAfterS !== null) {
        setWaitS(problem.retryAfterS);
      }
      setFailure({ kind: "problem", problem });
    } catch {
      setFailure({ kind: "unreachable" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-main">
      <h1>Sign in</h1>
      <p className="page-subtitle">Use your Bitscan account.</p>
      {notice === "password-changed" && (
        <p role="status" className="callout callout-success">
          Your password was changed. Sign in again.
        </p>
      )}
      {failure?.kind === "rejected" && (
        <p role="alert" className="callout callout-danger">
          Sign-in failed. Check your username, password and TOTP code.
        </p>
      )}
      {failure?.kind === "unreachable" && (
        <p role="alert" className="callout callout-danger">
          The manager is unavailable. Try again later.
        </p>
      )}
      {failure?.kind === "problem" && (
        <ProblemBanner problem={failure.problem} />
      )}
      <form
        className="form"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label>
          Username
          <input
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
            }}
          />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
        </label>
        <label>
          TOTP code (required for admins and accounts with TOTP)
          <input
            name="totp_code"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(event) => {
              setCode(event.target.value);
            }}
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary btn-block"
          disabled={busy || waitS !== null}
        >
          Sign in
        </button>
      </form>
    </main>
  );
}
