#!/usr/bin/env python3
"""GitHub cron backs up CF dispatches; missing history permits a full validated sync."""
import json
import os
import subprocess
from datetime import datetime, timezone


def backup_needed(history, now):
    runs = history["workflow_runs"]
    if not isinstance(runs, list):
        raise ValueError("Invalid workflow history")
    if not runs:
        return True
    latest = runs[0]
    if latest["head_branch"] != "main" or latest["event"] != "workflow_dispatch":
        raise ValueError("Unexpected workflow history")
    created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
    age = (now - created).total_seconds()
    healthy = latest["conclusion"] == "success" or latest["status"] in {
        "queued", "in_progress", "waiting", "pending", "requested"
    }
    return not (0 <= age < 6 * 3600 and healthy)


def main():
    if os.environ.get("GITHUB_REPOSITORY") != "NET86/rules":
        raise ValueError("Scheduler is restricted to NET86/rules")
    try:
        raw = subprocess.check_output([
            "gh", "api", "repos/NET86/rules/actions/workflows/sync.yml/runs"
            "?branch=main&event=workflow_dispatch&per_page=1"
        ], text=True, encoding="utf-8", timeout=45)
        needed = backup_needed(json.loads(raw), datetime.now(timezone.utc))
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
        # A duplicate validated sync is preferable to suppressing the only backup.
        print("History unavailable or invalid; retaining backup sync.")
        needed = True
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_sync={str(needed).lower()}\n")
    message = ("需要兜底同步：没有可确认的近期健康主调度记录。" if needed
               else "跳过兜底：近期主调度已成功或仍在运行；本次没有重复执行生产校验。")
    print("Backup sync required." if needed else "Recent primary sync is healthy; skipping backup.")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as output:
                output.write("## 调度判定\n\n" + message + "\n")
        except OSError:
            print("WARNING: summary unavailable; scheduling decision is unchanged")


if __name__ == "__main__":
    main()
