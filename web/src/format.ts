function pad(value: number): string {
  return value < 10 ? "0" + String(value) : String(value);
}

/**
 * An RFC 3339 time from the API (TS §6.3) as `YYYY-MM-DD HH:MM:SS UTC`;
 * a null time is "never". A value that does not parse is shown unchanged,
 * as text.
 */
export function formatTime(value: string | null): string {
  if (value === null) {
    return "never";
  }
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) {
    return value;
  }
  return (
    String(time.getUTCFullYear()) +
    "-" +
    pad(time.getUTCMonth() + 1) +
    "-" +
    pad(time.getUTCDate()) +
    " " +
    pad(time.getUTCHours()) +
    ":" +
    pad(time.getUTCMinutes()) +
    ":" +
    pad(time.getUTCSeconds()) +
    " UTC"
  );
}

/**
 * A host score (TS §4.5 L604: passed / (passed + failed), in [0, 1]) as a
 * percentage with one decimal, rounded down (#149), so "100.0 %" means every
 * rated check passed: 0.9996 is "99.9 %". A null score (nothing rated) is
 * "n/a". The tenths are built from integers, so no float is ever rounded for
 * display (`toFixed` would round 0.9996 up).
 */
export function formatScore(score: number | null): string {
  if (score === null || !Number.isFinite(score)) {
    return "n/a";
  }
  // Exact for every k / n: checked for all n up to 5,000 and sampled to 40,000.
  const tenths = Math.floor(score * 1000);
  const whole = Math.floor(tenths / 10);
  return String(whole) + "." + String(tenths - whole * 10) + " %";
}

/** The error count shown beside a score (#149): "0 errors", "1 error". */
export function formatErrorCount(errors: number): string {
  return String(errors) + (errors === 1 ? " error" : " errors");
}
