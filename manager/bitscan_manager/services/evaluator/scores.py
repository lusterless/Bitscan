"""Host compliance scores of one scan (TS §4.5 L602, §4.4 L579, L583; #120).

Scores are computed when read and never stored (no column exists), so a late
result or a re-evaluation changes the next read at once. The counts come from
the effective verdicts (#119) in `repositories/results.py`; the ratio from
`score.host_score()`. One SELECT, nothing written, nothing logged.
"""

from dataclasses import dataclass
from uuid import UUID

from bitscan_manager.repositories import results
from bitscan_manager.runtime import Database
from bitscan_manager.services.evaluator.score import HostScore, host_score


@dataclass(frozen=True, slots=True)
class AgentScore:
    """One host's score in one scan: its original job and its retry together."""

    agent_id: UUID
    host: HostScore


def scan_host_scores(db: Database, scan_id: UUID) -> list[AgentScore]:
    """One entry per agent with an original compliance job in the scan,
    ordered by agent_id; [] for an unknown scan."""
    with db.transaction() as tx:
        counts = results.host_counts(tx.conn, scan_id)
    return [
        AgentScore(c.agent_id, host_score(c.passed, c.failed, c.errors, c.not_run))
        for c in counts
    ]
