import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_git_identity as identity


class IdentityPolicyTests(unittest.TestCase):
    def test_net86_is_allowed(self):
        self.assertTrue(identity.allowed_human_or_bot(identity.NET86_NAME, identity.NET86_EMAIL))

    def test_github_platform_is_allowed(self):
        self.assertTrue(identity.allowed_human_or_bot("GitHub", "noreply@github.com"))

    def test_github_bot_is_allowed(self):
        self.assertTrue(identity.allowed_human_or_bot(
            "github-actions[bot]",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ))

    def test_other_human_is_rejected(self):
        self.assertFalse(identity.allowed_human_or_bot(
            "Other User",
            "12345+other@users.noreply.github.com",
        ))

    def test_bot_name_with_human_email_is_rejected(self):
        self.assertFalse(identity.allowed_human_or_bot(
            "example[bot]",
            "person@example.com",
        ))

    def test_unreadable_history_is_not_success(self):
        error = identity.subprocess.CalledProcessError(128, ["git", "log"])
        with patch.object(identity, "git", side_effect=error), self.assertRaises(type(error)):
            identity.check_history()

    def test_history_scan_includes_non_main_refs(self):
        row = f"{'a' * 40}\tOther User\tperson@example.invalid\t{identity.NET86_NAME}\t{identity.NET86_EMAIL}"
        with patch.object(identity, "git", return_value=row) as git:
            self.assertEqual(len(identity.check_history()), 1)
        self.assertIn("--all", git.call_args.args)


if __name__ == "__main__":
    unittest.main()
