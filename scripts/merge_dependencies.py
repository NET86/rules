#!/usr/bin/env python3
"""Merge trusted Dependabot version-update groups after both CI jobs pass."""
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlencode

REPO = "NET86/rules"
BOT = "dependabot[bot]"
REQUIRED_JOBS = {"validate (ubuntu-latest)", "validate (windows-latest)"}
ACTION_FILES = {f".github/workflows/{name}.yml" for name in (
    "ci", "sync", "audit", "dependency-automerge"
)}


def eligible(pr, run, jobs, files):
    if (pr["state"] != "open" or pr["draft"] or pr["user"]["login"] != BOT
            or pr["base"]["repo"]["full_name"] != REPO or pr["base"]["ref"] != "main"
            or pr["head"]["repo"]["full_name"] != REPO
            or run["head_repository"]["full_name"] != REPO
            or run["actor"]["login"] != BOT or run["event"] != "pull_request"
            or run["path"] != ".github/workflows/ci.yml"
            or run["status"] != "completed" or run["conclusion"] != "success"
            or run["head_sha"] != pr["head"]["sha"]
            or run["head_branch"] != pr["head"]["ref"]):
        return False
    branch = pr["head"]["ref"]
    # All version levels are allowed; CI success and scope are mandatory.
    if re.fullmatch(r"dependabot/github_actions/actions-tested-[0-9a-f]+", branch):
        allowed_files = ACTION_FILES
    elif re.fullmatch(r"dependabot/pip/transport-tested-[0-9a-f]+", branch):
        allowed_files = {"requirements-intake.txt"}
    else:
        return False
    if not files or len(files) != pr["changed_files"]:
        return False
    if any(row["status"] != "modified" or row["filename"] not in allowed_files for row in files):
        return False
    checked = {job["name"] for job in jobs if job["status"] == "completed"
               and job["conclusion"] == "success" and job["head_sha"] == pr["head"]["sha"]}
    return REQUIRED_JOBS <= checked


def api(path):
    if not path.startswith(f"repos/{REPO}/"):
        raise ValueError("Unexpected repository")
    return json.loads(subprocess.check_output(
        ["gh", "api", path],
        text=True, encoding="utf-8", timeout=45
    ))


def git(*args):
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8", timeout=120).strip()


def fast_forward(head, call=git):
    """Publish exactly a tested head; the server rejects a concurrent main update."""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid tested commit SHA")
    call("fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main", head)
    base = call("rev-parse", "refs/remotes/origin/main")
    if call("merge-base", base, head) != base:
        return False
    # No merge/rebase or PR checkout: privileged code never executes candidate code.
    # No force/lease: if main moves beyond our base, ordinary Git fast-forward
    # enforcement refuses the push instead of creating an untested combination.
    call("push", "origin", f"{head}:refs/heads/main")
    return True


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("Dependency automation is restricted to NET86/rules")
    if git("remote", "get-url", "origin") not in {
        f"https://github.com/{REPO}", f"https://github.com/{REPO}.git",
        "git@github-net86:NET86/rules.git",
    }:
        raise ValueError("Unexpected dependency publication remote")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    # Re-fetch server state rather than relying on an old completion event.
    run = api(f"repos/{REPO}/actions/runs/{int(event['workflow_run']['id'])}")
    jobs_response = api(f"repos/{REPO}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")
    jobs = jobs_response["jobs"]
    if len(jobs) != jobs_response["total_count"]:
        raise ValueError("Incomplete CI job list")
    # workflow_run.pull_requests can be empty; resolve the live PR by its fixed repo/head.
    query = urlencode({"state": "open", "base": "main", "head": f"NET86:{run['head_branch']}", "per_page": 100})
    decisions = []
    for link in api(f"repos/{REPO}/pulls?{query}"):
        number = int(link["number"])
        pr = api(f"repos/{REPO}/pulls/{number}")
        files = api(f"repos/{REPO}/pulls/{number}/files?per_page=100")
        if not eligible(pr, run, jobs, files):
            decisions.append(f"- PR #{number}：不符合自动合并条件，未合并。")
        elif fast_forward(pr["head"]["sha"]):
            decisions.append(f"- PR #{number}：已快进到经过测试的 `{pr['head']['sha']}`。")
        else:
            decisions.append(f"- PR #{number}：main 已前进，未合并；等待 rebase 和重新测试。")
        print(decisions[-1])
    return {"decisions": decisions}


if __name__ == "__main__":
    report = main()
    work = Path(__file__).resolve().parents[1] / ".work"
    work.mkdir(exist_ok=True)
    (work / "dependency-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
