#!/usr/bin/env python3
"""Fail closed when repository commits contain an unexpected human identity."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

NET86_NAME = "NET86"
NET86_EMAIL = "43442823+NET86@users.noreply.github.com"
BOT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\[bot\]$")
BOT_EMAIL_RE = re.compile(r"^\d+\+[A-Za-z0-9_.-]+\[bot\]@users\.noreply\.github\.com$")
PLATFORM_IDENTITIES = {("GitHub", "noreply@github.com")}


def allowed_human_or_bot(name: str, email: str) -> bool:
    if (name, email) == (NET86_NAME, NET86_EMAIL):
        return True
    if (name, email) in PLATFORM_IDENTITIES:
        return True
    return bool(BOT_NAME_RE.fullmatch(name) and BOT_EMAIL_RE.fullmatch(email))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def check_current_identity() -> list[str]:
    problems = []
    name = git("config", "--get", "user.name")
    email = git("config", "--get", "user.email")
    if (name, email) != (NET86_NAME, NET86_EMAIL):
        problems.append(f"current Git identity must be {NET86_NAME} <{NET86_EMAIL}>, got {name} <{email}>")
    return problems


def check_history() -> list[str]:
    try:
        raw = git("log", "--all", "--format=%H%x09%an%x09%ae%x09%cn%x09%ce")
    except subprocess.CalledProcessError:
        return []
    if not raw:
        return []
    problems = []
    for line in raw.splitlines():
        sha, an, ae, cn, ce = line.split("\t", 4)
        if not allowed_human_or_bot(an, ae):
            problems.append(f"{sha}: unexpected author {an} <{ae}>")
        if not allowed_human_or_bot(cn, ce):
            problems.append(f"{sha}: unexpected committer {cn} <{ce}>")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-only", action="store_true", help="check only repository-local effective commit identity")
    args = parser.parse_args()
    problems = check_current_identity() if args.current_only else check_history()
    if problems:
        print("Git identity isolation check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Git identity isolation check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
