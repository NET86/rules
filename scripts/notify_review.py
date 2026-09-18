#!/usr/bin/env python3
"""Maintain one automation-owned exception issue per channel, without repeat comments."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from rules import read_json

REPOSITORY = "NET86/rules"


def issue_body(channel, report):
    marker = f"<!-- rules-automation:{channel} -->"
    # Omit clock/observation counters: identical exceptions produce identical bodies.
    rows = sorted({json.dumps({k: v for k, v in row.items() if k in {"vendor", "tier", "section", "rule", "reason", "source", "source_id", "error_type"}}, ensure_ascii=False, sort_keys=True) for row in report.get("review_required", [])})
    failed = any(row.get("reason") == "workflow-failed" for row in report.get("review_required", []))
    if failed:
        status = "本次工作流失败，请查看 Actions 日志；不要把上一份成功报告当成本次成功。未通过校验的规则不会发布。"
    elif channel == "sources":
        status = "Sukka 二级雷达只读运行；以下缺口仅供复核，不会自动进入生产规则。"
    else:
        status = "自动更新继续运行；以下例外已隔离或保留上一可用版本，不会直接扩大核心规则。"
    return marker + "\n\n" + status + "\n\n```json\n" + json.dumps([json.loads(row) for row in rows], ensure_ascii=False, indent=2) + "\n```\n\n[Actions](https://github.com/NET86/rules/actions) · [维护说明](https://github.com/NET86/rules/blob/main/docs/MAINTAINING.md)。状态不变不重复评论；例外消失后自动关闭。\n"


def load_report(path, failed=False):
    try:
        report = read_json(path)
        if not isinstance(report, dict) or not isinstance(report.get("review_required"), list):
            raise ValueError("Invalid exception report")
    except (OSError, ValueError):
        if not failed:
            raise
        report = {"review_required": []}
    if failed:
        report["review_required"].append({"reason": "workflow-failed"})
    return report


def gh(*args, body=None):
    return subprocess.check_output(["gh", *args], input=body, text=True, encoding="utf-8", timeout=45)


def notify(channel, report, call=gh):
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("Issue automation is restricted to NET86/rules")
    title = f"[rules automation] {channel} exceptions"
    marker = f"<!-- rules-automation:{channel} -->"
    results = json.loads(call("issue", "list", "--repo", REPOSITORY, "--state", "all", "--limit", "100", "--search", f'in:title "{title}"', "--json", "number,title,body,state"))
    owned = [row for row in results if row["title"] == title and row["body"].startswith(marker)]
    if len(owned) > 1:
        raise ValueError("Duplicate automation issues require review; not mutating multiple issues")
    existing = owned[0] if owned else None
    if not report.get("review_required"):
        if existing and existing["state"] == "OPEN":
            call("issue", "close", str(existing["number"]), "--repo", REPOSITORY, "--reason", "completed")
        return
    body = issue_body(channel, report)
    if not existing:
        call("issue", "create", "--repo", REPOSITORY, "--title", title, "--body-file", "-", body=body)
    else:
        number = str(existing["number"])
        if existing["body"] != body:
            call("issue", "edit", number, "--repo", REPOSITORY, "--body-file", "-", body=body)
        if existing["state"] != "OPEN":
            call("issue", "reopen", number, "--repo", REPOSITORY)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=["sync", "sources"])
    parser.add_argument("report")
    parser.add_argument("--failed", action="store_true", help="Report workflow failure even if staging never produced a report")
    args = parser.parse_args()
    notify(args.channel, load_report(Path(args.report), args.failed))
    print("Exception issue synchronized (no repeated comments)")


if __name__ == "__main__":
    main()
