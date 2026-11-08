#!/usr/bin/env python3
"""Download a pinned official Mihomo release; verify its SHA-256 before extraction."""
import gzip
import io
import os
import platform
import sys
import time
import zipfile
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
ENDPOINT_BUDGET = 90


def extracted_binary(name, payload):
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [entry for entry in archive.namelist() if entry.endswith(".exe")]
            if len(names) != 1:
                raise ValueError("Unexpected archive executable count")
            # No extractall: archive paths cannot escape the destination.
            return archive.read(names[0])
    return gzip.decompress(payload)


def main():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Only x86_64 verification binaries are pinned")
    name, expected, asset_id = ASSETS[platform.system()]
    try:
        payload = fetch(f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{name}",
                        limit=DOWNLOAD_LIMIT, deadline=time.monotonic() + ENDPOINT_BUDGET)
    except OSError as exc:
        if isinstance(exc, HTTPError) and exc.code not in RETRYABLE_HTTP_STATUSES:
            raise
        reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        print(f"Mihomo release download failed ({reason}); trying the official release asset API", file=sys.stderr)
        payload = fetch(f"https://api.github.com/repos/MetaCubeX/mihomo/releases/assets/{asset_id}",
                        limit=DOWNLOAD_LIMIT, deadline=time.monotonic() + ENDPOINT_BUDGET,
                        accept="application/octet-stream")
    if sha256(payload) != expected:
        raise SystemExit("Mihomo release SHA-256 mismatch")
    binary = extracted_binary(name, payload)
    destination = ROOT / ".work/bin"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ("mihomo.exe" if os.name == "nt" else "mihomo")
    if path.exists() and sha256(path.read_bytes()) == sha256(binary):
        print(path)
        return
    temporary = path.with_name(path.name + ".download")
    try:
        temporary.write_bytes(binary)
        temporary.chmod(0o755)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    path.chmod(0o755)
    print(path)


if __name__ == "__main__":
    main()
