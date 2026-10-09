"""Adversarial proof that native reuse cannot launder stale or invalid input."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_cache
from rules import ROOT


class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'input'
        shutil.copytree(ROOT / 'rules', self.root / 'rules')
        (self.root / 'sources').mkdir()
        shutil.copyfile(ROOT / 'sources/semantic-contracts.json', self.root / 'sources/semantic-contracts.json')
        self.source = self.base / 'verifier'
        (self.source / 'scripts').mkdir(parents=True)
        (self.source / 'scripts/fixture.py').write_text('VERSION = 1\n')
        self.binary = self.base / 'engine'
        self.binary.write_bytes(b'fake binary identity for isolated unit test')
        self.binaries = [('mihomo', self.binary)]
        self.calls = []
        self.session = runtime_cache.RuntimeGateSession(self.good_gate, self.source)

    def good_gate(self, root, binaries, profile):
        self.calls.append((root, profile))
        for label, _ in binaries:
            (root / '.work' / f'{label}-validation-{profile}.json').write_text(json.dumps({
                'result': 'PASS', 'engine_label': label, 'profile': profile, 'routing_case_count': 1,
                'cases': [{'host': 'fixture.invalid', 'expected_core_or_voice': True, 'matched': True}]}))

    def invoke(self, root=None, profile='ai-daily'):
        return self.session(root or self.root, self.binaries, profile)

    def test_same_bytes_different_download_directory_reuse_only_native_work(self):
        other = self.base / 'downloaded'
        shutil.copytree(self.root, other)
        with patch.object(runtime_cache, 'verify', wraps=runtime_cache.verify) as portable:
            first = self.invoke()
            second = self.invoke(other)
        self.assertEqual(first['execution'], 'executed')
        self.assertEqual(second['execution'], 'reused')
        self.assertEqual(first['key'], second['key'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(portable.call_count, 3)
        report = json.loads((other / '.work/mihomo-validation-ai-daily.json').read_text())
        self.assertEqual(report['runtime_gate']['execution'], 'reused')

    def test_changed_binary_is_a_miss_even_at_the_same_path(self):
        self.invoke()
        self.binary.write_bytes(b'new engine implementation')
        self.assertEqual(self.invoke()['execution'], 'executed')
        self.assertEqual(len(self.calls), 2)

    def test_profile_and_engine_label_cannot_share_evidence(self):
        self.invoke()
        self.assertEqual(self.invoke(profile='split')['execution'], 'executed')
        self.binaries = [('flclash-core', self.binary)]
        self.assertEqual(self.invoke()['execution'], 'executed')
        self.assertEqual(len(self.calls), 3)

    def test_corrupt_actual_artifact_is_rejected_even_with_old_manifest(self):
        self.invoke()
        (self.root / 'rules/mihomo/ai-daily.yaml').write_bytes(b'payload: [broken\n')
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(len(self.calls), 1)

    def test_manifest_provenance_change_reexecutes_native_cases(self):
        self.invoke()
        path = self.root / 'rules/manifest.json'
        manifest = json.loads(path.read_text())
        manifest['upstream']['v2fly_revision'] = 'b' * 40
        path.write_text(json.dumps(manifest))
        self.assertEqual(self.invoke()['execution'], 'executed')
        self.assertEqual(len(self.calls), 2)

    def test_contract_byte_change_requires_a_new_native_check(self):
        self.invoke()
        path = self.root / 'sources/semantic-contracts.json'
        path.write_bytes(path.read_bytes() + b'\n')
        manifest_path = self.root / 'rules/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['semantic_contract']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        self.assertEqual(self.invoke()['execution'], 'executed')

    def test_verifier_changes_abort_instead_of_reusing_old_loaded_code(self):
        self.invoke()
        (self.source / 'scripts/fixture.py').write_text('VERSION = 2\n')
        with self.assertRaisesRegex(RuntimeError, 'Verifier source changed'):
            self.invoke()

    def test_native_failure_never_populates_success_cache(self):
        def failing(root, binaries, profile):
            self.good_gate(root, binaries, profile)
            raise RuntimeError('injected native failure')
        self.session.native_gate = failing
        with self.assertRaisesRegex(RuntimeError, 'injected native'):
            self.invoke()
        self.session.native_gate = self.good_gate
        self.assertEqual(self.invoke()['execution'], 'executed')
        self.assertEqual(len(self.calls), 2)

    def test_zero_exit_without_new_report_cannot_inherit_stale_pass(self):
        (self.root / '.work').mkdir()
        self.good_gate(self.root, self.binaries, 'ai-daily')
        self.session.native_gate = lambda *args: None
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertEqual(self.session._entries, {})

    def test_wrong_profile_or_failed_report_is_not_cached(self):
        def wrong(root, binaries, profile):
            self.good_gate(root, binaries, profile)
            path = root / '.work/mihomo-validation-ai-daily.json'
            report = json.loads(path.read_text())
            report['profile'] = 'split'
            path.write_text(json.dumps(report))
        self.session.native_gate = wrong
        with self.assertRaisesRegex(ValueError, 'invalid native'):
            self.invoke()
        self.assertEqual(self.session._entries, {})

    def test_pass_label_cannot_hide_a_failed_or_missing_routing_case(self):
        for mode in ('mismatch', 'count', 'missing'):
            with self.subTest(mode=mode):
                def dishonest(root, binaries, profile):
                    self.good_gate(root, binaries, profile)
                    path = root / '.work/mihomo-validation-ai-daily.json'
                    report = json.loads(path.read_text())
                    if mode == 'mismatch':
                        report['cases'][0]['matched'] = False
                    elif mode == 'count':
                        report['routing_case_count'] = 2
                    else:
                        report.pop('cases')
                    path.write_text(json.dumps(report))
                session = runtime_cache.RuntimeGateSession(dishonest, self.source)
                with self.assertRaisesRegex(ValueError, 'invalid native'):
                    session(self.root, self.binaries)
                self.assertEqual(session._entries, {})

    def test_binary_change_during_native_execution_invalidates_result(self):
        def changed(root, binaries, profile):
            self.good_gate(root, binaries, profile)
            self.binary.write_bytes(b'changed during run')
        self.session.native_gate = changed
        with self.assertRaisesRegex(RuntimeError, 'inputs changed'):
            self.invoke()
        self.assertEqual(self.session._entries, {})

    def test_destination_report_tampering_cannot_change_in_memory_evidence(self):
        self.invoke()
        path = self.root / '.work/mihomo-validation-ai-daily.json'
        path.write_text('{"result":"invented"}')
        self.assertEqual(self.invoke()['execution'], 'reused')
        self.assertEqual(json.loads(path.read_text())['result'], 'PASS')
        self.assertEqual(len(self.calls), 1)

    def test_new_process_scope_never_uses_previous_disk_pass(self):
        self.invoke()
        self.session = runtime_cache.RuntimeGateSession(self.good_gate, self.source)
        self.assertEqual(self.invoke()['execution'], 'executed')
        self.assertEqual(len(self.calls), 2)

    def test_invalid_engine_scope_cannot_alias_cached_reports(self):
        for binaries in ([], [('mihomo', self.binary), ('mihomo', self.binary)], [('../outside', self.binary)]):
            with self.subTest(binaries=binaries), self.assertRaises(ValueError):
                self.session(self.root, binaries)


if __name__ == '__main__':
    unittest.main()
