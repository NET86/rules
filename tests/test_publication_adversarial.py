"""Distinguish development progress from a broken stable publication."""
from pathlib import Path
import subprocess
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

    def test_commit_refs_failure_retries_and_validates_the_original_candidate(self):
        self.check_main_push_after_commit_refs_error()

    def test_commit_refs_failure_with_acknowledgement_lost_reads_main_back(self):
        self.check_main_push_after_commit_refs_error(accepted=True)

    def test_commit_refs_failure_does_not_overwrite_concurrent_main(self):
        self.check_main_push_after_commit_refs_error(concurrent=True)

    def test_main_push_stops_after_three_commit_refs_errors_or_one_policy_rejection(self):
        for stderr, attempts in (("remote: fatal error in commit_refs", 3),
                                 ("remote: GH006: Protected branch update failed", 1)):
            with self.subTest(stderr=stderr):
                def reject(*args, **kwargs):
                    if args[0] == "push":
                        raise subprocess.CalledProcessError(1, args, stderr=stderr)
                    return self.git(*args, **kwargs)

                with patch.object(self.publisher, "git", side_effect=reject) as git, patch.object(release.time, "sleep"):
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.publisher.run(self.candidate, lambda *args: self.fail("unexpected validation"),
                                           self.report, self.verified_refs)
                self.assertEqual(sum(call.args[0] == "push" for call in git.call_args_list), attempts)
                self.assertEqual(self.publisher.remote_ref("main"), self.old)
                self.assertEqual(self.publisher.remote_ref("stable"), self.old)

    def check_main_push_after_commit_refs_error(self, *, accepted=False, concurrent=False):
        pushes, validations = [], []
        other = self.git("commit-tree", self.publisher.tree(self.old), "-p", self.old,
                         input="independent main update\n")

        def push_with_error(*args, **kwargs):
            if args[0] == "push" and args[-1] == f"{self.candidate}:refs/heads/main":
                pushes.append(args)
                if len(pushes) == 1:
                    if accepted:
                        self.git(*args, **kwargs)
                    if concurrent:
                        self.git("push", "origin", f"{other}:main")
                    raise subprocess.CalledProcessError(1, args, stderr="remote: fatal error in commit_refs        \n")
            return self.git(*args, **kwargs)

        def validate(ref, label, expected):
            validations.append((label, expected))

        with patch.object(self.publisher, "git", side_effect=push_with_error), patch.object(release.time, "sleep"):
            if concurrent:
                with self.assertRaisesRegex(RuntimeError, "Concurrent main update"):
                    self.publisher.run(self.candidate, validate, self.report, self.verified_refs)
            else:
                self.publisher.run(self.candidate, validate, self.report, self.verified_refs)

        self.assertEqual(len(pushes), 1 if accepted or concurrent else 2)
        self.assertEqual(self.publisher.remote_ref("main"), other if concurrent else self.candidate)
        if concurrent:
            self.assertEqual(self.publisher.remote_ref("stable"), self.old)
            self.assertFalse(validations)
        else:
            self.assertEqual(validations[0], ("candidate", self.candidate))
            self.assertEqual(self.report["stable_remote_validation"], "PASS")

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
