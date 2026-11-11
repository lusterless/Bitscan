// TASK-239 TEST (TP-M11-07): CHK-M11-261, plants CHK-M11-363, -364, -377.
// Expected values: TS §4.5 L604 (score = PASS / (PASS + FAIL), "shown with
// the error count beside it", NULL "shown as 'n/a'"); REQ-280 (1); #149
// (approved 2026-11-08: one decimal, ROUNDED DOWN, "100.0 %" only when every
// rated check passed; "1 error", "5 errors", "0 errors").
import "../test/harness";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatErrorCount, formatScore } from "../format";
import { Score } from "./Score";

/** The rendered text with runs of whitespace (incl. NBSP) as one space. */
function shown(score: number | null, errors: number): string {
  const { container } = render(<Score score={score} errors={errors} />);
  return (container.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("CHK-M11-261 Score: REQ-280 (1) as written", () => {
  it("0.75 with 5 errors shows 75.0 % and 5 errors beside it", () => {
    expect(shown(0.75, 5)).toBe("75.0 % 5 errors");
  });

  it("null shows n/a, never a percentage (plant CHK-M11-363)", () => {
    const text = shown(null, 3);
    expect(text).toBe("n/a 3 errors");
    expect(text).not.toContain("%");
  });

  it("0.9996 shows 99.9 % (rounded down, plant CHK-M11-364)", () => {
    expect(shown(0.9996, 0)).toBe("99.9 % 0 errors");
  });

  it("1.0 shows 100.0 %", () => {
    expect(shown(1, 0)).toBe("100.0 % 0 errors");
  });

  it("the error count reads 1 error, 0 errors, 5 errors", () => {
    expect(shown(0.5, 1)).toBe("50.0 % 1 error");
    expect(shown(0.5, 0)).toBe("50.0 % 0 errors");
    expect(shown(0.5, 2)).toBe("50.0 % 2 errors");
  });

  it("the errors are beside the score in their own element", () => {
    const { container } = render(<Score score={0.75} errors={5} />);
    const parts = Array.from(container.querySelectorAll("span span")).map(
      (e) => e.textContent,
    );
    expect(parts).toEqual(["75.0 %", "5 errors"]);
  });

  it("errors are shown beside n/a too (a host with only ERRORs)", () => {
    expect(shown(null, 12)).toBe("n/a 12 errors");
  });
});

describe("CHK-M11-261 formatScore: the rounded-down boundaries (#149)", () => {
  // Values the manager sends are unrounded passed / (passed + failed).
  const cases: [number, string][] = [
    [0, "0.0 %"],
    [0.0004, "0.0 %"],
    [0.001, "0.1 %"],
    [1 / 3, "33.3 %"],
    [2 / 3, "66.6 %"], // nearest would be 66.7
    [0.75, "75.0 %"],
    [0.9996, "99.9 %"], // nearest would be 100.0
    [2499 / 2500, "99.9 %"],
    [0.99999, "99.9 %"],
    [1, "100.0 %"],
  ];
  for (const [score, text] of cases) {
    it(String(score) + " -> " + text, () => {
      expect(formatScore(score)).toBe(text);
    });
  }

  // Exact one-decimal percentages must not drop a tenth through float error
  // (plant CHK-M11-377: floor(s * 100 * 10) shows 28.9, 56.9, 57.9, 57.4).
  const exact: [number, number, string][] = [
    [29, 100, "29.0 %"],
    [57, 100, "57.0 %"],
    [58, 100, "58.0 %"],
    [23, 40, "57.5 %"],
    [29, 50, "58.0 %"],
    [46, 80, "57.5 %"],
  ];
  for (const [p, t, text] of exact) {
    it(String(p) + "/" + String(t) + " -> " + text, () => {
      expect(formatScore(p / t)).toBe(text);
    });
  }

  it("every k/n with n up to 400 equals the exact integer floor", () => {
    const wrong: string[] = [];
    for (let n = 1; n <= 400; n++) {
      for (let k = 0; k <= n; k++) {
        const tenths = Math.floor((1000 * k - ((1000 * k) % n)) / n);
        const want =
          String(Math.floor(tenths / 10)) + "." + String(tenths % 10) + " %";
        if (formatScore(k / n) !== want) {
          wrong.push(String(k) + "/" + String(n));
        }
      }
    }
    expect(wrong).toEqual([]);
  });

  it("null is n/a", () => {
    expect(formatScore(null)).toBe("n/a");
  });
});

describe("CHK-M11-261 formatErrorCount", () => {
  it("singular only for exactly one", () => {
    expect(formatErrorCount(0)).toBe("0 errors");
    expect(formatErrorCount(1)).toBe("1 error");
    expect(formatErrorCount(5)).toBe("5 errors");
    expect(formatErrorCount(10000)).toBe("10000 errors");
  });
});
