# TASK-189 IMPL: job and retry builder (pure)

Implementer: impl-manager-m9. REQ-209, REQ-210, REQ-212. Risk high (lead's second look, PD-39). Spec: TS §3.5 L248, §6.5 L1165–L1182, §4.4 L566, L577, §4.1 L530, §4.5 L587, L603. Answers applied: #117, #125 (a)–(c), (g), #126 (a), (b).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/build.py` (new, 172 lines) | `CatalogPlugin`, `UnstorableText`, `BuiltPlugins`, `pickup_text()`, `plugins_and_spec()`, `payload()`, `retry()` |

No file outside the task's list was changed. It reuses M8's `EvalSpec`, `build_eval_spec`, `parse_eval_spec` and `PluginSpec`, and M3's `PICKUP_WINDOW` (`services/scheduler/inventory.py`).

## Interface (as plan TASK-198 §2)

```python
PICKUP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
@dataclass(frozen=True, slots=True)
class CatalogPlugin: plugin_uuid: UUID; display_name: str; execute: str; timeout_s: int; operator: str; expected: str
class UnstorableText(ValueError)          # fixed message, no argument
@dataclass(frozen=True, slots=True)
class BuiltPlugins: plugins_json: list[dict[str, Any]]; eval_spec_json: dict[str, Any]; patterns: list[str]
def pickup_text(created_at: datetime) -> str
def plugins_and_spec(plugins: Sequence[CatalogPlugin], patterns: Sequence[str]) -> BuiltPlugins
def payload(job_id: UUID, agent_id: UUID, created_at: datetime, built: BuiltPlugins) -> dict[str, Any]
def retry(original_payload: Mapping[str, Any], original_eval_spec: Mapping[str, Any],
          missing: Collection[UUID], *, job_id: UUID, created_at: datetime,
          original_is_retry: bool) -> tuple[dict[str, Any], dict[str, Any]]
```

## Behaviour

- `plugins_and_spec`:
  - It first checks every `execute`, `display_name`, `expected` and redaction pattern for U+0000 and for a UTF-8 encode failure (a lone surrogate). One hit raises `UnstorableText` before anything is built.
  - It then builds `EvalSpec`, which enforces 1–5,000 distinct plugins, the 14 operators, name 1–400 and expected ≤ 4,000. An empty list raises `EvalSpecError`, a `ValueError`.
  - `plugins_json` is `[{plugin_uuid: str(uuid) (lowercase), execute, timeout_s}]` in the given order.
  - `eval_spec_json` is `build_eval_spec()` of the same plugins in the same order, with `name = display_name`.
  - `patterns` is a copy of the setting.
- `payload`: exactly `{job_id, agent_id, kind: "compliance", pickup_by, plugins, redaction_patterns}`, with copies of the lists. There is no `operator`, `expected` or `name` key at any depth.
- `pickup_text`: `(created_at + 24 h)` in UTC as `YYYY-MM-DDTHH:MM:SSZ`, truncated to the second like M3's `to_char`. A naive `created_at` raises `ValueError` rather than being read as local time.
- `retry`:
  - Raises `ValueError` when `original_is_retry` is set, when `missing` is empty, or when `missing` names a uuid not in the payload.
  - It keeps the original payload's items whose uuid is in `missing`, in the original order, copying only `plugin_uuid`, `execute` and `timeout_s`. It copies `agent_id` and `redaction_patterns` from the original. It sets a new `job_id` and `pickup_by = pickup_text(created_at)`. Nothing is read from the current catalog.
  - The eval_spec goes through `parse_eval_spec(original)`, keeps the entries for `missing` in order, then `build_eval_spec(EvalSpec(...))`. **Addition:** if the kept eval_spec uuids differ from the kept payload uuids (order included), it raises `ValueError`, so a retry never pairs commands with the wrong entries.

## For the tester

- REQ-209 (1): `payload()` is the reference for TASK-193's SQL-composed payload.
- `payload()` has no `UnstorableText` check of its own. It takes `BuiltPlugins` only from `plugins_and_spec`.
- `build.PICKUP_WINDOW` is an explicit re-export (`import PICKUP_WINDOW as PICKUP_WINDOW`) of M3's value, as the plan's interface lists it (revision after the first hand-off, so strict mypy accepts `build.PICKUP_WINDOW` in tests).
- Imports: `services.evaluator.{eval_spec, model}` (and through them `services.importer.model`/`values`), and `services.scheduler.inventory` (its package `__init__` imports only `inventory`). No db, repository, API, psycopg or logging.

## Plants

- CHK-M9-343: drop the `in wanted` filter.
- CHK-M9-344: a retry from the catalog. Not reachable here, because `retry()` takes no catalog input; the guard is its signature.
- CHK-M9-347: add `"operator": p.operator` to `plugins_json`.
- CHK-M9-348: build `PluginSpec`s from `reversed(plugins)`.
- CHK-M9-349: remove the `"\x00"` check.
- CHK-M9-350: `+ timedelta(hours=1)` in `pickup_text`, or a format without `Z`.
- CHK-M9-351: `patterns=[]`.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
