"""Reader for the shared agent wire-contract fixtures (TP-M3-01, REQ-061).

The fixtures in ``fixtures/`` were written by the tester from TS §6.5
(L1159-L1190) and the #60 field table in ``work/plans/TASK-048.md``, not from
the code. ``fixtures/manifest.json`` lists every file with its route,
direction, validity and constraint class. Entries with ``generate`` are built
here from their file (the M4 Go tests implement the same four operations, as
described in the manifest's ``about``).

``list_sha256`` below is the test's own oracle for TS §6.5 L1186 and #33: the
lines ``name\\tversion\\tarchitecture\\tstatus\\n`` in UTF-8, sorted by bytes,
concatenated, SHA-256, lowercase hex.
"""

import copy
import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST_PATH = FIXTURES / "manifest.json"


@dataclass(frozen=True)
class Fixture:
    file: str
    route: str
    direction: str
    valid: bool
    cls: str | None
    reason: str
    decoder: Mapping[str, Any] | None
    generate: Mapping[str, Any] | None
    schema_gap: str | None = None

    @property
    def id(self) -> str:
        return self.file.removesuffix(".json")

    @property
    def body_key(self) -> str:
        return f"{self.route}/{self.direction}"

    def raw_bytes(self) -> bytes:
        return (FIXTURES / self.file).read_bytes()

    def body(self) -> Any:
        """The fixture body, with any ``generate`` operation applied."""
        base = json.loads(self.raw_bytes().decode("utf-8"))
        if self.generate is None:
            return base
        return apply_generate(base, self.generate)

    def body_bytes(self) -> bytes:
        """The bytes a client would send (the file itself unless generated)."""
        if self.generate is None:
            return self.raw_bytes()
        return json.dumps(self.body(), ensure_ascii=False).encode("utf-8")


def manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def fixtures() -> list[Fixture]:
    out = []
    for e in manifest()["fixtures"]:
        out.append(
            Fixture(
                file=e["file"],
                route=e["route"],
                direction=e["direction"],
                valid=e["valid"],
                cls=e.get("class"),
                reason=e["reason"],
                decoder=e.get("decoder"),
                generate=e.get("generate"),
                schema_gap=e.get("schema_gap"),
            )
        )
    return out


def select(route: str | None = None, direction: str | None = None) -> Iterator[Fixture]:
    for f in fixtures():
        if route is not None and f.route != route:
            continue
        if direction is not None and f.direction != direction:
            continue
        yield f


def list_sha256(packages: Sequence[Mapping[str, Any]]) -> str:
    lines = sorted(
        f"{p['name']}\t{p['version']}\t{p['architecture']}\t{p['status']}\n".encode()
        for p in packages
    )
    return hashlib.sha256(b"".join(lines)).hexdigest()


def _uuid_for(n: int) -> str:
    h = f"{n:032x}"
    # RFC 9562 version 4 / variant 10 layout so every generated id is a valid UUID
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def apply_generate(base: Any, gen: Mapping[str, Any]) -> Any:
    body = copy.deepcopy(base)
    op = gen["op"]
    if op == "plugins_count":
        job = body["jobs"][0]
        tmpl = job["plugins"][0]
        job["plugins"] = [
            {**tmpl, "plugin_uuid": _uuid_for(i + 1)} for i in range(gen["count"])
        ]
    elif op == "packages_count":
        pk = [
            {
                "name": f"pkg-{i}",
                "version": "1.0",
                "architecture": "amd64",
                "status": "install ok installed",
                "source": f"pkg-{i}",
                "installed_size_kb": 1,
            }
            for i in range(gen["count"])
        ]
        body["packages"] = pk
        body["list_sha256"] = list_sha256(pk)
    elif op == "ip_addresses_count":
        n = gen["count"]
        body["os_info"]["ip_addresses"] = [
            f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}" for i in range(n)
        ]
    elif op == "raw_bytes":
        target = gen["bytes"]
        overhead = len(json.dumps({"pad": ""}, separators=(",", ":")).encode())
        body["os_info"]["raw"] = {"pad": "a" * (target - overhead)}
        got = len(json.dumps(body["os_info"]["raw"], separators=(",", ":")).encode())
        assert got == target, got
    else:  # pragma: no cover - manifest error
        raise AssertionError(f"unknown generate op {op!r}")
    return body
