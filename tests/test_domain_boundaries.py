"""Independent shared examples for compiler, artifact oracle and fact extraction."""
import itertools
import sys
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import intake
import rules
import verify_rules


class DomainBoundaryTests(unittest.TestCase):
    def extract(self, text):
        source = {'id': 'domain-boundaries', 'url': 'https://official.test/network',
                  'vendor': 'fixture', 'format': 'html', 'sections': ['Network'],
                  'required_hosts': ['control.example'], 'min_hosts': 1}
        page = '<h2>Network</h2><p>control.example ' + text + '</p>'
        return intake.extract_document(source, page.encode())['rules']

    def assert_contract(self, host, accepted):
        for kind in ('DOMAIN', 'DOMAIN-SUFFIX'):
            line = f'{kind},{host}'
            for label, operation in (
                ('compiler', lambda: rules.Rule.from_text(line)),
                ('surge', lambda: verify_rules.parse_artifact((line + '\n').encode(), 'surge')),
                ('mihomo', lambda: verify_rules.parse_artifact(('payload:\n  - "' + line + '"\n').encode(), 'mihomo')),
            ):
                with self.subTest(host=host, kind=kind, gate=label):
                    if accepted:
                        operation()
                    else:
                        with self.assertRaises(ValueError):
                            operation()

    def test_supported_hosts_agree_across_all_three_chains(self):
        for host in ('service.xn--p1ai', 'xn--fsqu00a.xn--0zwm56d', 'xn--bcher-kva.example',
                     'api-1.example', 'a' * 63 + '.example', '.'.join(['a' * 63] * 3 + ['b' * 61])):
            self.assert_contract(host, True)
            self.assertIn('DOMAIN,' + host, self.extract(host))

    def test_unsupported_final_labels_and_bad_lengths_fail_both_gates(self):
        for host in ('service.123', 'service.a', 'service.a1', 'service.a-b',
                     'service.xn--', 'service.-xn--p1ai', 'service.xn--p1ai-',
                     'service.' + 'a' * 64, 'a' * 64 + '.example',
                     '.'.join(['a' * 63] * 3 + ['b' * 62]), 'service..example',
                     'service_example.com', '*.service.xn--p1ai'):
            self.assert_contract(host, False)

    def test_malformed_wildcards_are_not_salvaged_as_parent_suffixes(self):
        for text in ('*..service.xn--p1ai', '..service.xn--p1ai', '*.*.service.xn--p1ai',
                     'partial*.service.xn--p1ai', 'api.*.service.xn--p1ai',
                     'service.xn--p1ai*', 'user@service.xn--p1ai',
                     'service.xn--p1ai-', 'service.123'):
            with self.subTest(text=text):
                self.assertEqual(self.extract(text), ['DOMAIN,control.example'])

    def test_single_wildcard_and_leading_dot_keep_exact_suffix_semantics(self):
        for prefix in ('*.', '.'):
            rows = self.extract(prefix + 'SERVICE.XN--P1AI')
            self.assertEqual(rows, ['DOMAIN,control.example', 'DOMAIN-SUFFIX,service.xn--p1ai'])
            line = rows[1]
            self.assertTrue(verify_rules.domain_matches(line, 'a.service.xn--p1ai'))
            self.assertFalse(verify_rules.domain_matches(line, 'notservice.xn--p1ai'))
            self.assertFalse(verify_rules.domain_matches(line, 'service.xn--p1ai.evil.example'))

    def test_verifier_remains_independent_of_compiler_validator(self):
        with mock.patch.object(rules.Rule, 'validate', side_effect=AssertionError('must not reuse compiler')):
            self.assertEqual(verify_rules.parse_artifact(b'DOMAIN,service.xn--p1ai\n', 'surge'),
                             ['DOMAIN,service.xn--p1ai'])
            with self.assertRaises(ValueError):
                verify_rules.parse_artifact(b'DOMAIN,service.123\n', 'surge')

    def test_deterministic_label_boundary_matrix_agrees(self):
        # These are ASCII syntax probes, not claims of IDNA registration or validity.
        labels = ('a', 'ab', '1', 'a-b', '-ab', 'ab-', 'a_b', 'xn--p1ai',
                  'xn--', 'a' * 63, 'a' * 64)
        for first, final in itertools.product(labels, repeat=2):
            host = first + '.' + final
            try:
                rules.Rule.from_text('DOMAIN,' + host)
                compiled = True
            except ValueError:
                compiled = False
            self.assertEqual(compiled, bool(verify_rules.valid_host(host)), host)


if __name__ == '__main__':
    unittest.main()
