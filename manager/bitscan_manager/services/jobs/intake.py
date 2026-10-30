"""Result intake for compliance jobs (TS §6.1 L1065, L1071, §4.4 L568–L570,
L575, L578, L581, §4.5 L587, L603, §3.3 L222, §8.4 L1288; REQ-214 to
REQ-217, REQ-226; open questions #12, #116 (d), #121, #124, #127 (a), (c),
#129 (c); plan work/plans/TASK-199.md, design note D2).

One batch is one transaction: the root job (COALESCE(retry_of, job_id)) and
then the posted job are locked FOR UPDATE, acceptance is decided on the rows
read under that lock, the plan's rows are inserted in one statement, and the
job's progress columns move. First result wins across the original and its
retry because both lock the same root. A refusal stores nothing and changes
nothing; the caller writes the refusal entry in its own transaction.

Nothing here logs, raises or audits stdout, stderr, a command or an expected
value; the eval_spec refusal is logged by exception type only (#124 (h)).
"""

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Final, Literal, Protocol
from uuid import UUID

from bitscan_manager.repositories import job_intake
from bitscan_manager.repositories.settings import SettingsRepo
from bitscan_manager.runtime import Database, Tx
from bitscan_manager.services.audit.metrics import PLUGIN_RESULTS
from bitscan_manager.services.evaluator.eval_spec import EvalSpecError, parse_eval_spec
from bitscan_manager.services.jobs import states
from bitscan_manager.services.jobs.intake_plan import IntakeItem, PluginNotInJob, plan
from bitscan_manager.services.settings.store import read_settings

log = logging.getLogger("bitscan_manager.jobs")

_LABELS: Final = {0: "PASS", 1: "FAIL", 2: "ERROR"}  # scan_result.eval_code
_ENDED: Final = frozenset({"completed", "partial", "failed"})  # #127 (c)


class IntakeBatch(Protocol):  # api.agent.schemas.ResultsRequest
    @property
    def results(self) -> Sequence[IntakeItem]: ...
    @property
    def final(self) -> bool: ...


@dataclass(frozen=True)
class Accepted:
    accepted: int  # rows inserted
    duplicates: int  # items the unit or an earlier item of the batch already had


@dataclass(frozen=True)
class Refused:
    reason: Literal["job_not_acceptable", "eval_spec_invalid"]
    own_cancelled: bool  # the agent's own cancelled job: not a flood (#124 (f))


class _Refusal(Exception):
    """Leaves the transaction, so it rolls back with nothing written."""

    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


def _not_acceptable(own_cancelled: bool = False) -> _Refusal:
    return _Refusal(Refused("job_not_acceptable", own_cancelled))


def _count_on_commit(tx: Tx, codes: Sequence[int]) -> None:
    """REQ-226: the stored rows by verdict, added only after the commit."""
    for label, n in Counter(_LABELS[c] for c in codes).items():
        tx.on_commit(partial(PLUGIN_RESULTS.labels(result=label).inc, n))


def _intake(
    tx: Tx, agent_id: UUID, job_id: UUID, batch: IntakeBatch, now: datetime
) -> Accepted:
    conn = tx.conn
    job = job_intake.lock_unit(conn, job_id)
    if job is None or job.agent_id != agent_id:
        raise _not_acceptable()
    if not states.accepts_results(job.kind, job.state, job.dispatched_at, now):
        own = job.kind == "compliance" and job.state == "cancelled"
        raise _not_acceptable(own)
    try:
        spec = parse_eval_spec(job.eval_spec)
    except EvalSpecError as exc:
        log.warning(
            "result batch refused: eval_spec unreadable (%s)", type(exc).__name__
        )
        raise _Refusal(Refused("eval_spec_invalid", False)) from None
    items = job.payload["plugins"]
    commands = {UUID(p["plugin_uuid"]): str(p["execute"]) for p in items}
    unit = [(job.job_id, job.created_at)]
    other = job_intake.sibling(conn, job)
    if other is not None:
        unit.append(other)
    existing = job_intake.result_uuids(conn, unit)
    try:
        planned = plan(spec, commands, existing, batch.results)
    except PluginNotInJob:
        raise _not_acceptable() from None
    stored = job_intake.insert_results(conn, job, planned.rows, now)
    have = existing | {r.plugin_uuid for r in planned.rows}
    outcome = states.after_batch(
        job.state,
        stored=stored,
        all_have_results=set(commands) <= have,
        final=batch.final,
    )
    state = job.state
    if outcome.start:
        parallel = read_settings(SettingsRepo(conn)).max_parallel_plugins
        timeouts = [int(p["timeout_s"]) for p in items]
        if job_intake.start(
            conn, job.job_id, now, states.deadline_at(now, timeouts, parallel)
        ):
            state = "running"
    if outcome.state != state:
        finished = now if outcome.state in _ENDED else None
        job_intake.set_state(conn, job.job_id, outcome.state, finished)
    _count_on_commit(tx, [r.eval_code for r in planned.rows])
    return Accepted(accepted=stored, duplicates=planned.duplicates)


def accept_results(
    db: Database, *, agent_id: UUID, job_id: UUID, batch: IntakeBatch, now: datetime
) -> Accepted | Refused:
    """One result batch for one job of this agent; `now` is the manager's
    clock (received_at and the start of the deadline, #124 (e))."""
    try:
        with db.transaction() as tx:
            return _intake(tx, agent_id, job_id, batch, now)
    except _Refusal as refusal:
        return refusal.refused
