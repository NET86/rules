import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
