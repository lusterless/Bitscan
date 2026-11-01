"""TP-M10-03 (tester-m10): REQ-243 (2) and (3), the redaction cross-check.

The agent's runner matches redaction patterns with Go's ``regexp``; the
manager accepts them with ``google-re2`` (#134, owner note). This file checks,
on the manager side:

* REQ-243 (2): the five default patterns extracted from TS §8.6 at test time
  equal, byte for byte, the default seeded by migration m0005 and the settings
  default, and compile in google-re2.
* REQ-243 (3): on the shared corpus
  ``tests/contract/fixtures/redaction/corpus.json`` each default pattern finds
  exactly the expected matches (byte spans, left to right). The Go suite
  (``agent/internal/redact``, TestCorpusGoRegexp) checks the same file with
  Go's ``regexp``, so both engines agree on the five defaults.

Pure: no database.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import re2  # type: ignore[import-untyped]

from bitscan_manager.services.settings.redaction import DEFAULT_PATTERNS

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "docs" / "spec" / "Technical_Specification.md"
FIXTURES = Path(__file__).resolve().parent / "contract" / "fixtures"
CORPUS = FIXTURES / "redaction" / "corpus.json"
MIGRATIONS = ROOT / "manager" / "bitscan_manager" / "db" / "migrations"
M0005 = MIGRATIONS / "versions" / "m0005_privileges_seeds.py"


def spec_patterns() -> list[str]:
    """The ```text block after "**Default redaction patterns**" in TS §8.6."""
    text = TS.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index("**Default redaction patterns**")
    block = text[text.index("```text\n", start) + len("```text\n") :]
    lines = block[: block.index("\n```")].split("\n")
    assert len(lines) == 5, lines
    return lines


def load_m0005() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0005_under_test", M0005)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus() -> list[dict[str, Any]]:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    assert len(cases) >= 40
    return cases


def expected_spans(text: bytes, matches: list[str]) -> list[tuple[int, int]]:
    """Byte spans of the expected matches, by sequential search."""
    out: list[tuple[int, int]] = []
    pos = 0
    for m in matches:
        mb = m.encode("utf-8")
        i = text.find(mb, pos)
        assert i >= 0, (m, pos)
        out.append((i, i + len(mb)))
        pos = i + len(mb)
    return out


def test_spec_list_equals_the_seeded_and_settings_defaults() -> None:
    """CHK-M10-015 (REQ-243 (2))."""
    spec = spec_patterns()
    assert list(DEFAULT_PATTERNS) == spec
    assert list(load_m0005().REDACTION_PATTERNS) == spec
    for p in spec:
        re2.compile(p)


@pytest.mark.parametrize("case", corpus(), ids=lambda c: str(c["name"]))
def test_corpus_matches_with_google_re2(case: dict[str, Any]) -> None:
    """CHK-M10-016 (REQ-243 (3)): google-re2 finds the expected spans."""
    patterns = [re2.compile(p.encode("utf-8")) for p in spec_patterns()]
    text = case["input"].encode("utf-8")
    assert len(case["matches"]) == 5
    for i, rx in enumerate(patterns):
        got = [(m.start(), m.end()) for m in rx.finditer(text)]
        assert got == expected_spans(text, case["matches"][i]), (case["name"], i + 1)
