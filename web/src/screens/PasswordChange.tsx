import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { toProblem, type ProblemInfo } from "../app/problems";
import { clearSession } from "../app/session";
import { ProblemBanner } from "../components/ProblemBanner";

export interface PasswordChangeProps {
  readonly onChanged: () => void;
}

// TS §6.2: at least 12 characters (counted as code points, like the server).
const MIN_LENGTH = 12;

/**
 * REQ-123. The passwords live only in this component's state; all three
 * fields are emptied before the request is sent. The server stays the judge.
 */
export function PasswordChange({ onChanged }: PasswordChangeProps) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setProblem(null);
    if (Array.from(next).length < MIN_LENGTH) {
      setNote("The new password must be at least 12 characters.");
      return;
    }
    if (next !== repeat) {
      setNote("The new passwords do not match.");
      return;
    }
    const body = { current_password: current, new_password: next };
    setCurrent("");
    setNext("");
    setRepeat("");
    setNote(null);
    setBusy(true);
    try {
      const { error, response } = await api.POST("/api/v1/auth/password", {
        body,
      });
      if (response.status === 204) {
        // Every session of the user has ended (#53 (a)): sign in again.
        clearSession();
        onChanged();
        return;
      }
      const info = toProblem(error, response);
      if (info.status === 403 && info.type === "forbidden") {
        setNote("The current password is not correct.");
      } else {
        setProblem(info);
      }
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  function field(
    label: string,
    value: string,
    set: (value: string) => void,
    autoComplete: "current-password" | "new-password",
  ) {
    return (
      <label>
        {label}
        <input
          type="password"
          autoComplete={autoComplete}
          required
          value={value}
          onChange={(event) => {
            set(event.target.value);
          }}
        />
      </label>
    );
  }

  return (
    <main>
      <h1>Change password</h1>
      {note !== null && <p role="alert">{note}</p>}
      <ProblemBanner problem={problem} />
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        {field("Current password", current, setCurrent, "current-password")}
        {field("New password", next, setNext, "new-password")}
        {field("Repeat new password", repeat, setRepeat, "new-password")}
        <button type="submit" disabled={busy}>
          Change password
        </button>
      </form>
    </main>
  );
}
