#!/usr/bin/env python3
"""Download a pinned official Mihomo release; verify its SHA-256 before extraction."""
import gzip
import io
import os
import platform
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError

from rules import ROOT, sha256
from sync import RETRYABLE_HTTP_STATUSES, fetch

VERSION = "v1.19.31"
ASSETS = {
    "Windows": (
        "mihomo-windows-amd64-v1-v1.19.31.zip",
        "d89c9bd746e8aacff89b2edf674813e25e8bd2dc565f4e12dc3b4526dd2b3177",
        563462668,
    ),
    "Linux": (
        "mihomo-linux-amd64-v1-v1.19.31.gz",
        "d4304c546c3cddcb6fafd4b4fddb0ba1a95ffa36606fda56d75db2e59ad24114",
        563462722,
    ),
}
DOWNLOAD_LIMIT = 100_000_000
PRIMARY_BUDGET = 90
FALLBACK_BUDGET = 135


def extracted_binary(name, payload):
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [entry for entry in archive.namelist() if entry.endswith(".exe")]
            if len(names) != 1:
                raise ValueError("Unexpected archive executable count")
            # No extractall: archive paths cannot escape the destination.
            return archive.read(names[0])
    return gzip.decompress(payload)


def download_archive(name, asset_id):
    try:
        return fetch(f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{name}",
                     limit=DOWNLOAD_LIMIT, deadline=time.monotonic() + PRIMARY_BUDGET)
    except OSError as exc:
        if isinstance(exc, HTTPError) and exc.code not in RETRYABLE_HTTP_STATUSES:
            raise
        reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        print(f"Mihomo release download failed ({reason}); trying the official release asset API", file=sys.stderr)
        return fetch(f"https://api.github.com/repos/MetaCubeX/mihomo/releases/assets/{asset_id}",
                     limit=DOWNLOAD_LIMIT, attempts=5, deadline=time.monotonic() + FALLBACK_BUDGET,
                     accept="application/octet-stream")


def write_atomic(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verified_archive(name, expected, asset_id):
    cache = ROOT / ".work/mihomo-download" / name
    try:
        with cache.open("rb") as handle:
            payload = handle.read(DOWNLOAD_LIMIT + 1)
        if len(payload) <= DOWNLOAD_LIMIT and sha256(payload) == expected:
            print(f"Using SHA-256-verified Mihomo archive from cache: {name}")
            return payload
        print(f"Ignoring Mihomo archive with an invalid cache checksum: {name}", file=sys.stderr)
    except FileNotFoundError:
        pass
    payload = download_archive(name, asset_id)
    if sha256(payload) != expected:
        raise SystemExit("Mihomo release SHA-256 mismatch")
    write_atomic(cache, payload, 0o644)
    return payload


def main():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Only x86_64 verification binaries are pinned")
    name, expected, asset_id = ASSETS[platform.system()]
    binary = extracted_binary(name, verified_archive(name, expected, asset_id))
    path = ROOT / ".work/bin" / ("mihomo.exe" if os.name == "nt" else "mihomo")
    if not path.exists() or sha256(path.read_bytes()) != sha256(binary):
        write_atomic(path, binary, 0o755)
    path.chmod(0o755)
    print(path)


if __name__ == "__main__":
    main()
