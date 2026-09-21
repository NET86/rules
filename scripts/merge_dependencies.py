#!/usr/bin/env python3
"""Merge only trusted Dependabot minor/patch groups after both CI jobs pass."""
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
    # These two groups are explicitly limited to minor/patch in dependabot.yml.
    if re.fullmatch(r"dependabot/github_actions/actions-safe-[0-9a-f]+", branch):
        allowed_files = ACTION_FILES
    elif re.fullmatch(r"dependabot/pip/transport-safe-[0-9a-f]+", branch):
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


def api(path, body=None):
    if not path.startswith(f"repos/{REPO}/"):
        raise ValueError("Unexpected repository")
    args = ["gh", "api", path]
    if body is not None:
        args += ["--method", "PUT", "--input", "-"]
    return json.loads(subprocess.check_output(
        args, input=json.dumps(body) if body is not None else None,
        text=True, encoding="utf-8", timeout=45
    ))


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("Dependency automation is restricted to NET86/rules")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    # Re-fetch server state rather than relying on an old completion event.
    run = api(f"repos/{REPO}/actions/runs/{int(event['workflow_run']['id'])}")
    jobs_response = api(f"repos/{REPO}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")
    jobs = jobs_response["jobs"]
    if len(jobs) != jobs_response["total_count"]:
        raise ValueError("Incomplete CI job list")
    # workflow_run.pull_requests can be empty; resolve the live PR by its fixed repo/head.
    query = urlencode({"state": "open", "base": "main", "head": f"NET86:{run['head_branch']}", "per_page": 100})
    for link in api(f"repos/{REPO}/pulls?{query}"):
        number = int(link["number"])
        pr = api(f"repos/{REPO}/pulls/{number}")
        files = api(f"repos/{REPO}/pulls/{number}/files?per_page=100")
        if not eligible(pr, run, jobs, files):
            print(f"PR #{number}: not eligible for automatic merge.")
            continue
        result = api(f"repos/{REPO}/pulls/{number}/merge", {
            "sha": pr["head"]["sha"], "merge_method": "squash"
        })
        if not result.get("merged"):
            raise ValueError("GitHub did not merge the tested commit")
        print(f"PR #{number}: merged tested dependency update.")


if __name__ == "__main__":
    main()
