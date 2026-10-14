"""Quarantined patterns are never run to attribute retirement anomalies."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from automation import reconcile, row_of
import rules
from rules import Rule, reviewed_match_entries
from intake import covered_by_vendor
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

    def test_reviewed_regex_resumes_selective_matching_after_quarantine_ends(self):
        pattern = Rule("DOMAIN-REGEX", r"^related\.[a-z]+\.com$")
        pattern_key = ("demo", "core", pattern)
        unrelated = ("demo", "core", Rule("DOMAIN", "unrelated.example.com"))
        manifest = {"provenance": [row_of(key, self.origin) for key in
                    (pattern_key, self.related, unrelated, self.ip, self.unrelated)]}
        issue = {"vendor": "demo", "rule": pattern.text}
        original = Rule.matches
        evaluated = []

        def matcher(rule, value):
            if rule == pattern:
                evaluated.append(value)
            return original(rule, value)

        with patch.object(Rule, "matches", matcher):
            self.assertEqual(affected_retirement_keys(manifest, [issue]),
                             {pattern_key, self.related, unrelated})
            self.assertEqual(evaluated, [])
            self.assertEqual(affected_retirement_keys(manifest, [
                {"vendor": "demo", "rule": self.related[2].text}
            ]), {pattern_key, self.related})
            self.assertEqual(evaluated, [self.related[2].value])
            self.assertEqual(affected_retirement_keys(manifest, []), set())

    def test_retirement_contract_checks_never_evaluate_quarantined_regex(self):
        frozen = self.frozen_without_pattern_matching([self.issue])
        catalog = {"vendors": [{"id": vendor, "sources": ["demo"]}
                               for vendor in ("demo", "other")],
                   "profiles": {"demo-profile": {"members": ["demo", "other"]}}}
        patches = {"add": [], "drop": {}, "surge_regex": {self.pattern.value: {}}}
        original = Rule.matches

        def bomb(rule, value):
            if rule == self.pattern:
                raise AssertionError("quarantined regexp evaluated by retirement contract")
            return original(rule, value)

        with patch.object(Rule, "matches", bomb):
            state, report = reconcile(
                {("other", "core", Rule("DOMAIN", "active.other.test")): self.origin},
                self.manifest, catalog, patches, {"pending": [], "retained": []},
                {"removal_grace_days": 0, "removal_min_observation_days": 1},
                today=date(2026, 10, 14), allow_removals=True, unhealthy_keys=frozen,
                contracts={"vendors": {"demo": {"must_match": ["related.example.com"]}},
                           "profiles": {"demo-profile": {"must_match": ["retired.other.test"]}}},
            )
        retained = {
            (row["vendor"], row["tier"], Rule.from_text(row["rule"]))
            for row in state["retained"]
        }
        self.assertIn(self.pattern_key, retained)
        self.assertIn(self.unrelated, retained)

    def test_coverage_scans_restore_regex_matching_after_quarantine_ends(self):
        pattern = Rule("DOMAIN-REGEX", r"^related\.[a-z]+\.com$")
        entries = {("demo", "core", pattern): self.origin}
        issue = {"vendor": "demo", "rule": pattern.text}
        blocked = reviewed_match_entries(entries, [issue])
        with patch.object(Rule, "matches", side_effect=AssertionError("isolated matcher")):
            self.assertFalse(covered_by_vendor(self.related[2], "demo", blocked))
        self.assertTrue(covered_by_vendor(self.related[2], "demo",
                                         reviewed_match_entries(entries, [])))
        self.assertEqual(entries, {("demo", "core", pattern): self.origin})

    def test_compiler_does_not_use_quarantined_regex_as_selected_coverage(self):
        catalog = {"vendors": [{"id": "demo", "sources": ["demo"]}]}
        patches = {"add": [], "drop": {}, "surge_regex": {self.pattern.value: {}}}
        documents = {"catalog.json": catalog, "patches.json": patches,
                     "semantic-contracts.json": {"schema": 2, "vendors": {"demo": {}}}}

        def collect(*args, **kwargs):
            kwargs["selection_issues"].append({"vendor": "demo", "value": "related.example.com"})
            kwargs["attribute_issues"].append(self.issue)
            return {}

        with patch.object(rules, "verify_snapshot", return_value={}), \
             patch.object(rules, "validate_profiles", return_value={}), \
             patch.object(rules, "read_json", side_effect=lambda path: documents[path.name]), \
             patch.object(rules, "collect", side_effect=collect), \
             patch.object(Rule, "matches", side_effect=AssertionError("isolated matcher")):
            with self.assertRaisesRegex(ValueError, "lost effective coverage"):
                rules.compile_outputs(Path("unused"), automation_state={
                    "retained": [row_of(self.pattern_key, self.origin)]
                })


if __name__ == "__main__":
    unittest.main()
