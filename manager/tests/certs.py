"""Throwaway test PKI made at test time with the openssl CLI (no key is ever
committed). Used by the sink, vault and serve tests (TP-M2-08, -10, -22).
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class Leaf:
    cert: Path
    key: Path


@dataclass(frozen=True)
class Pki:
    ca: Path
    ca_key: Path
    root: Path

    def leaf(self, name: str, sans: str = "DNS:localhost,IP:127.0.0.1") -> Leaf:
        key = self.root / f"{name}-leaf.key"
        csr = self.root / f"{name}-leaf.csr"
        cert = self.root / f"{name}-leaf.pem"
        ext = self.root / f"{name}-leaf.ext"
        ext.write_text(
            f"subjectAltName={sans}\nbasicConstraints=CA:FALSE\n"
            "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n",
            encoding="ascii",
        )
        _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", key)
        _openssl("req", "-new", "-key", key, "-subj", f"/CN={name}", "-out", csr)
        _openssl(
            "x509",
            "-req",
            "-in",
            csr,
            "-CA",
            self.ca,
            "-CAkey",
            self.ca_key,
            "-CAcreateserial",
            "-days",
            "2",
            "-sha256",
            "-extfile",
            ext,
            "-out",
            cert,
        )
        return Leaf(cert, key)


def openssl_path() -> str | None:
    return shutil.which("openssl")


def _openssl(*args: object) -> None:
    exe = openssl_path()
    assert exe is not None
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [exe, *map(str, args)],
        capture_output=True,
        text=True,
        env={**os.environ, "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]


def make_pki(root: Path, name: str = "ca") -> Pki:
    if openssl_path() is None:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("openssl is required for the TLS tests (CI=true)")
        pytest.skip("not run: openssl unavailable")
    root.mkdir(parents=True, exist_ok=True)
    ca_key = root / f"{name}.key"
    ca = root / f"{name}.pem"
    _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", ca_key)
    _openssl(
        "req",
        "-x509",
        "-new",
        "-key",
        ca_key,
        "-sha256",
        "-days",
        "2",
        "-subj",
        f"/CN=Bitscan test {name}",
        "-out",
        ca,
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    return Pki(ca, ca_key, root)
