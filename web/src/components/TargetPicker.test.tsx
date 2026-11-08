// TASK-256 TEST (TP-M11-14): CHK-M11-273, CHK-M11-274, plants CHK-M11-375
// (picker half), CHK-M11-379.
// Expected values: TS §4.4 L555 (three target forms); #154 (a) ("All hosts",
// "Hosts with any of these tags" checked against the #68 rule before
// sending, "These hosts" chosen from GET /agents, paged); #122 (b) (exactly
// one key; agents 1-10,000; tags 1-32 distinct, each 1-64 characters from
// [A-Za-z0-9._:-]; all: true); TS §6.3 L1143 (plain text).
import {
  answer,
  callsTo,
  json,
  queryOf,
  resetHttp,
  bsu,
  loginResponse,
} from "../test/harness";
import {
  IMG,
  SCRIPT,
  agentItem,
  noInjectedMarkup,
  pageOf,
  settle,
  uuid,
  at,
} from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession } from "../app/session";
import {
  ALL_HOSTS,
  TargetPicker,
  describeTarget,
  fromTarget,
  toTarget,
  type TargetValue,
} from "./TargetPicker";

const TAG_RULE =
  "Tags are 1 to 32 names of 1 to 64 characters: letters, digits and . _ : -";
const AGENTS = "/api/v1/agents";

function tags(text: string): TargetValue {
  return { ...ALL_HOSTS, kind: "tags", tags: text };
}
function agents(ids: string[]): TargetValue {
  return { ...ALL_HOSTS, kind: "agents", agents: ids };
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("operator", true, bsu("O")));
});
afterEach(() => {
  clearSession();
});

// ------------------------------------------------------------ CHK-M11-274

describe("CHK-M11-274 toTarget: exactly one key per form (#122 (b))", () => {
  it("all hosts is {all: true}", () => {
    expect(toTarget(ALL_HOSTS)).toEqual({ all: true });
  });

  it("tags is {tags: [...]}, split on commas and spaces, typed order kept", () => {
    expect(toTarget(tags("prod-web, db  x.y:z_1"))).toEqual({
      tags: ["prod-web", "db", "x.y:z_1"],
    });
  });

  it("a repeated tag is sent once, so the body holds distinct tags", () => {
    expect(toTarget(tags("a, b, a"))).toEqual({ tags: ["a", "b"] });
  });

  it("agents is {agents: [...]}", () => {
    expect(toTarget(agents([uuid(1), uuid(2)]))).toEqual({
      agents: [uuid(1), uuid(2)],
    });
  });

  it("each body has exactly one key", () => {
    for (const v of [ALL_HOSTS, tags("a"), agents([uuid(1)])]) {
      const body = toTarget(v);
      expect(typeof body).toBe("object");
      expect(Object.keys(body as object)).toHaveLength(1);
    }
  });
});

describe("CHK-M11-273 the #68 tag check before sending (plant CHK-M11-379)", () => {
  const ok64 = "a".repeat(64);
  it("64 characters accepted, 65 refused", () => {
    expect(toTarget(tags(ok64))).toEqual({ tags: [ok64] });
    expect(toTarget(tags("a".repeat(65)))).toBe(TAG_RULE);
  });

  it("32 distinct tags accepted, 33 refused", () => {
    const n = (k: number) =>
      Array.from({ length: k }, (_, i) => "t" + String(i)).join(",");
    expect(toTarget(tags(n(32)))).toEqual({ tags: n(32).split(",") });
    expect(toTarget(tags(n(33)))).toBe(TAG_RULE);
  });

  it("every allowed character class passes", () => {
    expect(toTarget(tags("AZaz09._:-"))).toEqual({ tags: ["AZaz09._:-"] });
  });

  for (const bad of [
    "a/b",
    "<b>",
    "a<script>",
    "café",
    "日本",
    "a;b",
    "a*",
    "a'b",
    '"a"',
    "a=b",
    "a@b",
  ]) {
    it("refused: " + bad, () => {
      expect(toTarget(tags(bad))).toBe(TAG_RULE);
    });
  }

  it("empty and separator-only input is refused (no tag)", () => {
    expect(toTarget(tags(""))).toBe(TAG_RULE);
    expect(toTarget(tags(" , ,, "))).toBe(TAG_RULE);
  });

  it("a space separates rather than joining (no tag ever holds a space)", () => {
    const body = toTarget(tags("a b"));
    expect(body).toEqual({ tags: ["a", "b"] });
  });
});

describe("CHK-M11-273 the host count bounds (#122 (b))", () => {
  it("no host chosen is refused", () => {
    expect(toTarget(agents([]))).toBe("Choose at least one host.");
  });
  it("10,000 accepted, 10,001 refused", () => {
    const ids = Array.from({ length: 10_001 }, (_, i) => uuid(i));
    expect(toTarget(agents(ids.slice(0, 10_000)))).toEqual({
      agents: ids.slice(0, 10_000),
    });
    expect(toTarget(agents(ids))).toBe("Choose at most 10,000 hosts.");
  });
});

describe("CHK-M11-274 round trips", () => {
  const stored: Record<string, unknown>[] = [
    { all: true },
    { tags: ["prod-web", "db"] },
    { agents: [uuid(1), uuid(2), uuid(3)] },
  ];
  for (const t of stored) {
    it(
      "toTarget(fromTarget(" + JSON.stringify(t) + ")) is the stored target",
      () => {
        expect(toTarget(fromTarget(t))).toEqual(t);
      },
    );
  }

  for (const v of [ALL_HOSTS, tags("a b,c"), agents([uuid(4)])]) {
    it(
      "fromTarget(toTarget(v)) keeps the form and its values: " + v.kind,
      () => {
        const body = toTarget(v);
        expect(typeof body).toBe("object");
        const back = fromTarget(body as Record<string, unknown>);
        expect(back.kind).toBe(v.kind);
        expect(toTarget(back)).toEqual(body);
      },
    );
  }

  it("a stored target with resolved_agents still reads as its requested form", () => {
    expect(
      toTarget(fromTarget({ tags: ["db"], resolved_agents: [uuid(1)] })),
    ).toEqual({
      tags: ["db"],
    });
    expect(fromTarget({ all: true, resolved_agents: [uuid(1)] }).kind).toBe(
      "all",
    );
  });
});

describe("CHK-M11-274 describeTarget in plain text", () => {
  it("names each form", () => {
    expect(describeTarget({ all: true })).toBe("All hosts");
    expect(describeTarget({ tags: ["a", "b"] })).toBe(
      "Hosts with any of the tags: a, b",
    );
    expect(describeTarget({ agents: [uuid(1), uuid(2)] })).toBe(
      "2 chosen hosts",
    );
    expect(describeTarget({})).toBe("Unknown target");
    expect(describeTarget({ all: "true" })).toBe("Unknown target");
  });

  it("a stored <script> tag value stays text when rendered", () => {
    const { container } = render(<p>{describeTarget({ tags: [SCRIPT] })}</p>);
    expect(container.textContent).toBe("Hosts with any of the tags: " + SCRIPT);
    expect(noInjectedMarkup(container)).toEqual({ scripts: 0, imgs: 0 });
  });
});

// ------------------------------------------------------------ CHK-M11-273 UI

function Harness({ start = ALL_HOSTS }: { start?: TargetValue }) {
  const [value, setValue] = useState<TargetValue>(start);
  return (
    <>
      <TargetPicker value={value} onChange={setValue} />
      <output data-testid="body">{JSON.stringify(toTarget(value))}</output>
    </>
  );
}

function body(): unknown {
  const text = screen.getByTestId("body").textContent ?? "";
  return JSON.parse(text) as unknown;
}

describe("CHK-M11-273 the picker", () => {
  it("offers exactly the three forms, All hosts first and chosen", () => {
    render(<Harness />);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.parentElement?.textContent)).toEqual([
      "All hosts",
      "Hosts with any of these tags",
      "These hosts",
    ]);
    expect((radios[0] as HTMLInputElement).checked).toBe(true);
    expect(body()).toEqual({ all: true });
    expect(callsTo(AGENTS)).toHaveLength(0);
  });

  it("tags: the typed text becomes the tags body; a bad tag gives the rule", async () => {
    render(<Harness />);
    fireEvent.click(
      screen.getByRole("radio", { name: "Hosts with any of these tags" }),
    );
    const input = screen.getByRole("textbox", { name: /Tags/ });
    fireEvent.change(input, { target: { value: "prod-web db" } });
    expect(body()).toEqual({ tags: ["prod-web", "db"] });
    fireEvent.change(input, { target: { value: "prod web<" } });
    expect(body()).toBe(TAG_RULE);
    await settle();
    expect(callsTo(AGENTS)).toHaveLength(0);
  });

  it("these hosts: GET /agents through the client, paged; the choice survives paging", async () => {
    const all = Array.from({ length: 53 }, (_, i) => agentItem(i));
    answer((call) =>
      json(200, pageOf(all, queryOf(call).cursor, Number(queryOf(call).limit))),
    );
    render(<Harness />);
    fireEvent.click(screen.getByRole("radio", { name: "These hosts" }));
    await settle();
    const first = callsTo(AGENTS)[0];
    expect(first?.authorization).toBe("Bearer " + bsu("O"));
    expect(queryOf(at(callsTo(AGENTS), 0))).toEqual({ limit: "50" });
    expect(body()).toBe("Choose at least one host.");

    const hosts = screen.getByRole("group", { name: "Hosts" });
    fireEvent.click(within(hosts).getByRole("checkbox", { name: /host-3\b/ }));
    expect(body()).toEqual({ agents: [uuid(3)] });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await settle();
    expect(queryOf(at(callsTo(AGENTS), 1))).toEqual({
      limit: "50",
      cursor: "p-50",
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /host-52\b/ }));
    expect(body()).toEqual({ agents: [uuid(3), uuid(52)] });
    expect(screen.getByText("Hosts (2 chosen)")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await settle();
    expect(
      (screen.getByRole("checkbox", { name: /host-3\b/ }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /host-3\b/ }));
    expect(body()).toEqual({ agents: [uuid(52)] });
  });

  it("a <script> or onerror hostname renders as text (plant CHK-M11-375)", async () => {
    answer(() =>
      json(200, {
        items: [
          agentItem(1, { hostname: SCRIPT }),
          agentItem(2, { hostname: IMG }),
        ],
        next_cursor: null,
      }),
    );
    const { container } = render(<Harness start={agents([])} />);
    await settle();
    expect(
      screen.getByRole("checkbox", { name: new RegExp(escape(SCRIPT)) }),
    ).toBeTruthy();
    expect(container.textContent).toContain(SCRIPT);
    expect(container.textContent).toContain(IMG);
    expect(noInjectedMarkup(container)).toEqual({ scripts: 0, imgs: 0 });
  });

  it("a refused host list shows its problem", async () => {
    answer(() =>
      json(503, { type: "about:blank", title: "t", status: 503, detail: null }),
    );
    render(<Harness start={agents([])} />);
    await settle();
    expect(screen.getByRole("alert").textContent).toContain(
      "The manager is unavailable. Try again later.",
    );
  });
});

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ------------------------------------------------------------ TASK-258
// TASK-258 TEST: an unrecognised stored target is "unknown", never All hosts
// (reviewer-m11 nit 1 on TASK-256/249, fails open). Expected values: #122 (b)
// (exactly the three forms; all is the value true only); the lead's ruling
// 2026-11-08 (an edit cannot widen a target it does not recognise).

describe("TASK-258 fromTarget never widens an unrecognised target", () => {
  const unknown: Record<string, unknown>[] = [
    {},
    { all: "true" },
    { all: false },
    { all: 1 },
    { tags: "db" },
    { agents: [1, 2] },
    { agents: uuid(1) },
    { foo: 1 },
    { resolved_agents: [uuid(1)] },
  ];
  for (const t of unknown) {
    it(JSON.stringify(t) + " is unknown and cannot be sent", () => {
      const v = fromTarget(t);
      expect(v.kind).toBe("unknown");
      expect(toTarget(v)).toBe("Choose a target.");
    });
  }

  it("{all: true} still reads as All hosts", () => {
    expect(fromTarget({ all: true }).kind).toBe("all");
    expect(toTarget(fromTarget({ all: true }))).toEqual({ all: true });
  });

  it("the picker shows Unknown target with no form chosen; choosing one replaces it", () => {
    render(<Harness start={fromTarget({ foo: 1 })} />);
    expect(screen.getByText("Unknown target").tagName).toBe("STRONG");
    expect(
      screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).checked),
    ).toEqual([false, false, false]);
    expect(body()).toBe("Choose a target.");
    fireEvent.click(screen.getByRole("radio", { name: "All hosts" }));
    expect(body()).toEqual({ all: true });
    expect(screen.queryByText("Unknown target")).toBeNull();
  });
});
