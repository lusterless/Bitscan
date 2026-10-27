"""G59 (TASK-174, TASK-175 verdict after TASK-154): the sample policies through
the import pipeline. CHK-M7-300, -301 (tests/m7/test-plan.md). Expected: every
``bits/samples/*.bit`` imports together into one fresh catalog with
``success``, no Reject finding and no BIT102, with distinct policy names and
plugin ids (REQ-179; TS §8.3 "The SR §1.1 canonical example must import
successfully"); the SR §1.1 example alone in another fresh catalog is
``success``. Owner: tester-m7-154.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.catalog_lock import catalog_lock
from bitscan_manager.services.importer.pipeline import (
    Actor,
    ImportOutcome,
    Mode,
    import_one,
)

from .bit_unit import SAMPLES
from .catalog_rows import owner
from .conftest import own_migrated_server
from .pipeline_rows import FixedClock, bits_dir, server_file
from .test_bit_fixtures import sr_example

pytestmark = pytest.mark.pg

SAMPLE_FILES = sorted(SAMPLES.glob("*.bit"))


def fresh_import(
    tmp: Path, files: list[tuple[str, bytes]]
) -> tuple[list[ImportOutcome], list[tuple[str, int]]]:
    (tmp / "creds").mkdir()
    with own_migrated_server(tmp / "creds") as server:
        db = AppDatabase(SecretStr(server.dsn("bitscan_app")), connect_timeout_s=3)
        db.open()
        try:
            outs = []
            for name, data in files:
                with db.session() as s, catalog_lock(s):
                    outs.append(
                        import_one(
                            s, FixedClock(), bits_dir(tmp), server_file(data, name),
                            mode=Mode.AUTO, actor=Actor("system", None),
                            file_exists=lambda p: True,
                        )
                    )  # fmt: skip
        finally:
            db.close()
        with owner(server) as c:
            counts = [
                (str(n), int(k))
                for n, k in c.execute(
                    "SELECT p.policy_name, count(pp.plugin_uuid) FROM policy p"
                    " JOIN policy_plugin pp USING (policy_id) GROUP BY 1 ORDER BY 1"
                ).fetchall()
            ]
    return outs, counts


def test_all_samples_import_together_with_no_reject_and_no_bit102(
    tmp_path: Path,
) -> None:
    assert len(SAMPLE_FILES) >= 2
    outs, counts = fresh_import(
        tmp_path, [(p.name, p.read_bytes()) for p in SAMPLE_FILES]
    )
    for path, out in zip(SAMPLE_FILES, outs, strict=True):
        assert out.outcome == "success", (path.name, out.findings)
        assert not [f for f in out.findings if f.rejects], path.name
        assert all(f.code.value != "BIT102" for f in out.findings), path.name
        assert out.plugins_added > 0
    assert len({o.policy_name for o in outs}) == len(outs)
    assert len(counts) == len(outs)
    # distinct plugin ids: each sample's plugins are all its own
    assert sum(k for _, k in counts) == sum(o.plugins_added for o in outs)


def test_the_sr_example_alone_imports_in_a_fresh_catalog(tmp_path: Path) -> None:
    outs, counts = fresh_import(tmp_path, [("sr.bit", sr_example())])
    assert [(o.outcome, o.policy_version, o.plugins_added) for o in outs] == [
        ("success", 1, 1)
    ]
    assert counts == [("CIS Ubuntu 24.04 Level 1 - Server", 1)]
