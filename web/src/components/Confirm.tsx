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
}

/** An inline confirmation step (no `window.confirm`, no portal). */
export function Confirm({
  label,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  disabled = false,
}: ConfirmProps) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        type="button"
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
    <div role="alertdialog" aria-label={label}>
      <p>{message}</p>
      <button
        type="button"
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
        onClick={() => {
          setOpen(false);
        }}
      >
        Cancel
      </button>
    </div>
  );
}
