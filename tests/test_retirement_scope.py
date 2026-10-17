"""Only suspicious upstream rules should suspend automated retirement."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import automation
import rules
import sync


class ScopedRetirementTests(unittest.TestCase):
    def setUp(self):
        self.origin = {"v2fly:data/dedicated"}
        self.old_affected = ("demo", "core", rules.Rule("DOMAIN", "affected.example.com"))
        self.old_unrelated = ("demo", "core", rules.Rule("DOMAIN", "retirable.other.test"))
        self.good = ("demo", "core", rules.Rule("DOMAIN", "normal.example.com"))
        self.before = {"provenance": [
            automation.row_of(row, self.origin)
            for row in (self.old_affected, self.old_unrelated, self.good)
        ]}
        self.catalog = {"vendors": [{"id": "demo", "sources": ["dedicated"]}]}
        self.patches = {"add": [], "drop": {}, "surge_regex": {}}

    def test_unknown_tag_does_not_freeze_whole_vendor(self):
        issues = [{"vendor": "demo", "rule": "DOMAIN,affected.example.com",
                   "reason": "unreviewed-upstream-attribute"}]
        frozen = sync.affected_retirement_keys(self.before, issues)
        self.assertEqual(frozen, {self.old_affected})
        current = {self.good: set(self.origin)}
        state, report = automation.reconcile(
            current, self.before, self.catalog, self.patches,
            {"schema": 1, "pending": [], "retained": []},
            {"removal_grace_days": 0, "removal_min_observation_days": 1},
            unhealthy_keys=frozen, allow_removals=True, contracts={"vendors": {}},
        )
        self.assertEqual([automation.key_of(x) for x in state["retained"]],
                         [self.old_affected])
        self.assertEqual([automation.key_of(x) for x in report["automatically_removed"]],
                         [self.old_unrelated])
        self.assertEqual(report["deletion_observation_frozen_vendors"], [])
        self.assertEqual(report["deletion_observation_frozen_rules"],
                         [{"vendor": "demo", "rule": "DOMAIN,affected.example.com"}])
        self.assertIn(self.old_affected,
                      automation.effective_entries(current, self.catalog, self.patches, state))

    def test_new_unrelated_unknown_tag_does_not_freeze_old_rules(self):
        issue = [{"vendor": "demo", "rule": "DOMAIN,entirely-new.example.com"}]
        self.assertEqual(sync.affected_retirement_keys(self.before, issue), set())

    def test_related_suffix_or_selected_value_freezes_only_matching_prior_rule(self):
        suffix = [{"vendor": "demo", "rule": "DOMAIN-SUFFIX,example.com"}]
        selected = [{"vendor": "demo", "value": "affected.example.com"}]
        for issues in (suffix, selected):
            with self.subTest(issues=issues):
                self.assertEqual(sync.affected_retirement_keys(self.before, issues),
                                 {self.old_affected, self.good} if issues is suffix
                                 else {self.old_affected})

    def test_full_upstream_outage_still_freezes_all_missing_rules(self):
        state, report = automation.reconcile(
            {self.good: set(self.origin)}, self.before, self.catalog, self.patches,
            {"schema": 1, "pending": [], "retained": []},
            {"removal_grace_days": 0, "removal_min_observation_days": 1},
            source_observation_healthy=False, allow_removals=True,
            contracts={"vendors": {}},
        )
        self.assertEqual({automation.key_of(x) for x in state["retained"]},
                         {self.old_affected, self.old_unrelated})
        self.assertEqual(len(report["deletion_observation_frozen_rules"]), 2)

    def test_reviewed_drop_and_known_exclusion_do_not_create_noise(self):
        catalog = {"vendors": [{"id": "demo", "group": "global", "sources": ["dedicated"]}]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dedicated").write_text(
                "full:ads.example.com @ads @brand-new\n"
                "full:ignored.example.com @brand-new\n"
                "full:normal.example.com @cn\n",
                encoding="utf-8",
            )
            patches = {"add": [], "drop": {"demo": {
                "DOMAIN,ignored.example.com": "locally excluded",
            }}}
            issues = []
            rows = rules.collect(catalog, patches, root, review_mode=True,
                                 attribute_issues=issues)
        self.assertFalse(issues)
        self.assertEqual({r[2].value for r in rows}, {"normal.example.com"})


if __name__ == "__main__":
    unittest.main()
