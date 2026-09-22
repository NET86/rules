"""Executable counterexamples for retirement, source health, radar and runtime evidence."""
import copy
import ipaddress
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_sources
import automation
import intake
import notify_review
import release
import rules
import sync
import verify_mihomo


def voice(*values):
    return {"prefixes": [{"ipv6Prefix" if ":" in value else "ipv4Prefix": value} for value in values]}


class RetirementContractTests(unittest.TestCase):
    def reconcile(self, extra=None, member=True):
        stable = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "service.io"))
        disappearing = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "service.com"))
        entries = {stable: {"v2fly:data/demo"}}
        before = {"provenance": [automation.row_of(key, {"v2fly:data/demo"})
                                  for key in (stable, disappearing)]}
        catalog = {"vendors": [{"id": "demo", "sources": ["demo"]},
                               {"id": "other", "sources": ["other"]}],
                   "profiles": {"ai-core": {"members": ["demo", "other"] if member else ["other"]}}}
        if extra:
            entries[("other", "core", extra)] = {"v2fly:data/other"}
        state, report = automation.reconcile(
            entries, before, catalog, {"add": [], "drop": {}, "surge_regex": {}}, {},
            {"removal_grace_days": 14, "removal_min_observation_days": 3},
            today=date(2026, 9, 22), allow_removals=True,
            contracts={"vendors": {"demo": {"must_match": ["service.io"]}},
                       "profiles": {"ai-core": {"must_match": ["service.com"]}}},
        )
        return state, report

    def test_profile_only_key_host_cannot_be_retired(self):
        state, report = self.reconcile()
        self.assertTrue(state["retained"][0]["protected"])
        self.assertEqual(report["review_required"][0]["reason"], "protected-upstream-removal")

    def test_profile_protection_allows_real_replacement_coverage(self):
        state, report = self.reconcile(rules.Rule("DOMAIN-SUFFIX", "service.com"))
        self.assertFalse(state["retained"])
        self.assertEqual(report["automatically_removed"][0]["reason"], "confirmed-upstream-removal")

    def test_unrelated_profile_does_not_pin_vendor_rule(self):
        state, _ = self.reconcile(member=False)
        self.assertFalse(state["retained"])


class AdditionalBoundaryTests(unittest.TestCase):
    def test_withdrawn_coverage_cannot_mask_a_profile_retirement(self):
        keep = ("demo", "core", rules.Rule("DOMAIN", "service.io"))
        missing = ("demo", "core", rules.Rule("DOMAIN", "service.com"))
        withdrawn = ("other", "core", rules.Rule("DOMAIN", "service.com"))
        before = {"provenance": [automation.row_of(key, {f"v2fly:data/{key[0]}"})
                                  for key in (keep, missing, withdrawn)]}
        catalog = {"vendors": [{"id": name, "sources": [name]} for name in ("demo", "other")],
                   "profiles": {"ai-core": {"members": ["demo", "other"]}}}
        state, _ = automation.reconcile(
            {keep: {"v2fly:data/demo"}}, before, catalog,
            {"add": [], "drop": {"other": {withdrawn[2].text: "Reviewed exclusion"}}, "surge_regex": {}},
            {}, {"removal_grace_days": 14, "removal_min_observation_days": 3}, allow_removals=True,
            contracts={"vendors": {"demo": {"must_match": ["service.io"]}},
                       "profiles": {"ai-core": {"must_match": ["service.com"]}}},
        )
        self.assertTrue(any(automation.key_of(row) == missing and row["protected"] for row in state["retained"]))
        self.assertFalse(any(automation.key_of(row) == withdrawn for row in state["retained"]))

    def test_radar_drop_is_exact_and_vendor_scoped(self):
        source = {"id": "radar", "url": "https://example/rules", "role": "secondary",
                  "sections": ["OpenAI / ChatGPT", "Claude"]}
        content = "# >> OpenAI / ChatGPT\nDOMAIN,shared-product.net\n# >> Claude\nDOMAIN,shared-product.net\n"
        pending, report = audit_sources.analyze(source, content, {},
            {"claude": {"DOMAIN,shared-product.net": "Reviewed exclusion"}})
        self.assertEqual([(row["vendor"], row["rule"]) for row in pending], [("openai", "DOMAIN,shared-product.net")])
        self.assertEqual(report["excluded_by_policy_count"], 1)

    def test_fourfold_voice_boundary_and_exact_half_retention(self):
        before = voice("8.8.8.1/32")
        self.assertIsNone(sync.voice_change_problem(before, voice(*(f"8.8.8.{n}/32" for n in range(1, 5)))))
        self.assertIn("expanded", sync.voice_change_problem(before, voice(*(f"8.8.8.{n}/32" for n in range(1, 6)))))
        self.assertIsNone(sync.voice_change_problem(voice("8.8.8.0/30"), voice("8.8.8.0/31")))

    def test_source_issue_does_not_tell_maintainers_to_add_every_candidate(self):
        body = notify_review.issue_body("sources", {"review_required": [{"reason": "source-unavailable"}]})
        self.assertIn("候选或来源异常需要复核", body)
        self.assertNotIn("需审核后补入", body)


class SourceInputTests(unittest.TestCase):
    def test_invalid_voice_json_types_are_format_errors(self):
        for payload in (None, [], {"prefixes": None}, {"prefixes": [None]},
                        {"prefixes": [1]}, {"prefixes": [["ipv4Prefix"]]},
                        {"prefixes": [{"ipv4Prefix": None}]},
                        {"prefixes": [{"ipv4Prefix": 134744072}]},
                        {"prefixes": [{"ipv4Prefix": []}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                rules.voice_rules(payload)

    def test_malformed_voice_keeps_verified_baseline(self):
        expected = (rules.ROOT / "sources/snapshot/openai-voice.json").read_bytes()
        with patch.object(sync, "fetch", return_value=b'{"prefixes":[null]}'):
            payload, status = sync.fetch_voice(rules.ROOT)
        self.assertEqual(status, "retained-last-good")
        self.assertEqual(payload, expected)

    @staticmethod
    def discovery():
        return {"name": "generativelanguage", "kind": "discovery#restDescription",
                "rootUrl": "https://generativelanguage.googleapis.com/"}

    def test_bad_discovery_source_does_not_stop_other_sources(self):
        for baseline in (True, False):
            with self.subTest(baseline=baseline), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / "sources").mkdir()
                bad = {"id": "bad", "vendor": "google-ai", "format": "discovery",
                       "url": "https://bad.example/api", "min_hosts": 1,
                       "required_hosts": ["generativelanguage.googleapis.com"]}
                good = dict(bad, id="good", url="https://good.example/api")
                document = intake.extract_document(bad, json.dumps(self.discovery()).encode())
                state = {"schema": 1, "documents": {"bad": document} if baseline else {}}
                (root / "sources/official.json").write_text(json.dumps({"sources": [bad, good]}))
                (root / "sources/official-state.json").write_text(json.dumps(state))
                def fetch(url):
                    return b"[]" if url == bad["url"] else json.dumps(self.discovery()).encode()
                updated, report = intake.refresh_official(root, fetch)
                self.assertEqual(report["sources"]["bad"]["status"],
                                 "retained-last-good" if baseline else "unavailable-no-baseline")
                self.assertEqual(report["sources"]["good"]["status"], "fresh")
                self.assertEqual(report["review_required"][0]["error_type"], "ValueError")
                self.assertEqual(updated["documents"].get("bad"), state["documents"].get("bad"))
                self.assertEqual(rules.read_json(root / "sources/official-state.json"), state)

    def test_discovery_url_fields_cannot_smuggle_non_string_domains(self):
        source = {"id": "discovery", "vendor": "google-ai", "url": "https://example/api",
                  "format": "discovery", "min_hosts": 1,
                  "required_hosts": ["generativelanguage.googleapis.com"]}
        for value in (None, 123, ["https://generativelanguage.googleapis.com/"],
                      {"url": "https://generativelanguage.googleapis.com/"}):
            doc = self.discovery()
            doc["baseUrl"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                intake.extract_document(source, json.dumps(doc).encode())


class VoiceBoundaryTests(unittest.TestCase):
    def test_multicast_and_special_addresses_are_not_voice_unicast(self):
        for value in ("224.0.0.0/24", "239.1.1.1/32", "ff00::/32", "240.0.0.0/16",
                      "127.0.0.1/32", "169.254.1.1/32", "::/128", "fe80::/64"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rules.voice_rules(voice(value))
        self.assertEqual(len(rules.voice_rules(voice("8.8.8.8/32", "2606:4700::/48"))), 2)

    def test_23_hosts_plus_a_24_requires_review(self):
        before = voice(*(f"8.8.8.{index}/32" for index in range(1, 24)))
        after = copy.deepcopy(before)
        after["prefixes"].append({"ipv4Prefix": "8.8.4.0/24"})
        self.assertIn("expanded", sync.voice_change_problem(before, after))

    def test_small_list_total_or_majority_replacement_requires_review(self):
        before = voice("8.8.8.1/32", "8.8.8.2/32", "8.8.8.3/32")
        for after in (voice("8.8.4.1/32", "8.8.4.2/32", "8.8.4.3/32"),
                      voice("8.8.8.1/32", "8.8.4.2/32", "8.8.4.3/32")):
            with self.subTest(after=after):
                self.assertIsNotNone(sync.voice_change_problem(before, after))

    def test_small_hole_in_large_range_is_not_a_total_replacement(self):
        before = voice("8.8.8.0/24")
        remaining = ipaddress.ip_network("8.8.8.0/24").address_exclude(ipaddress.ip_network("8.8.8.8/32"))
        self.assertIsNone(sync.voice_change_problem(before, voice(*(str(net) for net in remaining))))


class OfficialDecisionTests(unittest.TestCase):
    def test_explicit_vendor_drop_is_a_decision_not_a_new_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            source = {"id": "claude-test", "vendor": "claude", "url": "https://example/api"}
            rule = "DOMAIN,reviewed-claude-endpoint.net"
            for name, value in {
                "official.json": {"sources": [source]},
                "intake-policy.json": rules.read_json(rules.ROOT / "sources/intake-policy.json"),
                "patches.json": {"drop": {"claude": {rule: "Reviewed outside product scope"}}},
            }.items():
                (root / "sources" / name).write_text(json.dumps(value), encoding="utf-8")
            state = {"documents": {source["id"]: dict(source, rules=[rule])}}
            before = copy.deepcopy(state)
            report = intake.analyze_official(root, state, [])
            self.assertEqual(report["review_required"], [])
            self.assertEqual(report["decisions"][0]["action"], "excluded-local-policy")
            self.assertEqual(state, before)
            source["vendor"] = "openai"
            (root / "sources/official.json").write_text(json.dumps({"sources": [source]}))
            state["documents"][source["id"]]["vendor"] = "openai"
            self.assertEqual(len(intake.analyze_official(root, state, [])["review_required"]), 1)


class RadarAttributionTests(unittest.TestCase):
    source = {"id": "radar", "url": "https://example/rules", "role": "secondary",
              "sections": ["OpenAI / ChatGPT", "Claude"]}
    content = "# >> OpenAI / ChatGPT\nDOMAIN,shared-product.net\n# >> Claude\nDOMAIN,shared-product.net\n"

    def test_coverage_in_another_vendor_cannot_hide_a_gap(self):
        pending, summary = audit_sources.analyze(
            self.source, self.content, {"openai": {rules.Rule("DOMAIN", "shared-product.net")}})
        self.assertEqual([(row["section"], row["vendor"]) for row in pending], [("Claude", "claude")])
        self.assertEqual(summary["covered_count"], 1)

    def test_same_domain_in_two_sections_keeps_both_attributions(self):
        pending, summary = audit_sources.analyze(self.source, self.content, {})
        self.assertEqual({row["section"] for row in pending}, {"OpenAI / ChatGPT", "Claude"})
        self.assertEqual(summary["gap_count"], 2)

    def test_official_confirmation_cannot_be_labelled_secondary_only(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "anthropic").write_text("claude.ai\n")
            catalog = {"vendors": [{"id": "claude", "sources": ["anthropic"]}], "profiles": {}}
            rows = audit_sources.enrich_pending(
                [{"rule": "DOMAIN,shared-product.net", "section": "Claude"}], catalog,
                {"add": [], "drop": {}, "surge_regex": {}},
                {"documents": {"official": {"vendor": "claude", "url": "https://example/official",
                                             "rules": ["DOMAIN,shared-product.net"]}}}, data)
        self.assertEqual(rows[0]["evidence"]["official"]["level"], "confirmed")
        self.assertEqual(rows[0]["block_reason"], "primary-source-absent")
        self.assertNotIn("仅 Sukka", rows[0]["block_reason_label"])


class ReportingTests(unittest.TestCase):
    def test_voice_only_change_is_visible_even_when_count_is_unchanged(self):
        before = {"provenance": [], "bundles": {"openai-voice-ip": {
            "mihomo": {"sha256": "old", "count": 23}, "surge": {"sha256": "old", "count": 23}}}}
        after = copy.deepcopy(before)
        after["bundles"]["openai-voice-ip"]["mihomo"]["sha256"] = "new"
        after["bundles"]["openai-voice-ip"]["surge"]["sha256"] = "new"
        text = release.render_actions_summary(before, after, {}, {"result": "PASS"})
        self.assertIn("openai-voice-ip", text)
        self.assertNotIn("### 规则变化\n- 无变化", text)
        self.assertIn("23 → 23", text)

    def test_retained_source_summary_does_not_assert_download_failure(self):
        report = {"source_health": {"official_facts": {"openai-network": {
            "status": "retained-last-good", "error_type": "ValueError"}}}}
        text = release.render_actions_summary({}, {}, report, {})
        self.assertNotIn("沿用旧版（抓取失败）", text)

    def test_no_baseline_issue_does_not_claim_a_valid_baseline_exists(self):
        body = notify_review.issue_body("sync", {"review_required": [{
            "source_id": "new-source", "reason": "official-source-unavailable-or-parser-drift",
            "status": "unavailable-no-baseline", "error_type": "ValueError"}]})
        self.assertIn("无有效基线", body)
        self.assertNotIn("异常来源沿用有效基线。", body)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "NET86/rules"})
    def test_recovery_closes_issue_only_with_an_empty_exception_report(self):
        existing = {"number": 1, "title": "[rules automation] sync exceptions", "state": "OPEN",
                    "body": notify_review.issue_body("sync", {"review_required": [{"reason": "outage"}]})}
        call = Mock(side_effect=[json.dumps([existing]), ""])
        notify_review.notify("sync", {"review_required": []}, call)
        self.assertEqual(call.call_args.args, ("issue", "close", "1", "--repo", "NET86/rules", "--reason", "completed"))


class RuntimeEvidenceTests(unittest.TestCase):
    @staticmethod
    def socket_context(response):
        connection = Mock()
        connection.recv.return_value = response
        context = Mock()
        context.__enter__ = Mock(return_value=connection)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_connection_failures_are_not_negative_routing_success(self):
        for error in (TimeoutError("timeout"), ConnectionRefusedError("refused"), OSError("socket failed")):
            with self.subTest(error=error), patch.object(verify_mihomo.socket, "create_connection", side_effect=error):
                with self.assertRaises((OSError, RuntimeError)):
                    verify_mihomo.probe(12345, "unmatched.test")

    def test_only_explicit_local_outlet_statuses_are_classified(self):
        for response, expected in ((b"HTTP/1.1 204 No Content\r\n", True),
                                   (b"HTTP/1.1 418 Non-Matching Outlet\r\n", False)):
            with patch.object(verify_mihomo.socket, "create_connection", return_value=self.socket_context(response)):
                self.assertEqual(verify_mihomo.probe(12345, "unmatched.test"), expected)
        for response in (b"", b"HTTP/1.1 502 Bad Gateway\r\n", b"not an HTTP response\r\n"):
            with self.subTest(response=response), patch.object(
                    verify_mihomo.socket, "create_connection", return_value=self.socket_context(response)):
                with self.assertRaises(RuntimeError):
                    verify_mihomo.probe(12345, "unmatched.test")


if __name__ == "__main__":
    unittest.main()
