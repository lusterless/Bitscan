import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { setSession, useSession } from "../app/session";
import { ProblemBanner } from "../components/ProblemBanner";
import { QrCode } from "../components/QrCode";

type TotpEnrolRequest = components["schemas"]["TotpEnrolRequest"];

export interface TotpEnrolProps {
  readonly mode: "required" | "offer" | "manage";
  readonly onDone: () => void;
  /** Only for "offer": the user chose "Not now". */
  readonly onSkip?: () => void;
}

type Step =
  | { readonly kind: "start" }
  | { readonly kind: "confirm"; readonly secret: string; readonly uri: string };

const START: Step = { kind: "start" };

const INTRO = {
  required: "Admin accounts must set up TOTP before they can continue.",
  offer: "Set up TOTP to protect your account, or do it later from Account.",
  manage: "Set up TOTP for your account.",
} as const;

/**
 * REQ-122. The new secret and URI live only in `step` and are dropped on
 * success, on any refusal of the code and when the screen unmounts; the
 * current password and codes are emptied before each request is sent.
 */
export function TotpEnrol({ mode, onDone, onSkip }: TotpEnrolProps) {
  const session = useSession();
  const replacing = mode === "manage" && session?.totpEnrolled === true;
  const [step, setStep] = useState<Step>(START);
  const [currentPassword, setCurrentPassword] = useState("");
  const [currentCode, setCurrentCode] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);

  async function send(body: TotpEnrolRequest): Promise<void> {
    setNote(null);
    setProblem(null);
    setBusy(true);
    try {
      const { data, error, response } = await api.POST(
        "/api/v1/auth/totp/enrol",
        { body },
      );
      if (data !== undefined) {
        if ("secret" in data) {
          setStep({
            kind: "confirm",
            secret: data.secret,
            uri: data.otpauth_uri,
          });
        } else {
          // The confirm answer is a new TOTP-verified session (TS §6.2 L1089).
          setStep(START);
          setSession(data);
          onDone();
        }
        return;
      }
      const info = toProblem(error, response);
      if (
        step.kind === "confirm" &&
        (info.status === 403 || info.status === 409)
      ) {
        // A wrong code discards the pending secret on the server; so does expiry.
        setStep(START);
        setNote(
          info.status === 403
            ? "The code was not accepted. Start again to get a new secret."
            : "The enrolment expired. Start again.",
        );
      } else if (
        replacing &&
        info.status === 403 &&
        info.type === "forbidden"
      ) {
        setNote("The current password or code is not valid.");
      } else {
        setProblem(info);
      }
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  function start(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const body = replacing
      ? { current_password: currentPassword, current_code: currentCode }
      : {};
    setCurrentPassword("");
    setCurrentCode("");
    void send(body);
  }

  function confirm(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const body = { totp_code: code };
    setCode("");
    void send(body);
  }

  return (
    <main>
      <h1>{replacing ? "Replace TOTP" : "Set up TOTP"}</h1>
      {note !== null && <p role="alert">{note}</p>}
      <ProblemBanner problem={problem} />
      {step.kind === "start" ? (
        <form onSubmit={start}>
          <p>
            {replacing
              ? "Enter your current password and a current code to get a new secret."
              : INTRO[mode]}
          </p>
          {replacing && (
            <>
              <label>
                Current password
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={currentPassword}
                  onChange={(event) => {
                    setCurrentPassword(event.target.value);
                  }}
                />
              </label>
              <label>
                Current code
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  value={currentCode}
                  onChange={(event) => {
                    setCurrentCode(event.target.value);
                  }}
                />
              </label>
            </>
          )}
          <button type="submit" disabled={busy}>
            Start
          </button>
          {mode === "offer" && onSkip !== undefined && (
            <button type="button" onClick={onSkip}>
              Not now
            </button>
          )}
        </form>
      ) : (
        <form onSubmit={confirm}>
          <p>
            Add this secret to your authenticator app, then enter the code it
            shows.
          </p>
          <QrCode value={step.uri} label="QR code of the TOTP secret" />
          <p>
            Secret: <code>{step.secret}</code>
          </p>
          <p>
            URI: <code>{step.uri}</code>
          </p>
          <label>
            Code
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
              }}
            />
          </label>
          <button type="submit" disabled={busy || code === ""}>
            Confirm
          </button>
        </form>
      )}
    </main>
  );
}
