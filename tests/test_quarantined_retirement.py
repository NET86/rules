"""Quarantined patterns are never run to attribute retirement anomalies."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from automation import reconcile, row_of
from rules import Rule
from sync import affected_retirement_keys


class QuarantinedRetirementTests(unittest.TestCase):
    def setUp(self):
        self.pattern = Rule("DOMAIN-REGEX", r"^(.+)+Z$")
        self.origin = {"v2fly:data/demo"}
        self.related = ("demo", "core", Rule("DOMAIN", "related.example.com"))
        self.suffix = ("demo", "core", Rule("DOMAIN-SUFFIX", "example.com"))
        self.pattern_key = ("demo", "core", self.pattern)
        self.unrelated = ("other", "core", Rule("DOMAIN", "retired.other.test"))
        self.ip = ("demo", "core", Rule("IP-CIDR", "192.0.2.0/24"))
        self.keys = [self.related, self.suffix, self.pattern_key, self.unrelated, self.ip]
        self.manifest = {"provenance": [row_of(key, self.origin) for key in self.keys]}
        self.issue = {"vendor": "demo", "rule": self.pattern.text,
                      "reason": "unreviewed-upstream-attribute", "attributes": ["@unreviewed"]}

    def frozen_without_pattern_matching(self, issues):
        original = Rule.matches
        def bomb(rule, value):
            if rule == self.pattern:
                raise AssertionError("quarantined regexp evaluated")
            return original(rule, value)
        with patch.object(Rule, "matches", bomb):
            return affected_retirement_keys(self.manifest, issues)

    def test_unknown_regexp_retains_domain_rules_without_running_matcher(self):
        self.assertEqual(self.frozen_without_pattern_matching([self.issue]),
                         {self.related, self.suffix, self.pattern_key})

    def test_literal_issue_before_identical_historical_pattern_cannot_run_it(self):
        literal = {"vendor": "demo", "value": "other.example.com"}
        for issues in ([literal, self.issue], [self.issue, literal]):
            with self.subTest(issues=issues):
                self.assertEqual(self.frozen_without_pattern_matching(issues),
                                 {self.related, self.suffix, self.pattern_key})

    def test_retirement_keeps_uncertain_rules_and_removes_provably_unrelated(self):
        frozen = self.frozen_without_pattern_matching([self.issue])
        catalog = {"vendors": [{"id": vendor, "sources": ["demo"]}
                               for vendor in ("demo", "other")]}
        patches = {"add": [], "drop": {}, "surge_regex": {self.pattern.value: {}}}
        active_other = ("other", "core", Rule("DOMAIN", "active.other.test"))
        state, report = reconcile(
            {active_other: self.origin}, self.manifest, catalog, patches, {"pending": [], "retained": []},
            {"removal_grace_days": 0, "removal_min_observation_days": 1},
            today=date(2026, 10, 13), allow_removals=True, unhealthy_keys=frozen,
            contracts={"vendors": {}},
        )
        self.assertEqual({row["rule"] for row in state["retained"]},
                         {key[2].text for key in frozen})
        self.assertEqual({row["rule"] for row in report["automatically_removed"]},
                         {self.unrelated[2].text, self.ip[2].text})

    def test_literal_attribution_still_allows_unrelated_same_vendor_retirement(self):
        manifest = {"provenance": [row_of(key, self.origin) for key in
                    (self.related, ("demo", "core", self.unrelated[2]))]}
        self.assertEqual(affected_retirement_keys(manifest, [
            {"vendor": "demo", "rule": self.related[2].text}
        ]), {self.related})


if __name__ == "__main__":
    unittest.main()
