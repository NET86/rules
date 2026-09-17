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
    subprocess.run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin", lock["core_revision"]], check=True)
    subprocess.run(["git", "-C", str(repo), "switch", "--detach", lock["core_revision"]], check=True)
    subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "-o", str(binary), "."], cwd=repo, check=True, timeout=600)
    print(f"Built FlClash {lock['app_version']} routing core {lock['core_revision']}: {binary}")


if __name__ == "__main__":
    main()
