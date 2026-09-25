"""Protect primary/backup freshness and privileged dependency merge boundaries."""
import copy
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from schedule_gate import backup_needed
from merge_dependencies import eligible
import merge_dependencies


class BackupTests(unittest.TestCase):
    def test_only_recent_completed_cloudflare_success_skips(self):
        now = datetime(2026, 9, 21, 6, 49, tzinfo=timezone.utc)
        run = {"head_branch": "main", "event": "workflow_dispatch",
               "display_title": "Cloudflare scheduled sync",
               "created_at": (now - timedelta(minutes=30)).isoformat(),
               "status": "completed", "conclusion": "success"}
        for status, conclusion, expected in [
            ("completed", "success", False), ("in_progress", None, True),
            ("queued", None, True), ("completed", "failure", True),
            ("completed", "cancelled", True), ("completed", "skipped", True),
        ]:
            with self.subTest(status=status, conclusion=conclusion):
                self.assertEqual(backup_needed({"workflow_runs": [dict(
                    run, status=status, conclusion=conclusion)]}, now), expected)
        for age in [6, 7, -1]:
            run["created_at"] = (now - timedelta(hours=age)).isoformat()
            self.assertTrue(backup_needed({"workflow_runs": [run]}, now))
        for age in [timedelta(hours=5, minutes=25), timedelta(hours=5, minutes=59, seconds=59)]:
            run["created_at"] = (now - age).isoformat()
            self.assertFalse(backup_needed({"workflow_runs": [run]}, now))
        self.assertTrue(backup_needed({"workflow_runs": []}, now))

    def test_manual_success_cannot_hide_missing_or_failed_cloudflare_run(self):
        now = datetime(2026, 9, 21, 6, 49, tzinfo=timezone.utc)
        primary = {"head_branch": "main", "event": "workflow_dispatch",
                   "display_title": "Cloudflare scheduled sync",
                   "created_at": (now - timedelta(minutes=40)).isoformat(),
                   "status": "completed", "conclusion": "success"}
        manual = dict(primary, display_title="Manual sync",
                      created_at=(now - timedelta(minutes=5)).isoformat())
        self.assertFalse(backup_needed({"workflow_runs": [manual, primary]}, now))
        self.assertTrue(backup_needed({"workflow_runs": [manual]}, now))
        self.assertTrue(backup_needed({"workflow_runs": [manual, dict(primary, conclusion="failure")]}, now))
        self.assertTrue(backup_needed({"workflow_runs": [manual, dict(primary, status="in_progress",
                                                                      conclusion=None)]}, now))
        older_success = dict(primary, created_at=(now - timedelta(hours=5)).isoformat())
        self.assertTrue(backup_needed({"workflow_runs": [dict(primary, conclusion="failure"),
                                                        older_success]}, now))

    def test_summary_cannot_change_the_scheduling_output(self):
        import schedule_gate
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for needed in (False, True):
                for invalid_summary in (False, True):
                    with self.subTest(needed=needed, invalid_summary=invalid_summary):
                        output, summary = root / "output", root / "summary"
                        output.write_text("")
                        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as console, \
                                patch.object(sys, "stdout", console), \
                                patch.dict(os.environ, GITHUB_REPOSITORY="NET86/rules", GITHUB_OUTPUT=str(output),
                                        GITHUB_STEP_SUMMARY=str(root if invalid_summary else summary)), \
                                patch.object(schedule_gate.subprocess, "check_output", return_value='{"workflow_runs":[]}'), \
                                patch.object(schedule_gate, "backup_needed", return_value=needed):
                            schedule_gate.main()
                        self.assertEqual(output.read_text().strip(), f"run_sync={str(needed).lower()}")
                        if not invalid_summary:
                            self.assertIn("需要兜底" if needed else "本次没有重复执行生产校验", summary.read_text(encoding="utf-8"))

    def test_skipped_backup_cannot_be_mistaken_for_primary(self):
        with self.assertRaises(ValueError):
            backup_needed({"workflow_runs": [{"display_title": "Cloudflare scheduled sync",
                                              "head_branch": "main", "event": "schedule"}]},
                          datetime.now(timezone.utc))


class DependencyMergeTests(unittest.TestCase):
    def fixture(self):
        repo = {"full_name": "NET86/rules"}
        branch = "dependabot/pip/transport-tested-123abc"
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
        pr["head"]["ref"] = run["head_branch"] = "dependabot/github_actions/actions-tested-ab123"
        files[0]["filename"] = ".github/workflows/ci.yml"
        self.assertTrue(eligible(pr, run, jobs, files))

    def test_fails_closed_for_stale_checks_forks_ungrouped_updates_and_extra_files(self):
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
            responses = [run, {"jobs": jobs, "total_count": 2}, [{"number": 9}], pr, files]
            with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as console, \
                    patch.object(sys, "stdout", console), \
                    patch.dict(os.environ, GITHUB_REPOSITORY="NET86/rules", GITHUB_EVENT_PATH=str(event_path)), \
                    patch.object(merge_dependencies, "api", side_effect=responses) as api, \
                    patch.object(merge_dependencies, "git", return_value="git@github-net86:NET86/rules.git"), \
                    patch.object(merge_dependencies, "fast_forward", return_value=True) as publish:
                result = merge_dependencies.main()
                self.assertIn("已快进", result["decisions"][0])
                self.assertIn("head=NET86%3Adependabot%2Fpip%2F", api.call_args_list[2].args[0])
                publish.assert_called_once_with("abc")


class DependencyGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        subprocess.run(["git", "init", "--template=", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "--template=", "-b", "main", str(self.local)], check=True, capture_output=True)
        self.git("config", "user.name", "Dependency test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", str(self.remote))
        self.base = self.commit("base", "base")
        self.git("push", "origin", "main")
        self.git("switch", "-c", "dependency")
        self.head = self.commit("requirements-intake.txt", "tested update")
        self.git("push", "origin", "dependency")
        self.git("switch", "main")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.local), *args],
                                       text=True, encoding="utf-8", stderr=subprocess.PIPE).strip()

    def commit(self, path, content):
        (self.local / path).write_text(content, encoding="utf-8")
        self.git("add", path)
        self.git("commit", "-m", "fixture " + content)
        return self.git("rev-parse", "HEAD")

    def main_revision(self):
        return self.git("ls-remote", "origin", "refs/heads/main").split()[0]

    def test_publishes_exact_tested_head_without_checking_it_out(self):
        self.assertTrue(merge_dependencies.fast_forward(self.head, self.git))
        self.assertEqual(self.main_revision(), self.head)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)

    def test_advanced_main_waits_for_rebase_and_retest(self):
        advanced = self.commit("new-code", "new production code")
        self.git("push", "origin", "main")
        self.assertFalse(merge_dependencies.fast_forward(self.head, self.git))
        self.assertEqual(self.main_revision(), advanced)

    def test_server_rejects_main_race_after_local_ancestry_check(self):
        advanced = self.commit("new-code", "concurrent production code")
        def raced(*args):
            if args[0] == "push":
                self.git("push", "origin", "main")
            return self.git(*args)
        with self.assertRaises(subprocess.CalledProcessError):
            merge_dependencies.fast_forward(self.head, raced)
        self.assertEqual(self.main_revision(), advanced)

    def test_invalid_revision_cannot_reach_git(self):
        with patch.object(merge_dependencies, "git") as call:
            with self.assertRaises(ValueError):
                merge_dependencies.fast_forward("--all", call)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
