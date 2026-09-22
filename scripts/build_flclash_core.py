#!/usr/bin/env python3
"""Build the pinned routing core embedded by FlClash, not its UI/IPC wrapper."""
import json
import os
import subprocess
from pathlib import Path

from rules import ROOT


def main():
    lock = json.loads((ROOT / "sources/engines.json").read_text(encoding="utf-8"))["flclash"]
    work = ROOT / ".work"
    repo = work / "flclash-core-source"
    binary = work / "bin" / ("flclash-core.exe" if os.name == "nt" else "flclash-core")
    repo.mkdir(parents=True, exist_ok=True)
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", lock["core_repository"]], check=True)
    origin = subprocess.check_output(["git", "-C", str(repo), "remote", "get-url", "origin"], text=True, timeout=30).strip()
    dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"], text=True, timeout=30).strip()
    if origin != lock["core_repository"] or dirty:
        raise ValueError("Cached core source has an unexpected origin or local changes; refusing to build or clean it")
    subprocess.run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin", lock["core_revision"]], check=True, timeout=180)
    subprocess.run(["git", "-C", str(repo), "switch", "--detach", lock["core_revision"]], check=True)
    subprocess.run(["go", "build", "-mod=readonly", "-trimpath", "-buildvcs=false", "-o", str(binary), "."], cwd=repo, check=True, timeout=600)
    print(f"Built FlClash {lock['app_version']} routing core {lock['core_revision']}: {binary}")


if __name__ == "__main__":
    main()
