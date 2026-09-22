import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import automation
import rules
import sync


class ParserTests(unittest.TestCase):
    def test_all_supported_v2fly_forms(self):
        rows = list(rules.parse_v2fly("example.com\nfull:API.example.com @ads # optional\ndomain:other.example.com\nregexp:^a\\.example\\.com$\n"))
        self.assertEqual(rows[0][0], rules.Rule("DOMAIN-SUFFIX", "example.com"))
        self.assertEqual(rows[1], (rules.Rule("DOMAIN", "api.example.com"), {"@ads"}))
        self.assertEqual(rows[3][0].kind, "DOMAIN-REGEX")

    def test_invalid_syntax_uses_the_source_failure_contract(self):
        for text in ("unknown:example.com", "regexp:[", "regexp:(?P<bad"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                list(rules.parse_v2fly(text))

    def test_filtered_include_not_silently_expanded(self):
        with self.assertRaises(ValueError):
            list(rules.parse_v2fly("include:example @cn"))

    def test_path_traversal_rejected(self):
        for value in ["include:../secrets", "include:/etc/passwd", "include:C:\\secret"]:
            with self.assertRaises(ValueError):
                list(rules.parse_v2fly(value))

    def test_include_cycle_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / "a").write_text("include:b")
            (path / "b").write_text("include:a")
            with self.assertRaises(ValueError):
                list(rules.load_source(path, "a"))

    def test_nested_include(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / "a").write_text("include:b")
            (path / "b").write_text("full:api.example.com @ads")
            result = list(rules.load_source(path, "a"))
            self.assertEqual(result, [(rules.Rule("DOMAIN", "api.example.com"), {"@ads"}, "b")])

    def test_select_mode_never_inherits_includes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / "category").write_text("include:child\nexplicit.example.com\n")
            (path / "child").write_text("hidden.example.com\n")
            self.assertEqual(
                list(rules.load_explicit_source(path, "category")),
                [(rules.Rule("DOMAIN-SUFFIX", "explicit.example.com"), set(), "category")],
            )
            catalog = {"vendors": [{"id": "demo", "group": "global", "select": {"category": ["hidden.example.com"]}}]}
            patches = {"add": [], "drop": {}}
            issues = []
            self.assertFalse(rules.collect(catalog, patches, path, review_mode=True, selection_issues=issues))
            self.assertEqual(issues[0]["reason"], "selected-upstream-domain-disappeared-or-moved")
            with self.assertRaisesRegex(ValueError, "moved behind include"):
                rules.collect(catalog, patches, path)

    def test_domain_suffix_boundaries(self):
        r = rules.Rule("DOMAIN-SUFFIX", "openai.com")
        for host in ["openai.com", "API.OPENAI.COM.", "a.b.openai.com"]:
            self.assertTrue(r.matches(host))
        for host in ["notopenai.com", "openai.com.evil.test", "openai-com.test"]:
            self.assertFalse(r.matches(host))

    def test_invalid_domain_and_injection(self):
        for value in ["DOMAIN,*.google.com", "DOMAIN,google.com,AI", "DOMAIN,foo\nbar.com", "DOMAIN,-foo.com", "IP-ASN,20473"]:
            with self.assertRaises(ValueError):
                rules.Rule.from_text(value)


class PolicyTests(unittest.TestCase):
    def test_direct_source_authority_does_not_flow_through_include(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "dedicated").write_text("direct.example\ninclude:child\n", encoding="utf-8")
            (data / "child").write_text("transitive.example\n", encoding="utf-8")
            catalog = {"vendors": [{"id": "demo", "group": "global", "sources": ["dedicated"]}]}
            patches = {"add": [], "drop": {}, "surge_regex": {}}
            entries = rules.collect(catalog, patches, data, review_mode=True)
        direct = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "direct.example"))
        transitive = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "transitive.example"))
        self.assertIsNone(automation.scope_problem(direct, entries[direct], catalog, patches))
        self.assertEqual(
            automation.scope_problem(transitive, entries[transitive], catalog, patches),
            "source-not-authorized-by-catalog",
        )

    def test_select_authorizes_only_explicit_selected_value(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "mixed").write_text("selected.example\nother.example\n", encoding="utf-8")
            catalog = {
                "vendors": [{
                    "id": "demo", "group": "global",
                    "select": {"mixed": ["selected.example"]},
                }]
            }
            patches = {"add": [], "drop": {}, "surge_regex": {}}
            entries = rules.collect(catalog, patches, data, review_mode=True)
        selected = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "selected.example"))
        self.assertEqual(set(entries), {selected})
        self.assertIsNone(automation.scope_problem(selected, entries[selected], catalog, patches))

    def test_select_preserves_rule_union_independent_of_order_and_exclusions(self):
        exact = "DOMAIN,selected.example"
        suffix = "DOMAIN-SUFFIX,selected.example"
        cases = [
            (["selected.example", "full:selected.example"], {}, {exact, suffix}),
            (["selected.example @ads", "full:selected.example"], {}, {exact}),
            (["selected.example", "full:selected.example @ads"], {}, {suffix}),
            (["selected.example", "full:selected.example"], {suffix: "reviewed"}, {exact}),
            (["full:selected.example", "full:selected.example @ads"], {}, {exact}),
        ]
        catalog = {"vendors": [{"id": "demo", "group": "global",
                                "select": {"mixed": ["selected.example"]}}]}
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            for lines, dropped, expected in cases:
                for order in (lines, list(reversed(lines))):
                    with self.subTest(order=order, dropped=dropped):
                        (data / "mixed").write_text("\n".join(order) + "\nother.example\n", encoding="utf-8")
                        patches = {"add": [], "drop": {"demo": dropped}, "surge_regex": {}}
                        entries = rules.collect(catalog, patches, data, review_mode=True)
                        self.assertEqual({key[2].text for key in entries}, expected)
                        self.assertTrue(all(automation.scope_problem(key, origins, catalog, patches) is None
                                            for key, origins in entries.items()))

    def test_whole_cloud_blocked_even_for_explicit_patch(self):
        catalog = {"vendors": [{"id": "test", "group": "global"}]}
        patch = {"add": [{"vendor": "test", "tier": "core", "rule": "DOMAIN-SUFFIX,amazonaws.com", "source": "https://example.com", "reason": "bad"}]}
        with self.assertRaises(ValueError):
            rules.collect(catalog, patch, Path("unused"))

    def test_profile_budget_blocks_automatic_expansion(self):
        catalog = {
            "vendors": [{"id": "global", "group": "global"}, {"id": "cn", "group": "cn"}],
            "profiles": {
                "ai-daily": {"budget": 0, "members": ["global"]},
                "ai-core": {"budget": 1, "members": ["global"]},
                "ai-cn": {"budget": 1, "members": ["cn"]},
            },
        }
        with self.assertRaisesRegex(ValueError, "budget"):
            rules.validate_profiles(catalog)


class VoiceTests(unittest.TestCase):
    def test_ipv4_ipv6(self):
        result = rules.voice_rules({"prefixes": [{"ipv4Prefix": "8.8.8.8/32"}, {"ipv6Prefix": "2606:4700::/48"}]})
        self.assertEqual(len(result), 2)
        self.assertIn(rules.Rule("IP-CIDR6", "2606:4700::/48"), result)

    def test_empty_invalid_private_or_overbroad_rejected(self):
        for payload in [{}, {"prefixes": []}, {"prefixes": [{"ipv4Prefix": "0.0.0.0/0"}]}, {"prefixes": [{"ipv4Prefix": "127.0.0.1/32"}]}, {"prefixes": [{"ipv6Prefix": "8.8.8.8/32"}]}, {"prefixes": [{"ipv4Prefix": "8.8.8.1/24"}]}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                rules.voice_rules(payload)


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = rules.compile_outputs(rules.ROOT)
        cls.manifest = json.loads(cls.files["rules/manifest.json"])

    def vendor_rules(self, vendor):
        return [rules.Rule.from_text(e["rule"]) for e in self.manifest["provenance"] if e["vendor"] == vendor and e["tier"] == "core"]

    def test_priority_service_coverage(self):
        cases = {
            "openai": ["api.openai.com", "auth.openai.com", "chatgpt.com", "files.oaiusercontent.com", "cdn.oaistatic.com", "ab.chatgpt.livekit.cloud", "openaiassets.blob.core.windows.net", "chatgpt-async-webps-prod-eastus-123.webpubsub.azure.com"],
            "claude": ["claude.ai", "platform.claude.com", "downloads.claude.ai", "bridge.claudeusercontent.com", "api.anthropic.com", "x.claudemcpcontent.com"],
            "grok": ["grok.com", "grok.x.com", "api.x.ai"],
            "perplexity": ["perplexity.ai", "perplexity.com", "api.pplx.ai", "ppl-ai-file-upload.s3.amazonaws.com"],
            "google-ai": ["gemini.google.com", "generativelanguage.googleapis.com", "aistudio.google.com", "notebooklm-pa.googleapis.com"],
            "cursor": ["api2.cursor.sh", "a.b.cursorvm.com"],
            "runway": ["app.runwayml.com", "runway.com"]
        }
        for vendor, hosts in cases.items():
            for host in hosts:
                with self.subTest(vendor=vendor, host=host):
                    self.assertTrue(any(r.matches(host) for r in self.vendor_rules(vendor)))

    def test_negative_shared_service_cases(self):
        all_core = [rules.Rule.from_text(e["rule"]) for e in self.manifest["provenance"] if e["tier"] == "core"]
        for host in ["api.stripe.com", "tenant.auth0.com", "unrelated.ingest.sentry.io", "storage.googleapis.com", "other-bucket.s3.amazonaws.com", "api.github.com", "www.google.com", "www.microsoft.com", "google.com", "example.livekit.cloud", "x.com", "openai.com.attacker.test"]:
            with self.subTest(host=host):
                self.assertFalse(any(r.matches(host) for r in all_core))

    def test_official_openaimerge_cdn_is_exact_not_whole_domain(self):
        entries = self.vendor_rules("openai")
        self.assertTrue(any(rule.matches("cdn.openaimerge.com") for rule in entries))
        for host in ["openaimerge.com", "unrelated.openaimerge.com", "sub.cdn.openaimerge.com", "cdn.openaimerge.com.attacker.test"]:
            self.assertFalse(any(rule.matches(host) for rule in entries), host)

    def test_regex_widening_is_recorded(self):
        self.assertEqual(len(self.manifest["conversion_warnings"]), 1)
        surge = self.files["rules/surge/openai.list"]
        self.assertIn("# 注意：此通配符比上游正则更宽", surge)
        self.assertNotIn("\nDOMAIN-REGEX,", surge)
        self.assertIn("DOMAIN-WILDCARD,chatgpt-async-webps-prod-*-*.webpubsub.azure.com", surge)
        self.assertIn("DOMAIN-REGEX,", self.files["rules/mihomo/openai.yaml"])

    def test_unreviewed_regex_fails(self):
        with self.assertRaises(ValueError):
            rules.render_rule(rules.Rule("DOMAIN-REGEX", "^new.*$"), "surge", {"surge_regex": {}})

    def test_cn_shared_dependencies_and_voice_not_in_core(self):
        core = self.files["rules/surge/ai-core.list"]
        for text in ["deepseek.com", "storage.googleapis.com", "IP-CIDR", "host.livekit.cloud", "turn.livekit.cloud"]:
            self.assertNotIn(text, core)
        self.assertIn("deepseek.com", self.files["rules/surge/ai-cn.list"])
        self.assertNotIn("claude-compat", self.manifest["bundles"])
        self.assertNotIn("ai-compat", self.manifest["bundles"])

    def test_surges_and_mihomo_equivalent_except_declared_adapter(self):
        for bundle in self.manifest["bundles"]:
            surge = {line for line in self.files[f"rules/surge/{bundle}.list"].splitlines() if line and not line.startswith("#")}
            mihomo = {json.loads(line[4:]) for line in self.files[f"rules/mihomo/{bundle}.yaml"].splitlines() if line.startswith("  - ")}
            mapped = set()
            for line in mihomo:
                if line.startswith("DOMAIN-REGEX,"):
                    mapped.add("DOMAIN-WILDCARD,chatgpt-async-webps-prod-*-*.webpubsub.azure.com")
                else:
                    mapped.add(line)
            self.assertEqual(surge, mapped, bundle)

    def test_all_generated_hashes_match(self):
        for bundle in self.manifest["bundles"].values():
            for data in bundle.values():
                self.assertEqual(rules.sha256(self.files[data["path"]].encode()), data["sha256"])

    def test_grouped_output_preserves_unique_rule_counts(self):
        for bundle in self.manifest["bundles"].values():
            for target, data in bundle.items():
                output = self.files[data["path"]]
                active = [line for line in output.splitlines() if line and not line.startswith("#")] if target == "surge" else [json.loads(line[4:]) for line in output.splitlines() if line.startswith("  - ")]
                self.assertEqual(len(active), len(set(active)))
                self.assertEqual(len(active), data["count"])
                comments = [line for line in output.splitlines() if line.lstrip().startswith("#")]
                self.assertLessEqual(len(comments), 24)
                self.assertNotIn("# Source:", output)
                self.assertNotIn("GNU AFFERO GENERAL PUBLIC LICENSE", output)

    def test_daily_names_only_explicit_members_and_manifest_provenance(self):
        daily = self.files["rules/surge/ai-daily.list"]
        catalog = rules.read_json(rules.ROOT / "sources/catalog.json")
        daily_members = set(catalog["profiles"]["ai-daily"]["members"])
        for vendor in catalog["vendors"]:
            self.assertEqual(f"# {vendor['name']}" in daily, vendor["id"] in daily_members)
        self.assertIn(" 语音", daily)
        self.assertNotIn("# Source:", daily)
        self.assertIn(rules.RAW_URL + "/rules/manifest.json", daily)
        daily_provenance = [row for row in self.manifest["provenance"] if row["vendor"] in daily_members]
        self.assertTrue(any("v2fly:data/openai" in source for row in daily_provenance for source in row["sources"]))

    def test_standalone_license_notices_are_compact(self):
        for target, ext in (("surge", "list"), ("mihomo", "yaml")):
            daily = self.files[f"rules/{target}/ai-daily.{ext}"]
            self.assertIn("# SPDX-License-Identifier: AGPL-3.0-only", daily)
            self.assertIn("THIRD_PARTY_NOTICES.md", daily)
            self.assertNotIn("Permission is hereby granted", daily)
            self.assertNotIn('THE SOFTWARE IS PROVIDED "AS IS"', daily)
            self.assertNotIn("GNU AFFERO GENERAL PUBLIC LICENSE", daily)
            voice = self.files[f"rules/{target}/openai-voice-ip.{ext}"]
            self.assertIn("# SPDX-License-Identifier: AGPL-3.0-only", voice)
            self.assertIn("THIRD_PARTY_NOTICES.md", voice)
            self.assertNotIn("GNU AFFERO GENERAL PUBLIC LICENSE", voice)

    def test_subscription_index_contains_every_bundle_link_once(self):
        index = self.files["rules/README.md"]
        for bundle in self.manifest["bundles"].values():
            for data in bundle.values():
                self.assertEqual(index.count(rules.RAW_URL + "/" + data["path"] + ")"), 1)
        self.assertLess(index.index("## 合集"), index.index("## 单厂商"))
        self.assertLess(index.index("## 单厂商"), index.index("## 可选功能包"))

    def test_duplicate_rule_keeps_vendor_attribution_without_source_noise(self):
        rule = rules.Rule("DOMAIN", "shared.example.com")
        members = {("one", "core", rule): {"https://one.example.com/"}, ("two", "core", rule): {"https://two.example.com/"}}
        catalog = {"vendors": [{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}]}
        body, count = rules.render_members(members, "surge", {}, catalog)
        self.assertEqual(count, 1)
        self.assertEqual(body.count(rule.text), 1)
        self.assertNotIn("Source:", body)

    def test_multiline_evidence_does_not_leak_into_subscription(self):
        key = ("one", "core", rules.Rule("DOMAIN", "old.example.com"))
        body, count = rules.render_members({key: {"https://source.example.com/\nDOMAIN,evil.example.com"}}, "surge", {}, {"vendors": [{"id": "one", "name": "One"}]})
        self.assertNotIn("evil.example.com", body)
        self.assertEqual(count, 1)

    def test_changed_license_rejected_even_with_valid_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            content = b"Changed upstream terms"
            (path / "V2FLY-LICENSE").write_bytes(content)
            (path / "lock.json").write_text(json.dumps({"v2fly_revision": "a" * 40, "sha256": {"V2FLY-LICENSE": rules.sha256(content)}}))
            with self.assertRaisesRegex(ValueError, "license changed"):
                rules.verify_snapshot(path)

    def test_reproducible(self):
        self.assertEqual(self.files, rules.compile_outputs(rules.ROOT))

    def test_profiles_are_explicit_and_daily_is_not_core_alias(self):
        def lines(name):
            return {line for line in self.files[f"rules/surge/{name}.list"].splitlines() if line and not line.startswith("#")}
        profiles = self.manifest["profiles"]
        self.assertEqual(len(profiles["ai-daily"]["members"]), 5)
        self.assertEqual(len(profiles["ai-core"]["members"]), 14)
        self.assertEqual(len(profiles["ai-cn"]["members"]), 10)
        self.assertTrue(set(profiles["ai-daily"]["members"]).issubset(profiles["ai-core"]["members"]))
        self.assertNotEqual(lines("ai-daily"), lines("ai-core") | lines("openai-voice-ip"))
        self.assertTrue(lines("ai-daily").isdisjoint(lines("ai-cn")))
        self.assertEqual(self.manifest["profile_features"], {"ai-daily": ["openai-voice-ip"]})

    def test_snapshot_tampering_fails(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / "data").write_text("changed")
            (path / "lock.json").write_text(json.dumps({"v2fly_revision": "a" * 40, "sha256": {"data": "wrong"}}))
            with self.assertRaises(ValueError):
                rules.verify_snapshot(path)


if __name__ == "__main__":
    unittest.main()
