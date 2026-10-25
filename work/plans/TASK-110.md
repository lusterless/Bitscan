# TASK-110 plan: package search filter type, query parsing and repository

Covers TASK-109 (`parse_search`, `bm/services/packages/query.py`) and TASK-110 (`bm/repositories/packages.py`), and fixes the types TASK-113 and TASK-114 consume. REQs: REQ-113, REQ-114, REQ-115. Owner: impl-manager. One review round (speed rule 6); the reviewer is asked for a second look at the SQL (owner notes). Tests: TP-M5-02, TP-M5-03; mutation rows CHK-M5-320 to -327, -329, -330.

**Blocked on #83** (semantics), **#87** (stored versions the `debversion` comparator refuses), **#88** (empty values and U+0000). Each recommended answer is what this plan builds; a different answer changes only the named constant or check.

In this file `bm/` is `manager/bitscan_manager/`; L… are lines of `docs/spec/Technical_Specification.md`.

## Spec quotes

- TS §7 L1194: "Users can find any package across the fleet in under 1 s for 10,000 hosts × 2,000 packages (20 M `agent_package` rows), using a trigram index on names and normalised package rows." (No gate in M5: testing.md open question; timing deferred until after M6.)
- TS §7.1 L1200–L1210: the eleven parameters (`q` "Substring / fuzzy match on package name (`pg_trgm`); at least 3 characters"; `name` "Exact name"; `version` "Exact version"; `version_op` `lt`, `le`, `eq`, `ge`, `gt` "Compare with `version` using Debian ordering"; `arch`; `status` "`installed` (default) or `any`"; `os` "Filter by `os_info`"; `tag`; `host` "Hostname substring"; `agent_id`; `group_by` "`package` or `host` … at most 500 groups per page").
- L1212: "Filters combine with AND. `q` and `name` cannot be used together, and `version_op` needs `version`; either mistake returns 400."
- L1213–L1215: the three row shapes and `{ "items": [ … ], "next_cursor": "…" | null }`.
- TS §7.2 L1219: "`package.version` stays text and comparisons cast it (`version::debversion`), using the index `ix_package_name_debver`."
- TS §5.2 L795–L815: `package (package_id, name VARCHAR(255), version VARCHAR(255), architecture VARCHAR(16), source_name)`, UNIQUE (name, version, architecture); `ix_package_name_trgm`, `ix_package_name_debver`; `agent_package (agent_id, package_id, status VARCHAR(64), …)`, PRIMARY KEY (agent_id, package_id); `ix_agent_package_pkg`. L732 `ix_agent_hostname_trgm`. No index is added in M5.

## Layering

`api → services → repositories`, and no repository imports a service (the M3 tree has none). So the **filter type lives in the repository** and the service wraps it:
- `bm/repositories/packages.py` (TASK-110) defines `VersionOp`, `SearchFilter`, the row types and `PackageSearchRepo`.
- `bm/services/packages/query.py` (TASK-109) imports `SearchFilter` and `VersionOp` from it and defines `GroupBy`, `SearchQuery`, `InvalidSearch` and `parse_search`.

TASK-109 is therefore written against this file's signatures in parallel with TASK-110 and TESTed after TASK-110 IMPL; TASK-110's tests build `SearchFilter` values directly and need nothing from TASK-109.

## Interfaces (fixed for TASK-109, 110, 113, 114)

```python
# bm/repositories/packages.py (TASK-110)
class VersionOp(StrEnum):
    LT = "lt"; LE = "le"; EQ = "eq"; GE = "ge"; GT = "gt"

# #83 (f): the literal reading until the owner answers; the only place it is set.
INSTALLED_STATUSES: Final[tuple[str, ...]] = ("install ok installed",)

@dataclass(frozen=True)
class SearchFilter:
    q: str | None = None
    name: str | None = None
    version: str | None = None
    version_op: VersionOp | None = None        # only with version (parse_search enforces)
    arch: str | None = None
    statuses: tuple[str, ...] | None = INSTALLED_STATUSES   # None = status=any
    os_id: str | None = None
    os_version_id: str | None = None           # only with os_id
    tag: str | None = None
    host: str | None = None
    agent_id: UUID | None = None

@dataclass(frozen=True)
class PackageRow:            # one item without group_by
    package_id: int          # cursor anchor only; never in a response
    name: str
    version: str
    architecture: str
    status: str
    agent_id: UUID
    hostname: str

@dataclass(frozen=True)
class PackageGroup:          # group_by=package
    package_id: int          # cursor anchor only
    name: str
    version: str
    architecture: str
    host_count: int

@dataclass(frozen=True)
class HostGroup:             # group_by=host
    agent_id: UUID
    hostname: str
    package_count: int

RowAnchor = tuple[int, UUID]          # (package_id, agent_id) of the last row

class AnchorGone(Exception):
    """The package or agent a cursor points at no longer exists."""

class PackageSearchRepo:
    def __init__(self, conn: psycopg.Connection[Any]) -> None: ...
    def rows(self, f: SearchFilter, limit: int, after: RowAnchor | None) -> list[PackageRow]: ...
    def package_groups(self, f: SearchFilter, limit: int, after: int | None) -> list[PackageGroup]: ...
    def host_groups(self, f: SearchFilter, limit: int, after: UUID | None) -> list[HostGroup]: ...
    # TASK-114 adds read_only_snapshot(), count_capped() and stream() (work/plans/TASK-113.md).
```

```python
# bm/services/packages/query.py (TASK-109)
class GroupBy(StrEnum):
    PACKAGE = "package"; HOST = "host"

MAX_LEN: Final[Mapping[str, int]] = {      # #83 (h), characters (len), as the columns count
    "q": 255, "name": 255, "version": 255, "host": 255, "arch": 16, "tag": 64, "os": 49,
}
Q_MIN: Final = 3

@dataclass(frozen=True)
class SearchQuery:
    filter: SearchFilter
    group_by: GroupBy | None
    def shape(self) -> str: ...            # "rows" | "package" | "host"
    def cursor_scope(self) -> str: ...     # "packages:<shape>:<filter hash>"

class InvalidSearch(Exception):
    def __init__(self, params: tuple[str, ...]) -> None: ...   # parameter names only, sorted

def parse_search(params: Mapping[str, str | None]) -> SearchQuery: ...
```

`params` holds the raw query values of the eleven TS §7.1 names (absent = `None`); `limit` and `cursor` are not part of it (they stay with `api/pagination.py`). The route (TASK-113) maps `InvalidSearch(params)` to `Problem(400, "invalid_request", "Invalid request: " + ", ".join(f"query.{p}" for p in params))`, the same form `api/problems.py` uses for validation errors, so no value is ever echoed (REQ-038 (2)).

## `parse_search` rules (TASK-109; one REQ-113 (1) case each)

Checked in this order; the first failure raises:
1. **Text values** (`q`, `name`, `version`, `arch`, `os`, `tag`, `host`): an empty string or one holding U+0000 is refused (#88: PostgreSQL text cannot hold U+0000, so it would otherwise be a 500); longer than `MAX_LEN` is refused; exactly `MAX_LEN` is accepted.
2. **Enums:** `version_op` in `VersionOp`, `status` in `installed` or `any` (absent = `installed`), `group_by` in `GroupBy` (absent = rows). Anything else is refused, naming that parameter (`ne`, `removed`, `name`, upper case `LT` all refused: values are exact).
3. **`q`:** fewer than 3 characters refused. `q` with `name`: refused as `("name", "q")`.
4. **`version_op` without `version`:** refused as `("version", "version_op")`.
5. **`version`** must be a Debian version (#83 (g)), checked with dpkg's own syntax rules, so every version dpkg can install passes:
   - an epoch is present if the value has a `:`; the part before the first `:` must be 1 to 10 ASCII digits with a value of at most 2,147,483,647;
   - a revision is present if the rest has a `-`; the part after the last `-` must be non-empty and use only ASCII letters, digits and `.+~`;
   - the upstream part (between them) must be non-empty, start with an ASCII digit, and use only ASCII letters, digits and `.+~-`, plus `:` when there is an epoch;
   - no whitespace anywhere.
   Plain ASCII character-set checks, no regular expression (`str.isalnum()` and `str.isdigit()` accept non-ASCII characters, so they are not used). The check applies to `version` alone too (exact match), as REQ-113 says. TP-M5-02 also feeds every version of `manager/tests/fixtures/debversion_pairs.tsv` (the M1 dpkg corpus) and expects each accepted.
6. **`os`** (#83 (c)): split at the first `:`. `ubuntu` gives `os_id="ubuntu"`, any version; `ubuntu:24.04` gives both. Refused: an empty `os_id` (`:24.04`), an empty version (`ubuntu:`), a second `:`, an `os_id` over 32 or a version over 16 characters (the `os_info` columns, L782–L783). Exact match, case as given.
7. **`agent_id`:** a hyphenated UUID (36 characters, hyphens at positions 8, 13, 18 and 23, hex digits elsewhere, either case), then `uuid.UUID`. Braces, `urn:uuid:` and the 32-digit form are refused (M3 ruling: hyphenated UUIDs).
8. `status=any` gives `statuses=None`; `installed` gives `INSTALLED_STATUSES`.

Unknown parameters are ignored, as on every route. Normalised result (TASK-109 acceptance): `q`, `name`, `version`, `arch`, `tag`, `host` unchanged (matching is case-insensitive in SQL for `q` and `host` only, #83 (a), (d)); `os` split; `statuses` per #83 (f).

**`cursor_scope()`:** `f"packages:{shape}:{digest}"`, where `digest` is the first 32 hex characters of SHA-256 over `json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` of every `SearchFilter` field (enum values as strings, `agent_id` as its lowercase string, `statuses` as a list or null). `api/pagination.decode_cursor` refuses a cursor whose scope differs, so a cursor reused with any other filter or `group_by` answers 400 `query.cursor` (#83 (b), CHK-M5-328). The scope is short and fixed-length, so cursors stay far below the `page_params` 512-character limit (see "Cursor keys").

## SQL (TASK-110)

All SQL is `psycopg.sql.SQL` constants in this module, joined with `sql.SQL(" AND ").join(...)`; every value is a named bound parameter (`%(name)s`). Which fragments are used depends on which filters are set; no fragment text is built from input (ruff S608, CHK REQ-115 (3)). **Every literal `%` in a fragment is written `%%`**, because the statements take parameters (the trigram operator below).

Base:
```sql
FROM agent_package ap
JOIN package p ON p.package_id = ap.package_id
JOIN agent a ON a.agent_id = ap.agent_id
WHERE a.status <> 'decommissioned'            -- #83 (e), always present (CHK-M5-329)
```

Filter fragments (each present only when its field is set):

| Field | Fragment | Notes |
| --- | --- | --- |
| `q` | `(p.name ILIKE %(q_like)s ESCAPE '\' OR p.name %% %(q)s)` | #83 (a): case-insensitive substring or `pg_trgm` similarity at the default threshold; both use `ix_package_name_trgm`. `q_like = "%" + like_escape(q) + "%"` |
| `name` | `p.name = %(name)s` | exact |
| `version`, no op | `p.version = %(version)s` | exact text (TS §7.1 "Exact version") |
| `version` with op | one of five constants, for example `p.version::debversion < CAST(%(version)s AS debversion)` | the operator comes from a fixed `Mapping[VersionOp, sql.Composable]` of five whole fragments (`<`, `<=`, `=`, `>=`, `>`); never a text comparison (CHK-M5-320). `eq` is Debian equality, so `1.0` and `1.0-0` both match `eq 1.0` |
| `arch` | `p.architecture = %(arch)s` | exact |
| `statuses` | `ap.status = ANY(%(statuses)s)` | a list parameter; absent when `status=any` |
| `os_id` only | `EXISTS (SELECT 1 FROM os_info o WHERE o.agent_id = a.agent_id AND o.os_id = %(os_id)s)` | |
| `os_id` and version | the same with `AND o.os_version_id = %(os_version_id)s` | a second constant, not an optional clause |
| `tag` | `EXISTS (SELECT 1 FROM agent_tag t WHERE t.agent_id = a.agent_id AND t.tag = %(tag)s)` | exact |
| `host` | `a.hostname ILIKE %(host_like)s ESCAPE '\'` | #83 (d): case-insensitive substring; `ix_agent_hostname_trgm` |
| `agent_id` | `ap.agent_id = %(agent_id)s` | an unknown id gives an empty result, not 404 |

`like_escape(s)` replaces `\` with `\\`, then `%` with `\%` and `_` with `\_` (backslash first), so `q=%_\'";--` and `host=_` match those characters literally (CHK-M5-325, -326). In the Python source the `ESCAPE` clause is written `"ESCAPE '\\'"`; with `standard_conforming_strings` on (the PostgreSQL 16 default) the SQL literal is one backslash.

Shapes, orders (#83 (b)) and keysets:

| Shape | SELECT | GROUP BY | ORDER BY (= keyset tuple) |
| --- | --- | --- | --- |
| rows | `p.package_id, p.name, p.version, p.architecture, ap.status, a.agent_id, a.hostname` | none | `p.name, p.version::debversion, p.version, p.architecture, a.hostname, a.agent_id` |
| package | `p.package_id, p.name, p.version, p.architecture, count(*) AS host_count` | `p.package_id` | `p.name, p.version::debversion, p.version, p.architecture` |
| host | `a.agent_id, a.hostname, count(*) AS package_count` | `a.agent_id` | `a.hostname, a.agent_id` |

- `GROUP BY` the primary key makes the other columns of that table selectable (PostgreSQL functional dependency), and one `package_id` is one (name, version, architecture).
- `host_count` is `count(*)`: (agent_id, package_id) is the primary key of `agent_package`, so it counts distinct hosts holding that package under the same filters (REQ-114 (4)). `package_count` is the number of matching rows of that host.
- The text `p.version` after `p.version::debversion` makes the order total when two versions are equal in Debian order but differ as text (`1.0`, `1.0-0`; CHK-M5-327). For rows, `a.agent_id` ends the tuple, so the order is total.
- Keyset: `AND (<order tuple>) > (<anchor values>)` with each anchor value a bound parameter cast to its type (`CAST(%(k_version)s AS debversion)` for the Debian position, `CAST(%(k_version)s AS text)` for the text position, `CAST(%(k_agent)s AS uuid)`). The comparison is in the WHERE clause also for the grouped shapes, because the group keys are the order columns.
- `LIMIT %(limit)s`; the route asks for `limit + 1` rows to learn whether there is a next page (M3 `page_of` convention).

## Cursor keys (why ids, not sort values)

`api/pagination.page_params` caps `cursor` at 512 characters, and `encode_cursor` writes `json.dumps(..., ensure_ascii=True)`. A cursor holding the sort values (a 255-character name, a 255-character version, a hostname) would exceed 512 for long or non-ASCII values, which a hostile agent can send (the M3 decoder allows any storable text up to the column length), and the next page would then answer 400. So the cursor holds ids, and the repository looks the sort values up:

| Shape | Cursor key (list) | Lookup before the page query |
| --- | --- | --- |
| rows | `[package_id, "<agent_id>"]` | `SELECT p.name, p.version, p.architecture, a.hostname FROM package p, agent a WHERE p.package_id = %s AND a.agent_id = %s` |
| package | `[package_id]` | `SELECT name, version, architecture FROM package WHERE package_id = %s` |
| host | `["<agent_id>"]` | `SELECT hostname FROM agent WHERE agent_id = %s` |

No row found raises `AnchorGone`; the route answers 400 `invalid_request` `query.cursor` (start the search again). A hostname changed between pages (an approved re-enrolment) shifts that host's place in the order; any keyset paging has this under concurrent change. The same 512-character risk in the M3 cursors is #89 (not fixed in M5).

## Edge cases

- **Stored versions `debversion` cannot compare (#87).** The M3 decoder stores any storable version text up to 255 characters. If the extension's comparison raises on a malformed version (dpkg's `parseversion` errors), every query that orders or compares versions of that package name answers 500. TP-M5-03 probes it with a malformed version inserted as `bitscan_app` (`1.0 beta`, `a1`, `1:`, `1.0-`) next to a valid one with the same name. Until #87 is answered, TASK-110 adds no special handling: no `try` around the query, no per-row cast guard (a guard would hide a real database error).
- Parameters with only spaces are accepted as given (an `ILIKE` on spaces is valid); `q` of three spaces is three characters.
- `q` shorter than 3 after the `%`/`_` escape is still judged on the raw value (`q=%%%` is 3 characters).
- Upper-case `agent_id` input is accepted; output UUIDs are lowercase (M3 ruling).
- `limit` 1 to 500 and `cursor` stay with `page_params` (FastAPI validation 400 naming `query.limit`).
- `status=any` includes `deinstall ok config-files` (REQ-114 (3)); `hold ok installed` is excluded until #83 (f) is answered (one constant).
- An `agent_id` filter for a `decommissioned` host returns nothing (#83 (e)).
- Read-only: the repository issues SELECT statements only; nothing is written (REQ-115 (5)).

## Tests the plan expects (tester owns them)

- TP-M5-02: one case per rule above, at-limit and over-limit for every `MAX_LEN` entry, U+0000 and empty values, the dpkg corpus versions accepted, `cursor_scope()` equal for equal queries and different for any one changed field or `group_by`.
- TP-M5-03: the fixture fleet (`manager/tests/package_fleet.py`), as `bitscan_app`; each filter alone, every pair, one five-filter combination, against sets computed in Python; the five operators over at least 50 pairs of the M1 corpus; paging N + 1 with `limit=N` for all three shapes, including `1.0` and `1.0-0`; literal wildcards; `AnchorGone` after the anchor row's package is removed; the #87 probe, reported as a finding, not a failure of TASK-110.
