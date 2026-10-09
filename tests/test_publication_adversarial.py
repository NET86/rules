"""Distinguish development progress from a broken stable publication."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release
import test_intake_release as fixtures


class PublicationAdversarialTests(unittest.TestCase):
    manifest = fixtures.ReleaseTests.manifest
    setUp = fixtures.ReleaseTests.setUp
    tearDown = fixtures.ReleaseTests.tearDown

    def advance_main(self):
        newer = self.git('commit-tree', self.publisher.tree(self.candidate), '-p', self.candidate,
                         input='independent documentation update\n')
        self.git('push', 'origin', f'{newer}:main')
        return newer

    def test_verified_stable_is_not_rolled_back_for_independent_main_progress(self):
        moved = []
        def validate(ref, label, expected):
            if label == 'stable':
                moved.append(self.advance_main())
        stable = self.publisher.run(self.candidate, validate, self.report, self.verified_refs)
        self.assertEqual(self.publisher.tree(stable), self.publisher.tree(self.candidate))
        self.assertEqual(self.publisher.remote_ref('stable'), stable)
        self.assertEqual(self.publisher.remote_ref('main'), moved[0])
        self.assertEqual(self.report['result'], 'PASS')
        self.assertTrue(self.report['main_advanced_after_publication'])
        self.assertNotIn('rollback', self.report)

    def test_prepublication_main_progress_still_rejects_old_candidate(self):
        def validate(ref, label, expected):
            if label == 'candidate':
                self.advance_main()
        with self.assertRaisesRegex(RuntimeError, 'Concurrent main'):
            self.publisher.run(self.candidate, validate, self.report, self.verified_refs)
        self.assertEqual(self.publisher.remote_ref('stable'), self.old)

    def test_failed_stable_content_still_rolls_back_despite_main_progress(self):
        def validate(ref, label, expected):
            if label == 'stable':
                self.advance_main()
                raise ValueError('wrong published artifact bytes')
        with self.assertRaisesRegex(ValueError, 'wrong published'):
            self.publisher.run(self.candidate, validate, self.report, self.verified_refs)
        self.assertEqual(self.report['rollback'], 'RESTORED_STABLE')
        self.assertEqual(self.publisher.tree(self.publisher.remote_ref('stable')), self.publisher.tree(self.old))

    def test_concurrent_stable_update_is_not_overwritten_or_reported_as_ours(self):
        external = []
        def validate(ref, label, expected):
            if label == 'stable':
                current = self.publisher.remote_ref('stable')
                other = self.git('commit-tree', self.publisher.tree(self.old), '-p', current, input='external release\n')
                self.git('push', 'origin', f'{other}:stable')
                external.append(other)
        with self.assertRaisesRegex(RuntimeError, 'Concurrent stable'):
            self.publisher.run(self.candidate, validate, self.report, self.verified_refs)
        self.assertEqual(self.publisher.remote_ref('stable'), external[0])
        self.assertEqual(self.report['rollback'], 'SKIPPED_CONCURRENT_STABLE_UPDATE')
        self.assertNotEqual(self.report['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()
