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
