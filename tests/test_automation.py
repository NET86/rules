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
        self.direct = {"v2fly:data/demo"}
        self.catalog = {"vendors": [{"id": "demo", "group": "global", "sources": ["demo"]}]}
        self.patches = {"add": [], "drop": {}, "surge_regex": {}}
        self.policy = {"removal_grace_days": 14, "removal_min_observation_days": 3}
        self.contracts = {"vendors": {}}
        self.before = {"provenance": [automation.row_of(key, self.direct) for key in [self.stable, self.old]]}
        self.candidates = {self.stable: set(self.direct)}
        self.empty = {"schema": 1, "pending": [], "retained": []}

    def reconcile(self, day, state=None, **kwargs):
        return automation.reconcile(
            self.candidates, self.before, self.catalog, self.patches,
            state or self.empty, self.policy,
            today=date(2026, 1, day), contracts=self.contracts, **kwargs
        )

    def test_dedicated_source_new_root_is_accepted_automatically(self):
        new_root = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "unknown.test"))
        child = ("demo", "core", rules.Rule("DOMAIN", "new.example.com"))
        self.candidates.update({new_root: set(self.direct), child: set(self.direct)})
        state, report = self.reconcile(1)
        effective = automation.effective_entries(self.candidates, self.catalog, self.patches, state)
        self.assertIn(new_root, effective)
        self.assertIn(child, effective)
        self.assertEqual(report["quarantined_count"], 0)

    def test_transitive_include_does_not_inherit_dedicated_source_authority(self):
        key = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "included.example"))
        self.candidates[key] = {"v2fly:data/category-ai"}
        state, report = self.reconcile(1)
        self.assertEqual(report["review_required"][0]["reason"], "source-not-authorized-by-catalog")
        self.assertNotIn(key, automation.effective_entries(self.candidates, self.catalog, self.patches, state))

    def test_unknown_regex_quarantined_without_breaking_domains(self):
        key = ("demo", "core", rules.Rule("DOMAIN-REGEX", "^new.*$"))
        self.candidates[key] = set(self.direct)
        state, report = self.reconcile(1)
        self.assertEqual(report["review_required"][0]["reason"], "unreviewed-surge-regex-adapter")
        self.assertNotIn(key, automation.effective_entries(self.candidates, self.catalog, self.patches, state))

    def test_shared_root_cannot_enter_core_even_from_dedicated_source(self):
        key = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "amazonaws.com"))
        self.assertEqual(
            automation.scope_problem(key, self.direct, self.catalog, self.patches),
            "shared-platform-forbidden-in-core",
        )

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

    def test_vendor_outage_does_not_freeze_unrelated_retirement(self):
        other_stable = ("other", *self.stable[1:])
        other_old = ("other", *self.old[1:])
        other_origins = {"v2fly:data/other"}
        self.catalog["vendors"].append({"id": "other", "sources": ["other"]})
        self.candidates[other_stable] = other_origins
        self.before["provenance"].extend(automation.row_of(key, other_origins)
                                         for key in (other_stable, other_old))
        state, _ = self.reconcile(1)
        state, _ = self.reconcile(2, state)
        state, report = self.reconcile(20, state, unhealthy_vendors={"demo"})
        self.assertEqual([automation.key_of(row) for row in state["retained"]], [self.old])
        self.assertEqual(state["retained"][0]["observation_days"], ["2026-01-01", "2026-01-02"])
        self.assertEqual([automation.key_of(row) for row in report["automatically_removed"]], [other_old])
        self.assertEqual(report["deletion_observation_frozen_vendors"], ["demo"])

    def test_last_vendor_rule_is_retained(self):
        self.candidates = {}
        state, _ = self.reconcile(1)
        state, _ = self.reconcile(2, state)
        state, _ = self.reconcile(20, state)
        self.assertTrue(any(row["protected"] for row in state["retained"]))

    def test_reappearing_rule_resets_missing_state(self):
        state, _ = self.reconcile(1)
        self.candidates[self.old] = set(self.direct)
        state, _ = self.reconcile(2, state)
        self.assertEqual(state["retained"], [])

    def test_lossless_redundant_rule_removal_needs_no_delay(self):
        redundant = ("demo", "core", rules.Rule("DOMAIN", "old.example.com"))
        self.before["provenance"] = [automation.row_of(key, self.direct) for key in [self.stable, redundant]]
        state, report = self.reconcile(1)
        self.assertFalse(state["retained"])
        self.assertEqual(report["automatically_removed"][0]["reason"], "covered-by-current-rule")

    def test_local_drop_cannot_be_resurrected_by_retention(self):
        self.patches["drop"] = {"demo": {self.old[2].text: "local policy"}}
        state, report = self.reconcile(1)
        self.assertFalse(state["retained"])
        removed = next(row for row in report["automatically_removed"] if row["rule"] == self.old[2].text)
        self.assertEqual(removed["reason"], "local-policy-withdrawn")
        self.assertEqual(removed["policy_reason"], "locally-dropped-rule")


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "demo", "url": "https://example.com/rules", "role": "secondary gap radar", "vendor": "openai"}
        self.existing = {"openai": {rules.Rule("DOMAIN-SUFFIX", "openai.com")}}

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

    def test_enrichment_adds_cross_source_evidence_vendor_impact_and_gate(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "anthropic").write_text("full:new.example.com\n", encoding="utf-8")
            catalog = {
                "profiles": {
                    "ai-daily": {"members": ["claude"]},
                    "ai-core": {"members": ["claude"]},
                    "ai-cn": {"members": []},
                },
                "vendors": [{"id": "claude", "sources": ["anthropic"]}],
            }
            pending = [{
                "source_id": "sukka-source-ai", "source": "https://example.test/ai.conf",
                "section": "Claude", "rule": "DOMAIN,new.example.com",
                "reason": "uncovered-secondary-domain",
            }]
            official_state = {"documents": {"claude-network": {
                "vendor": "claude", "url": "https://example.test/official",
                "rules": ["DOMAIN,new.example.com"],
            }}}
            rows = audit_sources.enrich_pending(
                pending, catalog, {"add": [], "drop": {}, "surge_regex": {}}, official_state, data,
            )
        row = rows[0]
        self.assertEqual(row["vendor"], "claude")
        self.assertEqual(row["impact"], ["claude", "ai-daily", "ai-core"])
        self.assertTrue(row["evidence"]["v2fly"]["present"])
        self.assertEqual(row["evidence"]["v2fly"]["level"], "confirmed")
        self.assertEqual(row["evidence"]["official"]["level"], "confirmed")
        self.assertEqual(row["evidence"]["product_scope"]["status"], "in-scope")
        self.assertEqual(row["block_reason"], "radar-read-only")
        summary = audit_sources.format_review_item(row)
        self.assertIn("厂商：`claude`", summary)
        self.assertIn("V2Fly ✓ confirmed · anthropic", summary)
        self.assertIn("官方 confirmed · claude-network", summary)
        self.assertIn("若批准影响：claude / ai-daily / ai-core", summary)
        self.assertIn("主来源已收录", summary)

    def test_google_unselected_upstream_rule_is_explained_not_auto_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "google-deepmind").write_text("full:jules.google.com\n", encoding="utf-8")
            catalog = {
                "profiles": {
                    "ai-daily": {"members": ["google-ai"]},
                    "ai-core": {"members": ["google-ai"]},
                    "ai-cn": {"members": []},
                },
                "vendors": [{"id": "google-ai", "select": {"google-deepmind": ["gemini.google.com"]}}],
            }
            pending = [{
                "source_id": "sukka-source-ai", "source": "https://example.test/ai.conf",
                "section": "Google", "rule": "DOMAIN,jules.google.com",
                "reason": "uncovered-secondary-domain",
            }]
            rows = audit_sources.enrich_pending(
                pending, catalog, {"add": [], "drop": {}, "surge_regex": {}}, {"documents": {}}, data,
            )
        row = rows[0]
        self.assertTrue(row["evidence"]["v2fly"]["present"])
        self.assertEqual(row["evidence"]["product_scope"]["status"], "outside-explicit-select")
        self.assertEqual(row["block_reason"], "outside-explicit-product-select")

    def test_radar_evidence_scope_and_availability_do_not_grant_authority(self):
        cases = [
            ("full:new.example.com", "DOMAIN-SUFFIX", "related", "same-domain-different-scope"),
            ("full:api.new.example.com", "DOMAIN-SUFFIX", "related", "candidate-wider-than-evidence"),
            ("new.example.com", "DOMAIN", "confirmed", "evidence-covers-candidate"),
            (None, "DOMAIN", "unknown", None),
        ]
        for upstream, kind, level, relation in cases:
            with self.subTest(upstream=upstream), tempfile.TemporaryDirectory() as td:
                data = Path(td)
                if upstream:
                    (data / "anthropic").write_text(upstream + "\n", encoding="utf-8")
                catalog = {"profiles": {}, "vendors": [{"id": "claude", "sources": ["anthropic"]}]}
                row = audit_sources.enrich_pending(
                    [{"section": "Claude", "rule": kind + ",new.example.com"}], catalog,
                    {"add": [], "drop": {}, "surge_regex": {}}, {"documents": {}}, data,
                )[0]
                evidence = row["evidence"]["v2fly"]
                self.assertEqual(evidence["level"], level)
                self.assertEqual(evidence["status"], "available" if upstream else "unavailable")
                self.assertEqual(row["block_reason"], "primary-source-scope-mismatch" if upstream else "evidence-unavailable")
                self.assertEqual([match["relation"] for match in evidence["matches"]], [relation] if relation else [])
                self.assertIn("快照证据", audit_sources.format_review_item(row))

    def test_advertising_evidence_does_not_claim_it_will_be_published(self):
        for mode in ("sources", "select"):
            for ordinary in (False, True):
                with self.subTest(mode=mode, ordinary=ordinary), tempfile.TemporaryDirectory() as td:
                    data = Path(td)
                    text = "full:ads.example.com @ads\n" + ("full:ads.example.com\n" if ordinary else "")
                    (data / "demo").write_text(text, encoding="utf-8")
                    vendor = {"id": "demo", mode: ["demo"] if mode == "sources" else {"demo": ["ads.example.com"]}}
                    row = audit_sources.enrich_pending([{"vendor": "demo", "rule": "DOMAIN,ads.example.com"}],
                        {"vendors": [vendor], "profiles": {}}, {"add": [], "drop": {}, "surge_regex": {}},
                        {"documents": {}}, data)[0]
                    self.assertTrue(row["evidence"]["v2fly"]["present"])
                    self.assertEqual(row["evidence"]["v2fly"]["level"], "confirmed")
                    self.assertEqual(row["block_reason"], "radar-read-only" if ordinary else "upstream-advertising-excluded")
                    if not ordinary:
                        self.assertNotIn("等待规则同步", row["block_reason_label"])

    def test_actions_summary_lists_scan_counts_and_gap_details(self):
        report = {
            "review_required": [{
                "source_id": "sukka-source-ai",
                "section": "Claude",
                "rule": "DOMAIN-SUFFIX,newclaude.example",
                "reason": "uncovered-secondary-domain",
            }],
            "sources": {
                "sukka-source-ai": {
                    "active_line_count": 52,
                    "covered_count": 36,
                    "excluded_by_policy_count": 15,
                    "gap_count": 1,
                }
            },
        }
        text = audit_sources.render_actions_summary(report)
        self.assertIn("有效规则：**52**", text)
        self.assertIn("已覆盖：**36**", text)
        self.assertIn("策略排除：**15**", text)
        self.assertIn("待核验缺口：**1**", text)
        self.assertIn("`Claude` · `DOMAIN-SUFFIX,newclaude.example`", text)
        self.assertIn("仅供复核，不自动加入订阅", text)

    def test_actions_summary_caps_review_details(self):
        report = {
            "review_required": [
                {
                    "source_id": "sukka-source-ai",
                    "section": "OpenAI / ChatGPT",
                    "rule": f"DOMAIN,review-{index:02d}.example",
                    "reason": "uncovered-secondary-domain",
                }
                for index in range(12)
            ],
            "sources": {
                "sukka-source-ai": {
                    "active_line_count": 52,
                    "covered_count": 30,
                    "excluded_by_policy_count": 10,
                    "gap_count": 12,
                }
            },
        }
        text = audit_sources.render_actions_summary(report)
        self.assertIn("待审核 / 异常明细（12）", text)
        self.assertIn("review-09.example", text)
        self.assertNotIn("review-10.example", text)
        self.assertIn("另有 **2** 条，详见异常 Issue 或 source-audit.json。", text)


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

    def test_http_gzip_is_decoded_with_a_bound_and_archives_remain_raw(self):
        import gzip
        import io
        plain = b"official endpoint " * 100
        compressed = gzip.compress(plain)
        for encoding, payload, limit, expected in [
            ("gzip", compressed, len(plain), plain), ("", compressed, len(plain), compressed),
            ("gzip", compressed, 10, None), ("gzip", b"broken gzip", 100, None),
            ("gzip", compressed[:-5], len(plain) + 1, None),
            ("gzip", compressed[:10] + b"\x07" + compressed[-8:], len(plain) + 1, None),
        ]:
            with self.subTest(encoding=encoding, limit=limit):
                response = io.BytesIO(payload)
                response.headers = {"Content-Encoding": encoding}
                with patch.object(sync.urllib.request, "urlopen", return_value=response):
                    if expected is None:
                        with self.assertRaises((OSError, ValueError)):
                            sync.fetch("https://official.example", limit=limit, attempts=1)
                    else:
                        self.assertEqual(sync.fetch("https://official.example", limit=limit, attempts=1), expected)

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

    def test_disappeared_selection_keeps_each_domain_in_issue_and_summary(self):
        rows = [{"vendor": "demo", "source": "mixed", "value": value,
                 "reason": "selected-upstream-domain-disappeared-or-moved"}
                for value in ("first.example", "second.example")]
        body = notify_review.issue_body("sync", {"review_required": rows})
        import release
        for row in rows:
            self.assertIn(row["value"], body)
            self.assertIn(row["value"], release.format_review_item(row))
        self.assertNotEqual(body, notify_review.issue_body("sync", {"review_required": rows[:1]}))

    def test_clock_changes_do_not_change_issue_body(self):
        first = notify_review.issue_body("sync", self.report)
        self.report["review_required"][0]["first_seen"] = "2026-01-10"
        self.assertEqual(first, notify_review.issue_body("sync", self.report))

    def test_error_detail_is_visible_in_issue_body(self):
        report = {"review_required": [{
            "source_id": "openai-network",
            "reason": "official-source-unavailable-or-parser-drift",
            "error_type": "OSError",
            "error_detail": "Official HTTPS fallback failed: TimeoutError: handshake timed out",
        }]}
        body = notify_review.issue_body("sync", report)
        self.assertIn('"error_detail": "Official HTTPS fallback failed: TimeoutError: handshake timed out"', body)

    def test_failed_workflow_without_report_is_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            report = notify_review.load_report(Path(td) / "missing.json", failed=True)
        self.assertEqual(report["review_required"], [{"reason": "workflow-failed"}])
        self.assertIn("工作流失败", notify_review.issue_body("sync", report))

    def test_sources_issue_preserves_section_and_evidence(self):
        report = {"review_required": [{
            "source_id": "sukka-source-ai",
            "section": "Claude",
            "vendor": "claude",
            "rule": "DOMAIN,new.example",
            "reason": "uncovered-secondary-domain",
            "impact": ["claude", "ai-daily", "ai-core"],
            "evidence": {
                "v2fly": {"status": "available", "present": True, "level": "confirmed", "matches": []},
                "official": {"level": "none", "matches": []},
                "product_scope": {"status": "in-scope", "basis": "vendor-dedicated-v2fly-source"},
            },
            "block_reason": "source-not-authorized-by-catalog",
            "block_reason_label": "来源没有被当前 catalog 授权",
        }]}
        body = notify_review.issue_body("sources", report)
        self.assertIn("Sukka 补缺检查", body)
        self.assertIn('"section": "Claude"', body)
        self.assertIn('"rule": "DOMAIN,new.example"', body)
        self.assertIn('"impact": [', body)
        self.assertIn('"v2fly": {', body)
        self.assertIn('"block_reason": "source-not-authorized-by-catalog"', body)

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

    def test_large_exception_reports_are_bounded_without_hiding_state_changes(self):
        rows = [{"rule": f"DOMAIN,candidate-{i:04d}.example", "reason": "review", "error_detail": "detail" * 100}
                for i in range(500)]
        report = {"review_required": rows}
        body = notify_review.issue_body("sync", report)
        self.assertLess(len(body.encode("utf-8")), 60000)
        self.assertIn("完整报告", body)
        self.assertIn("SHA-256", body)
        self.assertEqual(body, notify_review.issue_body("sync", {"review_required": list(reversed(rows))}))
        rows[-1]["rule"] = "DOMAIN,candidate-9999.example"
        changed = notify_review.issue_body("sync", report)
        self.assertNotEqual(body, changed)
        self.assertEqual(body.split("```json\n")[1].split("\n```")[0],
                         changed.split("```json\n")[1].split("\n```")[0])
        huge = {"review_required": [{"reason": "review", "error_detail": "汉" * 100000}]}
        self.assertLess(len(notify_review.issue_body("sync", huge).encode("utf-8")), 60000)

    def test_invalid_report_rows_cannot_close_an_issue_or_hide_a_workflow_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            for row in (None, [], "text", {}, {"reason": None}, {"reason": ""}):
                with self.subTest(row=row):
                    path.write_text(json.dumps({"review_required": [row]}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        notify_review.load_report(path)
                    self.assertEqual(notify_review.load_report(path, failed=True)["review_required"],
                                     [{"reason": "workflow-failed"}])

    def test_invalid_failure_report_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(notify_review.load_report(path, failed=True)["review_required"], [{"reason": "workflow-failed"}])

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "NET86/rules"})
    def test_unchanged_open_issue_is_quiet_and_closed_issue_reopens(self):
        for state in ("OPEN", "CLOSED"):
            with self.subTest(state=state):
                row = {"number": 1, "title": "[rules automation] sync exceptions",
                       "body": notify_review.issue_body("sync", self.report), "state": state}
                call = Mock(return_value=json.dumps([row]))
                notify_review.notify("sync", self.report, call)
                self.assertEqual(call.call_count, 1 if state == "OPEN" else 2)
                if state == "CLOSED":
                    self.assertEqual(call.call_args.args,
                                     ("issue", "reopen", "1", "--repo", "NET86/rules"))

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
                self.assertLess(text.index("scripts/notify_review.py"), text.index("--summary-only"))
        for workflow, channel in (("ci", "ci"), ("sync", "sync"), ("audit", "sources"), ("dependency-automerge", "dependencies")):
            text = (rules.ROOT / f".github/workflows/{workflow}.yml").read_text(encoding="utf-8")
            self.assertIn(f"--summary-only {channel} --job-status ${{{{ job.status }}}}", text)


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
