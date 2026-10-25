import { useMemo } from "react";
import qrcode from "qrcode-generator";

export interface QrCodeProps {
  readonly value: string;
  readonly label: string;
}

const MARGIN = 4;

interface Drawing {
  readonly path: string;
  readonly size: number;
}

/** The dark modules as one SVG path, or null if the value is too long. */
function draw(value: string): Drawing | null {
  try {
    const code = qrcode(0, "M");
    code.addData(value);
    code.make();
    const count = code.getModuleCount();
    let path = "";
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) {
        if (code.isDark(row, col)) {
          path += "M" + String(col + MARGIN) + " " + String(row + MARGIN);
          path += "h1v1h-1z";
        }
      }
    }
    return { path, size: count + 2 * MARGIN };
  } catch {
    return null;
  }
}

/**
 * PD-28 (e): the code is drawn as SVG elements from the library's module
 * matrix. The library's HTML and data-URL helpers are never used, and the
 * secret is always shown as text next to it.
 */
export function QrCode({ value, label }: QrCodeProps) {
  const drawing = useMemo(() => draw(value), [value]);
  if (drawing === null) {
    return null;
  }
  const { path, size } = drawing;
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={"0 0 " + String(size) + " " + String(size)}
      width="200"
      height="200"
    >
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}
