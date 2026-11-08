import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Pager, useCursorPages } from "./Pager";
import { ProblemBanner } from "./ProblemBanner";
import { StatusBadge } from "./StatusBadge";

type AgentPage = components["schemas"]["Page_AgentItem_"];

/** TS §4.4 L555: exactly one of the three forms. */
export type Target =
  | { readonly all: true }
  | { readonly tags: string[] }
  | { readonly agents: string[] };

/** What the picker edits; `tags` is the text as typed. */
export interface TargetValue {
  readonly kind: "all" | "tags" | "agents";
  readonly tags: string;
  readonly agents: readonly string[];
}

export const ALL_HOSTS: TargetValue = { kind: "all", tags: "", agents: [] };

const TAG_RULE =
  "Tags are 1 to 32 names of 1 to 64 characters: letters, digits and . _ : -";

/** The #68 tag rule: 1 to 64 characters from A-Z, a-z, 0-9 and `._:-`. */
function isTag(tag: string): boolean {
  if (tag.length < 1 || tag.length > 64) return false;
  for (const ch of tag) {
    const ok =
      (ch >= "a" && ch <= "z") ||
      (ch >= "A" && ch <= "Z") ||
      (ch >= "0" && ch <= "9") ||
      "._:-".includes(ch);
    if (!ok) return false;
  }
  return true;
}

/** Tags split on commas and white space, each once, in typed order. */
function splitTags(text: string): string[] {
  const tags: string[] = [];
  let word = "";
  for (const ch of text + ",") {
    if (ch === "," || ch.trim() === "") {
      if (word !== "" && !tags.includes(word)) tags.push(word);
      word = "";
    } else {
      word += ch;
    }
  }
  return tags;
}

/** The #122 (b) body, or a fixed text saying what to fix. */
export function toTarget(value: TargetValue): Target | string {
  if (value.kind === "all") return { all: true };
  if (value.kind === "tags") {
    const tags = splitTags(value.tags);
    return tags.length >= 1 && tags.length <= 32 && tags.every(isTag)
      ? { tags }
      : TAG_RULE;
  }
  if (value.agents.length < 1) return "Choose at least one host.";
  if (value.agents.length > 10_000) return "Choose at most 10,000 hosts.";
  return { agents: [...value.agents] };
}

type StoredTarget = Readonly<Record<string, unknown>>;

function strings(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const items: unknown[] = value;
  return items.every((v) => typeof v === "string") ? (items as string[]) : null;
}

/** A stored target (as requested) back into the picker. */
export function fromTarget(target: StoredTarget): TargetValue {
  const tags = strings(target.tags);
  const agents = strings(target.agents);
  if (tags !== null)
    return { ...ALL_HOSTS, kind: "tags", tags: tags.join(", ") };
  if (agents !== null) return { ...ALL_HOSTS, kind: "agents", agents };
  return ALL_HOSTS;
}

/** A stored target as text; the API's values stay text nodes. */
export function describeTarget(target: StoredTarget): string {
  const tags = strings(target.tags);
  const agents = strings(target.agents);
  if (tags !== null) return "Hosts with any of the tags: " + tags.join(", ");
  if (agents !== null) return String(agents.length) + " chosen hosts";
  return target.all === true ? "All hosts" : "Unknown target";
}

/** Hosts from `GET /agents`, a page at a time; the choice survives paging. */
function HostChooser({
  chosen,
  onChange,
}: {
  readonly chosen: readonly string[];
  readonly onChange: (agents: readonly string[]) => void;
}) {
  const pages = useCursorPages();
  const [page, setPage] = useState<AgentPage | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);

  useEffect(() => {
    let active = true;
    const cursor = pages.cursor === null ? {} : { cursor: pages.cursor };
    api
      .GET("/api/v1/agents", { params: { query: { limit: 50, ...cursor } } })
      .then(({ data, error, response }) => {
        if (!active) return;
        setPage(data ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [pages.cursor]);

  return (
    <fieldset className="filter-group" aria-label="Hosts">
      <legend>Hosts ({chosen.length} chosen)</legend>
      <ProblemBanner problem={problem} />
      {page?.items.map((host) => (
        <label key={host.agent_id} className="check">
          <input
            type="checkbox"
            checked={chosen.includes(host.agent_id)}
            onChange={(event) => {
              onChange(
                event.target.checked
                  ? [...chosen, host.agent_id]
                  : chosen.filter((id) => id !== host.agent_id),
              );
            }}
          />
          {host.hostname} <StatusBadge status={host.status} />
        </label>
      ))}
      <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
    </fieldset>
  );
}

/** #154 (a): all hosts, hosts with any of some tags, or chosen hosts. */
export function TargetPicker({
  value,
  onChange,
}: {
  readonly value: TargetValue;
  readonly onChange: (value: TargetValue) => void;
}) {
  const kinds = [
    ["all", "All hosts"],
    ["tags", "Hosts with any of these tags"],
    ["agents", "These hosts"],
  ] as const;
  return (
    <fieldset className="filter-group">
      <legend>Target</legend>
      {kinds.map(([kind, label]) => (
        <label key={kind} className="check">
          <input
            type="radio"
            name="target-kind"
            checked={value.kind === kind}
            onChange={() => {
              onChange({ ...value, kind });
            }}
          />
          {label}
        </label>
      ))}
      {value.kind === "tags" && (
        <label>
          Tags (separated by commas or spaces)
          <input
            value={value.tags}
            onChange={(event) => {
              onChange({ ...value, tags: event.target.value });
            }}
          />
        </label>
      )}
      {value.kind === "agents" && (
        <HostChooser
          chosen={value.agents}
          onChange={(agents) => {
            onChange({ ...value, agents });
          }}
        />
      )}
    </fieldset>
  );
}
