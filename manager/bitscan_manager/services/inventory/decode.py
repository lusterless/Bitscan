"""Inventory upload decoder (TS §3.4 L240, §6.5 L1186, §8.1 L1250; #33, #60,
#72; plan work/plans/TASK-060.md).

Pure: no database. It returns a complete DecodedInventory or raises one
InventoryRefused, never partial data. Statuses (#72 (b), (c); rulings
2026-10-23): 413 too_large for byte limits (decompressed size, raw); 422 for
the contract model, more than 50,000 packages, duplicates and a list_sha256
mismatch; 400 invalid_request for a broken gzip stream, invalid UTF-8 or JSON,
U+0000 or a lone surrogate in any string, and nesting deeper than MAX_DEPTH.
Reasons are fixed words, never input; nothing here is logged.
"""

import hashlib
import json
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, NoReturn

from pydantic import ValidationError

from bitscan_manager.api.agent.schemas import InventoryBody, OsInfo, PackageItem

MIB: Final = 1_048_576
DECOMPRESSED_CAP: Final = 64 * MIB  # TS §3.4 L240
RAW_CAP: Final = 256 * 1024  # os_info.raw, compact UTF-8 JSON
MAX_PACKAGES: Final = 50_000
# Containers nested deeper than this anywhere in the body are refused before
# the model sees them, so a too-deep raw is a fixed 400 well inside
# pydantic-core's own recursion guard (lead ruling 2026-10-23).
MAX_DEPTH: Final = 32
_GZIP: Final = 31  # zlib wbits: one gzip member, header and trailer checked


class InventoryRefused(Exception):
    def __init__(self, status: int, type_: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.type = type_
        self.reason = reason


def _refuse(status: int, reason: str) -> NoReturn:
    type_ = {413: "too_large", 422: "about:blank"}.get(status, "invalid_request")
    raise InventoryRefused(status, type_, reason)


@dataclass(frozen=True)
class DecodedInventory:
    os_info: OsInfo
    packages: tuple[PackageItem, ...]
    list_sha256: str  # recomputed from packages (#33); equal to the agent's
    raw_json: str  # compact os_info.raw, at most RAW_CAP bytes in UTF-8


def gunzip_capped(chunks: Iterable[bytes], cap: int) -> bytes:
    """Streams one gzip member, never producing more than cap + 1 bytes: a
    bomb stops there (413). Truncated or trailing data is a 400."""
    inflater = zlib.decompressobj(_GZIP)
    out = bytearray()
    try:
        for chunk in chunks:
            data = chunk
            while data:
                if inflater.eof:
                    _refuse(400, "trailing_data")
                out += inflater.decompress(data, cap + 1 - len(out))
                if len(out) > cap:
                    _refuse(413, "decompressed_too_large")
                data = inflater.unconsumed_tail
            if inflater.unused_data:
                _refuse(400, "trailing_data")
    except zlib.error:
        _refuse(400, "bad_gzip")
    if not inflater.eof:
        _refuse(400, "truncated_gzip")
    return bytes(out)


def list_sha256(packages: Sequence[PackageItem]) -> str:
    """TS §6.5 L1186 and #33: the UTF-8 lines name\\tversion\\tarchitecture\\t
    status\\n, sorted by their bytes, concatenated, SHA-256, lowercase hex."""
    lines = sorted(
        f"{p.name}\t{p.version}\t{p.architecture}\t{p.status}\n".encode()
        for p in packages
    )
    return hashlib.sha256(b"".join(lines)).hexdigest()


def _no_constants(name: str) -> NoReturn:
    raise ValueError(name)  # NaN and Infinity are not JSON (RFC 8259)


def _storable_tree(document: Any) -> None:
    """One iterative walk: every key and string is storable (no U+0000, no
    lone surrogate) and no container is nested deeper than MAX_DEPTH."""
    stack: list[tuple[Any, int]] = [(document, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, str):
            if "\x00" in item:
                _refuse(400, "nul_character")
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                _refuse(400, "lone_surrogate")
        elif isinstance(item, dict | list):
            if depth >= MAX_DEPTH:
                _refuse(400, "too_deep")
            children = (
                [*item.keys(), *item.values()] if isinstance(item, dict) else item
            )
            stack.extend((child, depth + 1) for child in children)


def decode_inventory(body: bytes) -> DecodedInventory:
    """body: the gzip request body as sent (the route caps it at 10 MiB)."""
    raw_bytes = gunzip_capped((body,), DECOMPRESSED_CAP)
    try:
        text = raw_bytes.decode("utf-8")
        del raw_bytes
        document = json.loads(text, parse_constant=_no_constants)
    except (UnicodeDecodeError, ValueError, RecursionError):
        _refuse(400, "bad_json")
    del text
    _storable_tree(document)
    packages = document.get("packages") if isinstance(document, dict) else None
    if isinstance(packages, list) and len(packages) > MAX_PACKAGES:
        _refuse(422, "too_many_packages")  # before validating every row
    try:
        inventory = InventoryBody.model_validate(document)
    except ValidationError:
        _refuse(422, "invalid_field")
    raw_json = json.dumps(
        inventory.os_info.raw,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(raw_json.encode("utf-8")) > RAW_CAP:
        _refuse(413, "raw_too_large")
    keys = {(p.name, p.version, p.architecture) for p in inventory.packages}
    if len(keys) != len(inventory.packages):
        _refuse(422, "duplicate_package")
    digest = list_sha256(inventory.packages)
    if digest != inventory.list_sha256:
        _refuse(422, "hash_mismatch")
    return DecodedInventory(
        inventory.os_info, tuple(inventory.packages), digest, raw_json
    )
