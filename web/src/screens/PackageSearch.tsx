import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components, operations } from "../api/schema";
import { downloadCsv } from "../app/download";
import { toProblem, type ProblemInfo } from "../app/problems";
import { formatHash, type Route } from "../app/router";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { TypeAhead } from "../components/TypeAhead";

type SearchQuery = NonNullable<
  operations["search_packages_api_v1_packages_search_get"]["parameters"]["query"]
>;
type Row = components["schemas"]["PackageRowItem"];
type PackageGroup = components["schemas"]["PackageGroupItem"];
type HostGroup = components["schemas"]["HostGroupItem"];
type Item = Row | PackageGroup | HostGroup;
type VersionOp = NonNullable<SearchQuery["version_op"]>;

export interface PackageSearchProps {
  readonly navigate: (route: Route) => void;
}

interface Filters {
  q: string;
  name: string;
  version: string;
  version_op: VersionOp | "";
  arch: string;
  status: "installed" | "any";
  os: string;
  tag: string;
  host: string;
  agent_id: string;
  view: "package" | "host";
}
type TextKey =
  "q" | "name" | "version" | "arch" | "os" | "tag" | "host" | "agent_id";

const TEXT_FIELDS: readonly (readonly [TextKey, string])[] = [
  ["q", "Name contains (q, 3 or more characters)"],
  ["name", "Exact name"],
  ["version", "Version"],
  ["arch", "Architecture"],
  ["os", "OS (for example ubuntu:24.04)"],
  ["tag", "Host tag"],
  ["host", "Hostname contains"],
  ["agent_id", "Agent id"],
];
const OPS: readonly VersionOp[] = ["lt", "le", "eq", "ge", "gt"];
const EMPTY: Filters = {
  q: "",
  name: "",
  version: "",
  version_op: "",
  arch: "",
  status: "installed",
  os: "",
  tag: "",
  host: "",
  agent_id: "",
  view: "package",
};
const PAGE_SIZE = 50;

/** Only the filled fields (REQ-129 (1)); `installed` is the server default. */
function toQuery(f: Filters): SearchQuery {
  const query: SearchQuery = { group_by: f.view };
  for (const [key] of TEXT_FIELDS) {
    if (f[key] !== "") query[key] = f[key];
  }
  if (f.version !== "" && f.version_op !== "") query.version_op = f.version_op;
  if (f.status === "any") query.status = "any";
  return query;
}

const CARRIED: readonly ("os" | "tag" | "host" | "agent_id")[] = [
  "os",
  "tag",
  "host",
  "agent_id",
];

/**
 * #86 (a), lead ruling 2026-10-25: the version's host rows keep the search's
 * host filters, so the list matches the group's `host_count`.
 */
function drillQuery(search: SearchQuery | null, group: PackageGroup) {
  const query: SearchQuery = {
    name: group.name,
    version: group.version,
    arch: group.architecture,
  };
  if (search?.status !== undefined) query.status = search.status;
  for (const key of CARRIED) {
    const value = search?.[key];
    if (typeof value === "string") query[key] = value;
  }
  return query;
}

const isPackageGroup = (i: Item): i is PackageGroup => "host_count" in i;
const isHostGroup = (i: Item): i is HostGroup => "package_count" in i;
const isRow = (i: Item): i is Row => !isPackageGroup(i) && !isHostGroup(i);

/** #86 (b): `group_by=package` rows nested by name, in response order. */
function byName(groups: readonly PackageGroup[]): Map<string, PackageGroup[]> {
  const map = new Map<string, PackageGroup[]>();
  for (const group of groups) {
    const list = map.get(group.name);
    if (list === undefined) map.set(group.name, [group]);
    else list.push(group);
  }
  return map;
}

/** REQ-129. Every API value is rendered as a text node. */
export function PackageSearch({ navigate }: PackageSearchProps) {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [search, setSearch] = useState<SearchQuery | null>(null);
  const [query, setQuery] = useState<SearchQuery | null>(null);
  const pages = useCursorPages();
  const [items, setItems] = useState<readonly Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (query === null) return;
    let active = true;
    const paged = { ...query, limit: PAGE_SIZE };
    if (pages.cursor !== null) paged.cursor = pages.cursor;
    api
      .GET("/api/v1/packages/search", { params: { query: paged } })
      .then(({ data, error, response }) => {
        if (!active) return;
        setItems(data === undefined ? null : data.items);
        setNextCursor(data?.next_cursor ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setNote("The manager is unavailable. Try again later.");
      });
    return () => {
      active = false;
    };
  }, [query, pages.cursor]);

  function open(next: SearchQuery): void {
    setNote(null);
    setItems(null);
    setQuery(next);
    pages.reset();
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (filters.q !== "" && filters.name !== "") {
      setNote("Use either “Name contains” or “Exact name”, not both.");
      return;
    }
    const next = toQuery(filters);
    setSearch(next);
    open(next);
  }

  /** REQ-131: the query on screen, without `limit` or `cursor`. */
  async function exportCsv(current: SearchQuery): Promise<void> {
    setNote(null);
    setProblem(null);
    setExporting(true);
    try {
      setProblem(await downloadCsv(current));
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setExporting(false);
    }
  }

  function hostLink(agentId: string, hostname: string) {
    const route: Route = { name: "host", agentId };
    return (
      <a
        href={formatHash(route)}
        onClick={(event) => {
          event.preventDefault();
          navigate(route);
        }}
      >
        {hostname}
      </a>
    );
  }

  const drill = query !== null && query.group_by === undefined;
  const list = items ?? [];
  return (
    <main>
      <h1>Package search</h1>
      <form onSubmit={submit} aria-label="Search packages">
        {TEXT_FIELDS.map(([key, label]) =>
          key === "q" ? (
            <TypeAhead
              key={key}
              label={label}
              value={filters.q}
              onChange={(value) => {
                setFilters((f) => ({ ...f, q: value }));
              }}
              onChoose={(name) => {
                setFilters((f) => ({ ...f, name, q: "" }));
              }}
            />
          ) : (
            <label key={key}>
              {label}
              <input
                value={filters[key]}
                onChange={(event) => {
                  setFilters({ ...filters, [key]: event.target.value });
                }}
              />
            </label>
          ),
        )}
        <label>
          Version comparison
          <select
            value={filters.version_op}
            disabled={filters.version === ""}
            onChange={(event) => {
              const op = OPS.find((o) => o === event.target.value);
              setFilters({ ...filters, version_op: op ?? "" });
            }}
          >
            <option value="">exact version</option>
            {OPS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(event) => {
              setFilters({
                ...filters,
                status: event.target.value === "any" ? "any" : "installed",
              });
            }}
          >
            <option value="installed">installed</option>
            <option value="any">any</option>
          </select>
        </label>
        <label>
          View
          <select
            value={filters.view}
            onChange={(event) => {
              setFilters({
                ...filters,
                view: event.target.value === "host" ? "host" : "package",
              });
            }}
          >
            <option value="package">by package and version</option>
            <option value="host">by host</option>
          </select>
        </label>
        <button type="submit">Search</button>
      </form>
      {note !== null && <p role="alert">{note}</p>}
      <ProblemBanner problem={problem} />
      {query !== null && (
        <button
          type="button"
          disabled={exporting}
          onClick={() => {
            void exportCsv(query);
          }}
        >
          Export CSV
        </button>
      )}
      {drill && search !== null && (
        <button
          type="button"
          onClick={() => {
            open(search);
          }}
        >
          Back to results
        </button>
      )}
      {items !== null && list.length === 0 && <p>No packages found.</p>}
      {[...byName(list.filter(isPackageGroup))].map(([name, groups]) => (
        <section key={name} aria-label={name}>
          <h2>{name}</h2>
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Architecture</th>
                <th>Hosts</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group, index) => (
                <tr key={index}>
                  <td>
                    <button
                      type="button"
                      onClick={() => {
                        open(drillQuery(search, group));
                      }}
                    >
                      {group.version}
                    </button>
                  </td>
                  <td>{group.architecture}</td>
                  <td>{group.host_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {list.some(isHostGroup) && (
        <table aria-label="Hosts">
          <thead>
            <tr>
              <th>Host</th>
              <th>Matching packages</th>
            </tr>
          </thead>
          <tbody>
            {list.filter(isHostGroup).map((group, index) => (
              <tr key={index}>
                <td>{hostLink(group.agent_id, group.hostname)}</td>
                <td>{group.package_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.some(isRow) && (
        <table aria-label="Hosts with this version">
          <thead>
            <tr>
              <th>Host</th>
              <th>Name</th>
              <th>Version</th>
              <th>Architecture</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {list.filter(isRow).map((row, index) => (
              <tr key={index}>
                <td>{hostLink(row.agent_id, row.hostname)}</td>
                <td>{row.name}</td>
                <td>{row.version}</td>
                <td>{row.architecture}</td>
                <td>{row.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {query !== null && <Pager pages={pages} nextCursor={nextCursor} />}
    </main>
  );
}
