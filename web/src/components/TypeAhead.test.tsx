// TASK-125 TEST (TP-M5-18): CHK-M5-270 to CHK-M5-273.
// Expected values: REQ-130 per the agreed #32 answer: from 3 characters, 300
// ms after the last change, one GET /api/v1/packages/search?q=<input>&
// group_by=package&limit=500; at most 10 distinct names in response order;
// a stale answer is ignored; choosing sets the exact name and clears q.
import {
  answer,
  bsu,
  callsTo,
  deferred,
  json,
  loginResponse,
  queryOf,
  resetHttp,
  type Call,
  type Deferred,
} from "../test/harness";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, setSession } from "../app/session";
import { PackageSearch } from "../screens/PackageSearch";
import { TypeAhead } from "./TypeAhead";

const SEARCH = "/api/v1/packages/search";
const LABEL = "Name contains";

function groups(names: string[]) {
  return names.map((name, i) => ({
    name,
    version: "1." + String(i),
    architecture: "amd64",
    host_count: 1,
  }));
}

function Harness({ onChoose }: { onChoose: (n: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <TypeAhead
      label={LABEL}
      value={value}
      onChange={setValue}
      onChoose={onChoose}
    />
  );
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("viewer", true, bsu("V")));
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  vi.useRealTimers();
  clearSession();
});

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function typeIn(value: string): void {
  fireEvent.change(screen.getByLabelText(LABEL), { target: { value } });
}

function suggestions(): string[] {
  const list = screen.queryByRole("list", { name: "Suggestions" });
  return list === null
    ? []
    : within(list)
        .getAllByRole("button")
        .map((b) => b.textContent ?? "");
}

describe("CHK-M5-270 debounce and request", () => {
  it("2 characters send nothing, even after a long wait", async () => {
    answer(() => json(200, { items: groups(["ab"]), next_cursor: null }));
    render(<Harness onChoose={vi.fn()} />);
    typeIn("a");
    typeIn("ab");
    await advance(2000);
    expect(callsTo(SEARCH)).toHaveLength(0);
  });

  it("2 code points of astral text send nothing; 3 send", async () => {
    answer(() => json(200, { items: [], next_cursor: null }));
    render(<Harness onChoose={vi.fn()} />);
    typeIn("\u{1F600}\u{1F600}");
    await advance(400);
    expect(callsTo(SEARCH)).toHaveLength(0);
    typeIn("\u{1F600}\u{1F600}\u{1F600}");
    await advance(400);
    expect(callsTo(SEARCH)).toHaveLength(1);
  });

  it("5 characters typed quickly send one request, 300 ms after the last change, exactly q, group_by=package, limit=500", async () => {
    answer(() => json(200, { items: [], next_cursor: null }));
    render(<Harness onChoose={vi.fn()} />);
    for (const v of ["o", "op", "ope", "open", "opens"]) {
      typeIn(v);
      await advance(100);
    }
    expect(callsTo(SEARCH)).toHaveLength(0);
    await advance(199);
    expect(callsTo(SEARCH)).toHaveLength(0);
    await advance(1);
    const sent = callsTo(SEARCH);
    expect(sent).toHaveLength(1);
    expect(queryOf(sent[0] as Call)).toEqual({
      q: "opens",
      group_by: "package",
      limit: "500",
    });
    expect(sent[0]?.url).toBe(SEARCH + "?q=opens&group_by=package&limit=500");
    expect(sent[0]?.authorization).toBe("Bearer " + bsu("V"));
    await advance(5000);
    expect(callsTo(SEARCH)).toHaveLength(1);
  });

  it("going back under 3 characters clears the suggestions", async () => {
    answer(() => json(200, { items: groups(["openssl"]), next_cursor: null }));
    render(<Harness onChoose={vi.fn()} />);
    typeIn("ope");
    await advance(300);
    expect(suggestions()).toEqual(["openssl"]);
    typeIn("op");
    await advance(0);
    expect(suggestions()).toEqual([]);
  });
});

describe("CHK-M5-271 at most 10 distinct names in response order", () => {
  it("14 groups over 12 names give the first 10 distinct names", async () => {
    const names = [
      "zlib1g",
      "zlib1g",
      "apt",
      "bash",
      "bash",
      "curl",
      "dash",
      "e2fsprogs",
      "findutils",
      "gzip",
      "hostname",
      "init",
      "jq",
      "kmod",
    ];
    answer(() => json(200, { items: groups(names), next_cursor: "more" }));
    render(<Harness onChoose={vi.fn()} />);
    typeIn("lib");
    await advance(300);
    expect(suggestions()).toEqual([
      "zlib1g",
      "apt",
      "bash",
      "curl",
      "dash",
      "e2fsprogs",
      "findutils",
      "gzip",
      "hostname",
      "init",
    ]);
  });

  it("a refusal shows no suggestions and no error", async () => {
    answer(() =>
      json(400, { type: "invalid_request", status: 400, detail: "x" }),
    );
    render(<Harness onChoose={vi.fn()} />);
    typeIn("abc");
    await advance(300);
    expect(suggestions()).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("hostile names render as text", async () => {
    const hostile = "<img src=x onerror=alert(1)>";
    answer(() => json(200, { items: groups([hostile]), next_cursor: null }));
    const { container } = render(<Harness onChoose={vi.fn()} />);
    typeIn("img");
    await advance(300);
    expect(suggestions()).toEqual([hostile]);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });
});

describe("CHK-M5-272 a stale answer is ignored", () => {
  it("a slower earlier response arriving after a later one changes nothing", async () => {
    const pending: Deferred[] = [];
    answer(() => {
      const d = deferred();
      pending.push(d);
      return d.promise;
    });
    render(<Harness onChoose={vi.fn()} />);
    typeIn("ssl");
    await advance(300);
    typeIn("sslx");
    await advance(300);
    expect(callsTo(SEARCH).map((c) => c.query.get("q"))).toEqual([
      "ssl",
      "sslx",
    ]);
    await act(async () => {
      pending[1]?.resolve(
        json(200, { items: groups(["new-answer"]), next_cursor: null }),
      );
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(suggestions()).toEqual(["new-answer"]);
    await act(async () => {
      pending[0]?.resolve(
        json(200, { items: groups(["old-answer"]), next_cursor: null }),
      );
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(suggestions()).toEqual(["new-answer"]);
  });
});

describe("CHK-M5-273 choosing a suggestion", () => {
  it("calls onChoose with the name and closes the list", async () => {
    answer(() =>
      json(200, { items: groups(["openssl", "openssh"]), next_cursor: null }),
    );
    const onChoose = vi.fn();
    render(<Harness onChoose={onChoose} />);
    typeIn("ope");
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: "openssh" }));
    expect(onChoose).toHaveBeenCalledWith("openssh");
    expect(suggestions()).toEqual([]);
  });

  it("on the search screen it sets Exact name and clears q; Search then sends name only", async () => {
    answer((call) =>
      call.query.get("limit") === "500"
        ? json(200, {
            items: groups(["openssl", "libssl3"]),
            next_cursor: null,
          })
        : json(200, { items: [], next_cursor: null }),
    );
    render(<PackageSearch navigate={vi.fn()} />);
    const q = screen.getByLabelText(
      "Name contains (q, 3 or more characters)",
    ) as HTMLInputElement;
    fireEvent.change(q, { target: { value: "ssl" } });
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: "libssl3" }));
    expect(q.value).toBe("");
    expect(
      (screen.getByLabelText("Exact name") as HTMLInputElement).value,
    ).toBe("libssl3");
    fireEvent.submit(screen.getByRole("form", { name: "Search packages" }));
    await advance(0);
    const searches = callsTo(SEARCH).filter(
      (c) => c.query.get("limit") === "50",
    );
    expect(searches.map(queryOf)).toEqual([
      { name: "libssl3", group_by: "package", limit: "50" },
    ]);
  });
});
