import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rules
import automation
import audit_sources
import notify_review
import sync
import verify_mihomo


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.stable = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "example.com"))
        self.old = ("demo", "core", rules.Rule("DOMAIN", "legacy.service.test"))
        self.approvals = {"demo": {"core": ["DOMAIN-SUFFIX,example.com", "DOMAIN,legacy.service.test"]}}
        self.patches = {"surge_regex": {}}
        self.policy = {"removal_grace_days": 14, "removal_min_observation_days": 3}
        self.contracts = {"vendors": {}}
        self.before = {"provenance": [automation.row_of(key, {"source"}) for key in [self.stable, self.old]]}
        self.candidates = {self.stable: {"source"}}
        self.empty = {"schema": 1, "pending": [], "retained": []}

    def reconcile(self, day, state=None, **kwargs):
        return automation.reconcile(
            self.candidates, self.before, self.approvals, self.patches,
            state or self.empty, self.policy,
            today=date(2026, 1, day), contracts=self.contracts, **kwargs
        )

    def test_unknown_root_quarantined_while_safe_update_continues(self):
        unknown = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "unknown.test"))
        child = ("demo", "core", rules.Rule("DOMAIN", "new.example.com"))
        self.candidates.update({unknown: {"source"}, child: {"source"}})
        state, report = self.reconcile(1)
        effective = automation.effective_entries(self.candidates, self.approvals, self.patches, state)
        self.assertIn(child, effective)
        self.assertNotIn(unknown, effective)
        self.assertEqual(report["quarantined_count"], 1)

    def test_unknown_regex_quarantined_without_breaking_domains(self):
        key = ("demo", "core", rules.Rule("DOMAIN-REGEX", "^new.*$"))
        self.candidates[key] = {"source"}
        state, report = self.reconcile(1)
        self.assertEqual(report["review_required"][0]["reason"], "unreviewed-surge-regex-adapter")
        self.assertNotIn(key, automation.effective_entries(self.candidates, self.approvals, self.patches, state))

    def test_shared_root_cannot_be_approved_into_core(self):
        key = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "amazonaws.com"))
        self.approvals["demo"]["core"].append(key[2].text)
        self.assertEqual(automation.scope_problem(key, self.approvals, self.patches), "shared-platform-forbidden-in-core")

    def test_removal_requires_grace_and_three_distinct_days(self):
        state, report = self.reconcile(1)
        self.assertEqual(len(state["retained"]), 1)
        state, _ = self.reconcile(2, state)
        state, report = self.reconcile(15, state)
        self.assertEqual(state["retained"], [])
        self.assertEqual(len(report["automatically_removed"]), 1)

    def test_repeated_same_day_does_not_accelerate_retirement(self):
        state, _ = self.reconcile(1)
        for _ in range(5):
            state, _ = self.reconcile(1, state)
        self.assertEqual(state["retained"][0]["observation_days"], ["2026-01-01"])
        state, _ = self.reconcile(20, state)
        self.assertEqual(len(state["retained"]), 1)

    def test_key_host_is_never_retired_automatically(self):
        self.contracts = {"vendors": {"demo": {"must_match": ["legacy.service.test"]}}}
        state, _ = self.reconcile(1)
        state, _ = self.reconcile(2, state)
        state, report = self.reconcile(20, state, allow_removals=True)
        self.assertTrue(state["retained"][0]["protected"])
        self.assertEqual(report["review_required"][0]["reason"], "protected-upstream-removal")

    def test_unhealthy_source_freezes_deletion_observation(self):
        state, _ = self.reconcile(1)
        self.assertEqual(state["retained"][0]["observation_days"], ["2026-01-01"])
        state, report = self.reconcile(20, state, source_observation_healthy=False)
        self.assertEqual(state["retained"][0]["observation_days"], ["2026-01-01"])
        self.assertEqual(state["retained"][0]["first_missing"], "2026-01-01")
        self.assertIn("demo", report["deletion_observation_frozen_vendors"])
        self.assertFalse(report["automatically_removed"])

    def test_last_vendor_rule_is_retained(self):
        self.candidates = {}
        state, _ = self.reconcile(1)
        state, _ = self.reconcile(2, state)
        state, _ = self.reconcile(20, state)
        self.assertTrue(any(row["protected"] for row in state["retained"]))

    def test_reappearing_rule_resets_missing_state(self):
        state, _ = self.reconcile(1)
        self.candidates[self.old] = {"source"}
        state, _ = self.reconcile(2, state)
        self.assertEqual(state["retained"], [])

    def test_lossless_redundant_rule_removal_needs_no_delay(self):
        redundant = ("demo", "core", rules.Rule("DOMAIN", "old.example.com"))
        self.before["provenance"] = [automation.row_of(key, {"source"}) for key in [self.stable, redundant]]
        state, report = self.reconcile(1)
        self.assertFalse(state["retained"])
        self.assertEqual(report["automatically_removed"][0]["reason"], "covered-by-current-rule")

    def test_withdrawn_approval_cannot_be_resurrected(self):
        self.approvals["demo"]["core"].remove(self.old[2].text)
        state, _ = self.reconcile(1)
        self.assertFalse(state["retained"])


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "demo", "url": "https://example.com/rules", "role": "secondary gap radar"}
        self.existing = {rules.Rule("DOMAIN-SUFFIX", "openai.com")}

    def test_covered_changes_are_silent_and_broad_non_domains_are_excluded(self):
        pending, summary = audit_sources.analyze(
            self.source,
            "DOMAIN,new.openai.com\nDOMAIN-SUFFIX,amazonaws.com\nPROCESS-NAME,ChatGPT",
            self.existing,
        )
        self.assertFalse(pending)
        self.assertEqual(summary["covered_count"], 1)
        self.assertEqual(summary["excluded_by_policy_count"], 2)

    def test_unknown_gap_remains_reported_without_persistent_baseline(self):
        first, _ = audit_sources.analyze(self.source, "DOMAIN,new.example.com", self.existing)
        second, _ = audit_sources.analyze(self.source, "DOMAIN,new.example.com", self.existing)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, second)

    def test_ignore_rules_are_radar_only_policy(self):
        source = dict(self.source, ignore_rules=["DOMAIN,new.example.com"])
        pending, summary = audit_sources.analyze(source, "DOMAIN,new.example.com", self.existing)
        self.assertFalse(pending)
        self.assertEqual(summary["excluded_by_policy_count"], 1)
        self.assertEqual(len(self.existing), 1)

    def test_section_allowlist_ignores_out_of_scope_products(self):
        source = dict(self.source, sections=["Keep"])
        pending, summary = audit_sources.analyze(
            source,
            "# >> Keep\nDOMAIN,new.example.com\n# >> Long Tail\nDOMAIN,ignored.example.net",
            self.existing,
        )
        self.assertEqual([row["rule"] for row in pending], ["DOMAIN,new.example.com"])
        self.assertEqual(pending[0]["section"], "Keep")
        self.assertEqual(summary["sections"], ["Keep"])

    def test_missing_expected_section_is_parser_drift(self):
        source = dict(self.source, sections=["Expected"])
        with self.assertRaisesRegex(ValueError, "sections changed"):
            audit_sources.analyze(source, "# >> Renamed\nDOMAIN,new.example.com", self.existing)

    def test_exact_host_does_not_cover_suffix_widening(self):
        self.assertFalse(audit_sources.covered(rules.Rule("DOMAIN-SUFFIX", "example.com"), {rules.Rule("DOMAIN", "example.com")}))


class ResilienceTests(unittest.TestCase):
    def test_voice_failure_retains_verified_last_good(self):
        with patch.object(sync, "fetch", side_effect=OSError("test outage")):
            payload, status = sync.fetch_voice(rules.ROOT)
        self.assertEqual(status, "retained-last-good")
        self.assertTrue(rules.voice_rules(json.loads(payload)))

    def test_voice_failure_without_valid_snapshot_fails(self):
        with tempfile.TemporaryDirectory() as td, patch.object(sync, "fetch", side_effect=OSError("test outage")):
            with self.assertRaises(OSError):
                sync.fetch_voice(Path(td))

    def test_transient_download_retried(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"valid"
        with patch.object(sync.urllib.request, "urlopen", side_effect=[OSError("transient"), response]) as fetch, patch.object(sync.time, "sleep"):
            self.assertEqual(sync.fetch("https://example.com"), b"valid")
            self.assertEqual(fetch.call_count, 2)

    def test_permanent_http_error_not_retried(self):
        error = urllib.error.HTTPError("https://example.com", 404, "missing", {}, None)
        try:
            with patch.object(sync.urllib.request, "urlopen", side_effect=error) as fetch:
                with self.assertRaises(urllib.error.HTTPError):
                    sync.fetch("https://example.com")
                self.assertEqual(fetch.call_count, 1)
        finally:
            error.close()

    def test_cli_import_identity_and_offline_reproducibility(self):
        result = subprocess.run([sys.executable, str(rules.ROOT / "scripts/rules.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.report = {"review_required": [{"vendor": "demo", "rule": "DOMAIN,new.test", "reason": "new-scope", "first_seen": "2026-01-01"}]}

    def test_clock_changes_do_not_change_issue_body(self):
        first = notify_review.issue_body("sync", self.report)
        self.report["review_required"][0]["first_seen"] = "2026-01-10"
        self.assertEqual(first, notify_review.issue_body("sync", self.report))

    def test_failed_workflow_without_report_is_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            report = notify_review.load_report(Path(td) / "missing.json", failed=True)
        self.assertEqual(report["review_required"], [{"reason": "workflow-failed"}])
        self.assertIn("本次工作流失败", notify_review.issue_body("sync", report))

    def test_failed_workflow_preserves_pending_findings(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            path.write_text(json.dumps(self.report), encoding="utf-8")
            report = notify_review.load_report(path, failed=True)
        self.assertEqual(len(report["review_required"]), 2)
        self.assertEqual(report["review_required"][0]["rule"], "DOMAIN,new.test")

    def test_missing_success_report_cannot_close_exception_issue(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OSError):
                notify_review.load_report(Path(td) / "missing.json")

    def test_invalid_failure_report_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(notify_review.load_report(path, failed=True)["review_required"], [{"reason": "workflow-failed"}])

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "NET86/rules"})
    def test_unchanged_issue_makes_no_writes(self):
        row = {"number": 1, "title": "[rules automation] sync exceptions", "body": notify_review.issue_body("sync", self.report), "state": "OPEN"}
        call = Mock(return_value=json.dumps([row]))
        notify_review.notify("sync", self.report, call)
        self.assertEqual(call.call_count, 1)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "NET86/rules"})
    def test_empty_report_does_not_create_issue(self):
        call = Mock(return_value="[]")
        notify_review.notify("sync", {"review_required": []}, call)
        self.assertEqual(call.call_count, 1)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/other-repo"})
    def test_wrong_owner_refused(self):
        with self.assertRaises(ValueError):
            notify_review.notify("sync", self.report, Mock())

    def test_notification_follows_evidence_upload(self):
        for workflow in ("sync", "audit"):
            text = (rules.ROOT / f".github/workflows/{workflow}.yml").read_text(encoding="utf-8")
            with self.subTest(workflow=workflow):
                self.assertLess(text.index("actions/upload-artifact@"), text.index("scripts/notify_review.py"))


class EngineHarnessTests(unittest.TestCase):
    def socket_context(self):
        context = Mock()
        connection = Mock()
        context.__enter__ = Mock(return_value=connection)
        context.__exit__ = Mock(return_value=False)
        return context, connection

    def test_proxy_listener_must_be_ready_separately_from_controller(self):
        context, _ = self.socket_context()
        with patch.object(verify_mihomo.socket, "create_connection", side_effect=[ConnectionRefusedError(), context]):
            self.assertFalse(verify_mihomo.proxy_ready(12345))
            self.assertTrue(verify_mihomo.proxy_ready(12345))

    def test_provider_readiness_tolerates_transient_null_state(self):
        names = ["one", "two"]
        self.assertFalse(verify_mihomo.providers_ready(None, names))
        self.assertFalse(verify_mihomo.providers_ready({}, names))
        self.assertFalse(verify_mihomo.providers_ready({"one": None, "two": {"ruleCount": 1}}, names))
        self.assertFalse(verify_mihomo.providers_ready({"one": {"ruleCount": 0}, "two": {"ruleCount": 1}}, names))
        self.assertTrue(verify_mihomo.providers_ready({"one": {"ruleCount": 1}, "two": {"ruleCount": 2}}, names))

    def test_fragmented_http_status_line_is_not_a_false_routing_failure(self):
        context, connection = self.socket_context()
        connection.recv.side_effect = [b"HTTP/1.", b"1 204 No Content\r", b"\nContent-Length: 0\r\n\r\n"]
        with patch.object(verify_mihomo.socket, "create_connection", return_value=context):
            self.assertTrue(verify_mihomo.probe(12345, "api.openai.com"))


if __name__ == "__main__":
    unittest.main()
