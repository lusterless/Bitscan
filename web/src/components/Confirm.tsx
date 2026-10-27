import { useState } from "react";

export interface ConfirmProps {
  /** Text of the button that opens the question, for example "Revoke". */
  readonly label: string;
  /** The question; rendered as text. */
  readonly message: string;
  readonly confirmLabel?: string;
  /** Called once per confirmation, never on the first click or on cancel. */
  readonly onConfirm: () => void;
  readonly disabled?: boolean;
  /** How the opening and confirming buttons look; the default is neutral. */
  readonly tone?: "primary" | "danger";
}

/** An inline confirmation step (no `window.confirm`, no portal). */
export function Confirm({
  label,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  disabled = false,
  tone,
}: ConfirmProps) {
  const [open, setOpen] = useState(false);
  const toned = tone === undefined ? "btn btn-sm" : "btn btn-sm btn-" + tone;
  if (!open) {
    return (
      <button
        type="button"
        className={toned}
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
      >
        {label}
      </button>
    );
  }
  return (
    <div role="alertdialog" aria-label={label} className="confirm">
      <p>{message}</p>
      <button
        type="button"
        className={tone === undefined ? "btn btn-sm btn-primary" : toned}
        disabled={disabled}
        onClick={() => {
          setOpen(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => {
          setOpen(false);
        }}
      >
        Cancel
      </button>
    </div>
  );
}
