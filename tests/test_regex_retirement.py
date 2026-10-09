"""Scoped anomaly handling must compare rule identity before host matching."""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from automation import reconcile, row_of
from rules import Rule
from sync import affected_retirement_keys


class RegexRetirementTests(unittest.TestCase):
    def setUp(self):
        self.regex = Rule('DOMAIN-REGEX', r'^chatgpt-async-webps-prod-\S+-\d+\.webpubsub\.azure\.com$')
        self.active = Rule('DOMAIN', 'active.example.com')
        self.unrelated = Rule('DOMAIN', 'retired.example.com')
        self.origin = {'v2fly:data/openai'}
        self.rows = [row_of(('openai', 'core', rule), self.origin)
                     for rule in (self.regex, self.active, self.unrelated)]
        self.manifest = {'provenance': self.rows}
        self.issues = [{'vendor': 'openai', 'rule': self.regex.text,
                        'reason': 'unreviewed-upstream-attribute', 'attributes': ['@unreviewed']}]

    def test_identical_regex_is_frozen_even_when_it_cannot_match_its_own_text(self):
        self.assertFalse(self.regex.matches(self.regex.value))
        self.assertTrue(self.regex.matches('chatgpt-async-webps-prod-a-1.webpubsub.azure.com'))
        self.assertEqual(affected_retirement_keys(self.manifest, self.issues),
                         {('openai', 'core', self.regex)})

    def test_same_vendor_unrelated_rules_are_not_frozen(self):
        unrelated_regex = Rule('DOMAIN-REGEX', r'^other-\d+\.example\.com$')
        manifest = {'provenance': self.rows + [row_of(('openai', 'core', unrelated_regex), self.origin)]}
        affected = affected_retirement_keys(manifest, self.issues)
        self.assertNotIn(('openai', 'core', unrelated_regex), affected)
        self.assertNotIn(('openai', 'core', self.unrelated), affected)
        self.assertNotIn(('openai', 'core', self.active), affected)

    def test_identity_match_does_not_cross_vendor_or_tier_boundaries(self):
        manifest = {'provenance': [row_of(('other', 'core', self.regex), self.origin),
                                   row_of(('openai', 'extras', self.regex), self.origin)]}
        self.assertEqual(affected_retirement_keys(manifest, self.issues), set())

    def test_domain_and_suffix_overlap_still_freezes_only_related_rules(self):
        suffix = Rule('DOMAIN-SUFFIX', 'example.com')
        specific = Rule('DOMAIN', 'child.example.com')
        manifest = {'provenance': [row_of(('openai', 'core', suffix), self.origin),
                                   row_of(('openai', 'core', specific), self.origin)]}
        issues = [{'vendor': 'openai', 'value': 'child.example.com'}]
        self.assertEqual(affected_retirement_keys(manifest, issues),
                         {('openai', 'core', suffix), ('openai', 'core', specific)})

    def test_aged_anomalous_regex_is_retained_but_healthy_unrelated_removal_continues(self):
        retained = [dict(row, first_missing='2026-09-01', observation_days=['2026-09-01', '2026-09-02', '2026-09-03'])
                    for row in self.rows if row['rule'] != self.active.text]
        catalog = {'vendors': [{'id': 'openai', 'sources': ['openai']}], 'profiles': {}}
        patches = {'add': [], 'drop': {}, 'surge_regex': {self.regex.value: {}}}
        state, report = reconcile(
            {('openai', 'core', self.active): self.origin}, self.manifest, catalog, patches,
            {'pending': [], 'retained': retained},
            {'removal_grace_days': 14, 'removal_min_observation_days': 3},
            today=date(2026, 10, 9), unhealthy_keys=affected_retirement_keys(self.manifest, self.issues))
        self.assertEqual([row['rule'] for row in state['retained']], [self.regex.text])
        self.assertNotIn('2026-10-09', state['retained'][0]['observation_days'])
        self.assertEqual([row['rule'] for row in report['automatically_removed']], [self.unrelated.text])
        self.assertEqual(report['deletion_observation_frozen_vendors'], [])
        self.assertEqual(report['deletion_observation_frozen_rules'], [{'vendor': 'openai', 'rule': self.regex.text}])


if __name__ == '__main__':
    unittest.main()
