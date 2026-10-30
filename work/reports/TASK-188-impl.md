# TASK-188 IMPL: scan targets (pure)

Implementer: impl-manager-m9. REQ-208. Risk high. Spec: TS §4.4 L555, §5.2 L850, L865, §6.4 L1151. Answers applied: #122 (b)–(d), #68; decisions 2026-10-30 "M9 early rulings" (1) and (3).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/jobs/targets.py` (new, 110 lines) | `Target`, `parse_target()`, `stored_target()`, `InvalidTarget`, limits |

No file outside the task's list was changed.

## Interface (as plan TASK-198 §2)

```python
TargetKind = Literal["agents", "tags", "all"]
AGENTS_MAX: Final = 10_000
TAGS_MAX: Final = 32; MAX_TAG_LENGTH: Final = 64; TAG_CHARACTERS: Final = frozenset(A–Z a–z 0–9 . _ : -)
class InvalidTarget(ValueError):     # message "Invalid request: <field>", .field in
    field: str                       #   {"target", "target.agents", "target.tags", "target.all"}
@dataclass(frozen=True, slots=True)
class Target: kind: TargetKind; agents: tuple[UUID, ...] = (); tags: tuple[str, ...] = ()
def parse_target(value: object) -> Target
def stored_target(target: Target, resolved: Sequence[UUID]) -> dict[str, Any]
```

## Behaviour

- `parse_target`: `type(value) is dict` with exactly one key from `agents`, `tags`, `all`, else `InvalidTarget("target")`.
  - `all`: the value must be `True` itself (`{"all": 1}`, `false`, `"true"` refused).
  - `agents`: `type is list`, 1–10,000 items; each a 36-character string with hyphens exactly at 8, 13, 18, 23 and hex digits everywhere else, either case. Distinct **by UUID value**, so a case variant of the same id is a duplicate and refused (ruling (3)). Kept in input order as `UUID`s.
  - `tags`: `type is list`, 1–32 items; each a `str` of 1–64 characters from `TAG_CHARACTERS`; distinct (case-sensitive, as M3's tags).
- The UUID check does not rely on `uuid.UUID()` alone. It also accepts braces, `urn:` and 32-hex forms, and its `int(..., 16)` accepts `_`, so `1234567_-1234-...` would parse; each character is checked.
- `stored_target`: `{"agents": [lowercase ids in request order]}`, `{"tags": [...]}` or `{"all": True}`, plus `"resolved_agents"`: distinct, lowercase, sorted strings (lowercase hex text order equals UUID order).
- The messages are fixed words. No input value is ever in an exception.

## For the tester

- **Pin the copied tag constants:** `targets.TAGS_MAX == admin.MAX_TAGS`, `targets.MAX_TAG_LENGTH == admin.MAX_TAG_LENGTH` and `targets.TAG_CHARACTERS == admin.TAG_CHARACTERS` (`bitscan_manager.services.agents.admin`). They are copies by ruling (1), because importing `admin.py` pulls `repositories.agents` and psycopg.
- Imports: stdlib only.
- `InvalidTarget.field` is there for the route's problem detail (TASK-205). The message is always `Invalid request: <field>`.

## Plants

No mutation row names TASK-188 directly. Useful plants for REQ-208 (2): drop the hex-character loop (the `_` form is then accepted); compare agent ids as strings (a case variant is then accepted); `isinstance(inner, bool)` instead of `is True`.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass.
