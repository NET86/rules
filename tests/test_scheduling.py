"""Protect primary/backup freshness and privileged dependency merge boundaries."""
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from schedule_gate import backup_needed
from merge_dependencies import eligible
import merge_dependencies


class BackupTests(unittest.TestCase):
    def test_recent_success_or_active_skips_but_failure_does_not(self):
        now = datetime(2026, 9, 21, 6, 49, tzinfo=timezone.utc)
        run = {"head_branch": "main", "event": "workflow_dispatch",
               "created_at": (now - timedelta(minutes=30)).isoformat(),
               "status": "completed", "conclusion": "success"}
        for status, conclusion, expected in [
            ("completed", "success", False), ("in_progress", None, False),
            ("queued", None, False), ("completed", "failure", True),
            ("completed", "cancelled", True), ("completed", "skipped", True),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                self.assertEqual(backup_needed({"workflow_runs": [dict(
                    run, status=status, conclusion=conclusion)]}, now), expected)
        for age in [5, 6, -1]:
            run["created_at"] = (now - timedelta(hours=age)).isoformat()
            self.assertTrue(backup_needed({"workflow_runs": [run]}, now))
        self.assertTrue(backup_needed({"workflow_runs": []}, now))

    def test_skipped_backup_cannot_be_mistaken_for_primary(self):
        with self.assertRaises(ValueError):
            backup_needed({"workflow_runs": [{"head_branch": "main", "event": "schedule"}]},
                          datetime.now(timezone.utc))


class DependencyMergeTests(unittest.TestCase):
    def fixture(self):
        repo = {"full_name": "NET86/rules"}
        branch = "dependabot/pip/transport-safe-123abc"
        pr = {"state": "open", "draft": False, "user": {"login": "dependabot[bot]"},
              "base": {"repo": repo, "ref": "main"}, "head": {"repo": repo, "ref": branch, "sha": "abc"},
              "changed_files": 1}
        run = {"head_repository": repo, "actor": {"login": "dependabot[bot]"},
               "path": ".github/workflows/ci.yml", "event": "pull_request", "status": "completed",
               "conclusion": "success", "head_sha": "abc", "head_branch": branch}
        jobs = [{"name": f"validate ({os})", "status": "completed", "conclusion": "success", "head_sha": "abc"}
                for os in ["ubuntu-latest", "windows-latest"]]
        files = [{"filename": "requirements-intake.txt", "status": "modified"}]
        return pr, run, jobs, files

    def test_both_allowed_groups_merge(self):
        pr, run, jobs, files = self.fixture()
        self.assertTrue(eligible(pr, run, jobs, files))
        pr["head"]["ref"] = run["head_branch"] = "dependabot/github_actions/actions-safe-ab123"
        files[0]["filename"] = ".github/workflows/ci.yml"
        self.assertTrue(eligible(pr, run, jobs, files))

    def test_fails_closed_for_stale_checks_forks_major_updates_and_extra_files(self):
        changes = [
            lambda p, r, j, f: p["head"].update(sha="new-commit"),
            lambda p, r, j, f: p["head"].update(repo={"full_name": "other/rules"}),
            lambda p, r, j, f: p["user"].update(login="someone"),
            lambda p, r, j, f: p.update(draft=True),
            lambda p, r, j, f: p.update(state="closed"),
            lambda p, r, j, f: p["base"].update(ref="stable"),
            lambda p, r, j, f: p["head"].update(ref="dependabot/pip/cffi-3.0.0"),
            lambda p, r, j, f: r.update(event="push"),
            lambda p, r, j, f: r.update(conclusion="failure"),
            lambda p, r, j, f: r.update(path=".github/workflows/sync.yml"),
            lambda p, r, j, f: j.pop(),
            lambda p, r, j, f: j[1].update(conclusion="skipped"),
            lambda p, r, j, f: j[1].update(head_sha="old"),
            lambda p, r, j, f: f[0].update(filename="scripts/merge_dependencies.py"),
            lambda p, r, j, f: f[0].update(status="added"),
            lambda p, r, j, f: p.update(changed_files=101),
        ]
        for change in changes:
            fixture = copy.deepcopy(self.fixture())
            change(*fixture)
            with self.subTest(change=change):
                self.assertFalse(eligible(*fixture))

    def test_merge_resolves_empty_event_pr_list_and_binds_tested_sha(self):
        pr, run, jobs, files = self.fixture()
        run.update(id=42, pull_requests=[])
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps({"workflow_run": {"id": 42}}), encoding="utf-8")
            responses = [run, {"jobs": jobs, "total_count": 2}, [{"number": 9}], pr, files, {"merged": True}]
            with patch.dict(os.environ, GITHUB_REPOSITORY="NET86/rules", GITHUB_EVENT_PATH=str(event_path)), \
                    patch.object(merge_dependencies, "api", side_effect=responses) as api:
                merge_dependencies.main()
                self.assertIn("head=NET86%3Adependabot%2Fpip%2F", api.call_args_list[2].args[0])
                self.assertEqual(api.call_args.args, ("repos/NET86/rules/pulls/9/merge",
                                                     {"sha": "abc", "merge_method": "squash"}))


if __name__ == "__main__":
    unittest.main()
