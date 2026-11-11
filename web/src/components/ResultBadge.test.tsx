// TASK-239 TEST (TP-M11-07): CHK-M11-262, plant CHK-M11-365 (W2 half).
// Expected values: TS §4.5 L603 ("The API returns both `result` and
// `original_result`"; views use the latest re-evaluation); TS §4.4 L585
// (plugins with no result show as Not run); REQ-281 (1) ("A re-evaluated row
// shows both verdicts, another row one, a null result 'Not run'");
// `.claude/rules/web-ui.md` ("Show both the current verdict and
// `original_result` when a result has been re-evaluated").
import "../test/harness";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultBadge, type Verdict } from "./ResultBadge";

const VERDICTS: Verdict[] = ["PASS", "FAIL", "ERROR"];

function badges(
  result: Verdict | null,
  originalResult: Verdict | null,
  reevaluated: boolean,
): { text: string; labels: string[] } {
  const { container } = render(
    <ResultBadge
      result={result}
      originalResult={originalResult}
      reevaluated={reevaluated}
    />,
  );
  return {
    text: (container.textContent ?? "").replace(/\s+/g, " ").trim(),
    labels: Array.from(container.querySelectorAll(".badge")).map(
      (b) => b.textContent ?? "",
    ),
  };
}

describe("CHK-M11-262 one verdict when never re-evaluated", () => {
  for (const v of VERDICTS) {
    it(v + " shows exactly " + v, () => {
      const b = badges(v, v, false);
      expect(b.labels).toEqual([v]);
      expect(b.text).toBe(v);
    });
  }

  it("a null result is Not run, not FAIL and not empty", () => {
    const b = badges(null, null, false);
    expect(b.labels).toEqual(["Not run"]);
    expect(b.text).not.toMatch(/PASS|FAIL|ERROR/);
  });

  it("the three verdicts are told apart by more than their text", () => {
    const tones = VERDICTS.map((v) => {
      const { container } = render(
        <ResultBadge result={v} originalResult={v} reevaluated={false} />,
      );
      return container.querySelector(".badge")?.className ?? "";
    });
    expect(new Set(tones).size).toBe(3);
  });
});

describe("CHK-M11-262 both verdicts when re-evaluated (plant CHK-M11-365)", () => {
  it("FAIL re-evaluated to PASS shows PASS first, then the original FAIL", () => {
    const b = badges("PASS", "FAIL", true);
    expect(b.labels).toEqual(["PASS", "FAIL"]);
    expect(b.text).toBe("PASS original FAIL");
  });

  it("ERROR re-evaluated to FAIL shows both", () => {
    expect(badges("FAIL", "ERROR", true).labels).toEqual(["FAIL", "ERROR"]);
  });

  it("an unchanged verdict after re-evaluation still shows both (the rule says when re-evaluated, not when different)", () => {
    const b = badges("PASS", "PASS", true);
    expect(b.labels).toEqual(["PASS", "PASS"]);
    expect(b.text).toContain("original");
  });

  it("every pair of verdicts shows current then original", () => {
    for (const cur of VERDICTS) {
      for (const orig of VERDICTS) {
        expect(badges(cur, orig, true).labels).toEqual([cur, orig]);
      }
    }
  });

  it("a different original without the re-evaluated flag is not shown", () => {
    // The original equals the stored verdict, so only a re-evaluation can
    // make them differ; without one the row shows one verdict.
    expect(badges("PASS", "FAIL", false).labels).toEqual(["PASS"]);
  });
});
