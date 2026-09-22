import copy
import json
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import intake
import release
import rules
import verify_rules


class IntakeTests(unittest.TestCase):
    def test_visible_sections_drop_scripts_navigation_and_nested_headings(self):
        page = '<nav>bad.test</nav><h2><div>Network <span>access</span></div></h2><p>*.api.example.com</p><script>evil.test</script><h2>Other</h2>outside.test'
        text = intake.visible_sections(page, ["Network access"])
        self.assertIn("*.api.example.com", text)
        for excluded in ("bad.test", "evil.test", "outside.test"):
            self.assertNotIn(excluded, text)

    def test_missing_section_fails_closed(self):
        with self.assertRaises(ValueError):
            intake.visible_sections("<h2>Changed title</h2>api.test", ["Network"])

    def test_official_shape_guard(self):
        source = {"id": "fixture", "url": "https://official.test", "vendor": "fixture",
                  "format": "html", "sections": ["Network"], "required_hosts": ["api.example.com"], "min_hosts": 1}
        doc = intake.extract_document(source, b"<h2>Network</h2><p>*.api.example.com and config.json</p>")
        self.assertEqual(doc["rules"], ["DOMAIN-SUFFIX,api.example.com"])
        with self.assertRaises(ValueError):
            intake.extract_document(source, b"<h2>Network</h2><p>access denied</p>")

    def test_api_documents_are_limited_to_network_sections(self):
        sources = {row["id"]: row for row in rules.read_json(rules.ROOT / "sources/official.json")["sources"]}
        cases = [
            ("hunyuan-regions", "1. 服务地址", "hunyuan.tencentcloudapi.com", "hunyuan.ap-guangzhou.tencentcloudapi.com"),
            ("spark-http", "# 2.1 语言模型", "spark-api-open.xf-yun.com", "spark-api-open.xf-yun.com"),
        ]
        for source_id, heading, first, second in cases:
            with self.subTest(source=source_id):
                payload = (f"<h2>{heading}</h2><p>https://{first}/v1 https://{second}/v1</p>"
                           "<h2>Code examples</h2><p>client.chat.completions.create example.org</p>").encode()
                doc = intake.extract_document(sources[source_id], payload)
                self.assertEqual(set(doc["rules"]), {"DOMAIN," + first, "DOMAIN," + second})
                with self.assertRaises(ValueError):
                    intake.extract_document(sources[source_id], b"<h2>Renamed</h2><p>access denied</p>")

    def test_google_discovery_identity_and_endpoints(self):
        source = next(s for s in rules.read_json(rules.ROOT / "sources/official.json")["sources"] if s["format"] == "discovery")
        doc = {"name": "generativelanguage", "kind": "discovery#restDescription",
               "rootUrl": "https://generativelanguage.googleapis.com/", "mtlsRootUrl": "https://generativelanguage.mtls.googleapis.com/"}
        self.assertEqual(len(intake.extract_document(source, json.dumps(doc).encode())["rules"]), 2)
        doc["name"] = "wrong-api"
        with self.assertRaises(ValueError):
            intake.extract_document(source, json.dumps(doc).encode())

    def test_partial_host_wildcards_never_become_parent_domains(self):
        source = {"id": "fixture", "url": "https://official.test", "vendor": "fixture",
                  "format": "html", "sections": ["Network"],
                  "required_hosts": ["githubcopilot.com"], "min_hosts": 1}
        page = b"""<h2>Network</h2><p>https://*.githubcopilot.com/*
            https://copilot-reports-*.b01.azurefd.net
            https://usagereports*.blob.core.windows.net
            https://api.*.example.com https://api.example.net*</p>"""
        self.assertEqual(intake.extract_document(source, page)["rules"],
                         ["DOMAIN-SUFFIX,githubcopilot.com"])

    def test_copilot_radar_filters_shared_services_without_hiding_new_exact_hosts(self):
        source = next(s for s in rules.read_json(rules.ROOT / "sources/official.json")["sources"]
                      if s["id"] == "github-copilot-network")
        page = b"""<h2>Copilot on GitHub.com</h2><p>unselected.github.com</p>
            <h3>Specific required domains</h3><table><tr><td>
            https://*.githubcopilot.com/* https://*.business.githubcopilot.com
            https://copilot-proxy.githubusercontent.com
            https://origin-tracker.githubusercontent.com
            https://new-copilot-service.githubusercontent.com
            https://api.github.com/user https://github.com/login/* *.github.com
            https://avatars.githubusercontent.com *.githubusercontent.com
            https://github.githubassets.com *.githubassets.com
            https://collector.github.com https://copilot-telemetry.githubusercontent.com
            https://default.exp-tas.com https://copilot-reports.github.com
            https://copilot-reports-*.b01.azurefd.net
            https://usagereports*.blob.core.windows.net
            </td></tr></table>
            <h2>Copilot on GHE.com</h2><p>*.SUBDOMAIN.ghe.com</p>
            <h2>Editor-specific requirements</h2><p>vscode.dev</p>
            <h2>Copilot voice features</h2><p>*.api.azureml.ms</p>
            <h2>Copilot cloud agent recommended allowlist</h2>
            <h3>Container Registries</h3><p>*.docker.io</p>"""
        doc = intake.extract_document(source, page)
        production = {
            ("github-copilot", "core", rules.Rule("DOMAIN-SUFFIX", "githubcopilot.com")): {"v2fly"},
            ("github-copilot", "core", rules.Rule("DOMAIN", "copilot-proxy.githubusercontent.com")): {"v2fly"},
        }
        before = copy.deepcopy(production)
        report = intake.analyze_official(rules.ROOT, {"documents": {source["id"]: doc}}, production)
        self.assertEqual(production, before)
        self.assertEqual({row["rule"] for row in report["review_required"]}, {
            "DOMAIN,origin-tracker.githubusercontent.com",
            "DOMAIN,new-copilot-service.githubusercontent.com",
        })
        self.assertEqual({row["rule"] for row in report["decisions"] if row["action"] == "already-covered"}, {
            "DOMAIN-SUFFIX,githubcopilot.com", "DOMAIN-SUFFIX,business.githubcopilot.com",
            "DOMAIN,copilot-proxy.githubusercontent.com",
        })
        for outside in ("unselected.github.com", "subdomain.ghe.com", "vscode.dev", "api.azureml.ms",
                        "docker.io", "b01.azurefd.net", "blob.core.windows.net"):
            self.assertFalse(any(rules.Rule.from_text(text).value == outside for text in doc["rules"]), outside)

    def test_copilot_document_drift_retains_last_good_facts(self):
        source = next(s for s in rules.read_json(rules.ROOT / "sources/official.json")["sources"]
                      if s["id"] == "github-copilot-network")
        baseline = rules.read_json(rules.ROOT / "sources/official-state.json")["documents"][source["id"]]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            before = {"schema": 1, "documents": {source["id"]: baseline}}
            (root / "sources/official.json").write_text(json.dumps({"sources": [source]}))
            (root / "sources/official-state.json").write_text(json.dumps(before))
            for payload in (b"<h3>Renamed requirements</h3><p>githubcopilot.com</p>",
                            b"<h3>Specific required domains</h3><p>Access denied</p>"):
                with self.subTest(payload=payload):
                    after, report = intake.refresh_official(root, lambda url: payload)
                    self.assertEqual(after, before)
                    self.assertEqual(report["sources"][source["id"]]["status"], "retained-last-good")
                    self.assertEqual(report["review_required"][0]["source_id"], source["id"])

    def test_official_analysis_never_mutates_production_entries(self):
        production = {
            ("demo", "core", rules.Rule("DOMAIN-SUFFIX", "example.com")): {"v2fly"},
        }
        state = {
            "documents": {
                "fixture": {
                    "url": "https://official.test",
                    "vendor": "demo",
                    "rules": ["DOMAIN,api.example.com", "DOMAIN,new.example.net"],
                }
            }
        }
        config = {
            "schema": 1,
            "sources": [{"id": "fixture", "url": "https://official.test", "vendor": "demo"}],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            (root / "sources/intake-policy.json").write_text(json.dumps({
                "official_exclude_suffixes": {}, "official_shared_suffixes": {}, "official_exclude_exact": {}
            }))
            (root / "sources/official.json").write_text(json.dumps(config))
            (root / "sources/patches.json").write_text(json.dumps({"drop": {}}))
            before = copy.deepcopy(production)
            report = intake.analyze_official(root, state, production)
        self.assertEqual(production, before)
        self.assertEqual(report["decisions"][0]["action"], "already-covered")
        self.assertEqual(report["review_required"][0]["reason"], "official-uncovered-domain")

    def test_only_valid_current_source_documents_can_be_last_good(self):
        source = {"id": "fixture", "url": "https://official.test/network", "vendor": "demo",
                  "format": "html", "sections": ["Network"], "required_hosts": ["api.example.com"], "min_hosts": 1}
        payload = b"<h2>Network</h2><p>api.example.com</p>"
        valid = intake.extract_document(source, payload)
        invalid = [None, {}, dict(valid, vendor="other"), dict(valid, url="https://old.test"),
                   dict(valid, rules=[]), dict(valid, rules=[None]), dict(valid, rules=["DOMAIN,wrong.example"]),
                   dict(valid, rules=["IP-CIDR,8.8.8.8/32"]), dict(valid, document_sha256="bad")]
        def offline(url):
            raise OSError("offline")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            other = dict(source, id="healthy", url="https://healthy.test/network")
            (root / "sources/official.json").write_text(json.dumps({"sources": [source, other]}))
            for old in [valid, *invalid]:
                for recover in (False, True):
                    with self.subTest(old=old, recover=recover):
                        state = {"schema": 1, "documents": {"fixture": old, "removed-source": valid}}
                        path = root / "sources/official-state.json"
                        path.write_text(json.dumps(state))
                        def fetch(url):
                            return payload if recover or url == other["url"] else offline(url)
                        after, report = intake.refresh_official(root, fetch)
                        expected = "fresh" if recover else ("retained-last-good" if old == valid else "unavailable-no-baseline")
                        self.assertEqual(report["sources"]["fixture"]["status"], expected)
                        self.assertEqual(report["sources"]["healthy"]["status"], "fresh")
                        self.assertNotIn("removed-source", after["documents"])
                        self.assertEqual("fixture" in after["documents"], recover or old == valid)
                        self.assertEqual(rules.read_json(path), state)

    def test_patch_evidence_loss_is_visible_without_revoking_authority(self):
        source = {"id": "fixture", "url": "https://official.test/network", "vendor": "demo"}
        exact = "DOMAIN,tenant.shared.example"
        broad = "DOMAIN-SUFFIX,tenant.shared.example"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            docs = {
                "official.json": {"sources": [source]},
                "intake-policy.json": {"official_exclude_exact": {"shared.example": "Shared namespace"},
                                       "official_exclude_suffixes": {}, "official_shared_suffixes": {}},
                "patches.json": {"add": [{"vendor": "demo", "tier": "core", "rule": rule,
                                          "source": source["url"], "reason": "Reviewed"} for rule in (exact, broad)], "drop": {}}
            }
            for name, data in docs.items():
                (root / "sources" / name).write_text(json.dumps(data))
            production = {("demo", "core", rules.Rule.from_text(rule)): {source["url"]} for rule in (exact, broad)}
            before = copy.deepcopy(production)
            for facts, expected in [([exact], [broad]), ([broad], []),
                                    (["DOMAIN-SUFFIX,shared.example"], [exact, broad]), ([], [exact, broad])]:
                with self.subTest(facts=facts):
                    report = intake.analyze_official(root, {"documents": {"fixture": dict(source, rules=facts)}}, production)
                    missing = [row["rule"] for row in report["review_required"] if row["reason"] == "official-patch-evidence-missing"]
                    self.assertEqual(sorted(missing), sorted(expected))
                    self.assertEqual(production, before)
            # Withdrawn patches and facts cited from another source/vendor are not invented anomalies.
            self.assertFalse(intake.analyze_official(root, {"documents": {"fixture": dict(source, rules=[])}}, {})["review_required"])
            docs["patches.json"]["add"][0]["source"] = "https://different.test/network"
            docs["patches.json"]["add"][1]["vendor"] = "other"
            (root / "sources/patches.json").write_text(json.dumps(docs["patches.json"]))
            self.assertFalse(intake.analyze_official(root, {"documents": {"fixture": dict(source, rules=[])}}, production)["review_required"])

    def test_all_official_failures_preserve_baselines(self):
        before = rules.read_json(rules.ROOT / "sources/official-state.json")
        def fail(url):
            raise OSError("offline")
        after, report = intake.refresh_official(rules.ROOT, fail)
        self.assertEqual(before, after)
        expected = {s["id"] for s in rules.read_json(rules.ROOT / "sources/official.json")["sources"]}
        self.assertEqual({row["source_id"] for row in report["review_required"]}, expected)
        self.assertTrue(all(row["error_detail"] == "offline" for row in report["review_required"]))

    def test_official_wording_only_change_does_not_mutate_fact_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            source = {
                "id": "fixture", "url": "https://official.test", "vendor": "fixture",
                "format": "html", "sections": ["Network"],
                "required_hosts": ["api.example.com"], "min_hosts": 1,
            }
            old_doc = intake.extract_document(source, b"<h2>Network</h2><p>api.example.com old wording</p>")
            (root / "sources/official.json").write_text(json.dumps({"sources": [source]}))
            (root / "sources/official-state.json").write_text(json.dumps({"schema": 1, "documents": {"fixture": old_doc}}))
            new_payload = b"<h2>Network</h2><p>api.example.com new harmless wording</p>"
            after, report = intake.refresh_official(root, lambda url: new_payload)
        self.assertEqual(after["documents"]["fixture"], old_doc)
        self.assertFalse(report["sources"]["fixture"]["changed"])
        self.assertTrue(report["sources"]["fixture"]["document_changed"])
        self.assertNotEqual(report["sources"]["fixture"]["document_sha256"], old_doc["document_sha256"])

    def test_public_openai_403_uses_bounded_pinned_transport(self):
        source = {"url": "https://help.openai.com/en/articles/9247338"}
        response = types.SimpleNamespace(status_code=200, raise_for_status=lambda: None)
        calls = []
        def compatible(url, **kwargs):
            calls.append((url, kwargs))
            kwargs["content_callback"](b"<html>official</html>")
            return response
        def denied(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        module = types.SimpleNamespace(requests=types.SimpleNamespace(get=compatible))
        with patch.dict(sys.modules, {"curl_cffi": module}):
            data, transport = intake.fetch_official(source, denied)
        self.assertEqual(data, b"<html>official</html>")
        self.assertEqual(transport, "browser-compatible-https")
        self.assertFalse(calls[0][1]["allow_redirects"])
        self.assertEqual(calls[0][0], source["url"])

    def test_403_fallback_cannot_fetch_arbitrary_hosts(self):
        def denied(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            intake.fetch_official({"url": "https://unreviewed.test"}, denied)

    def test_oversized_official_fallback_fails_closed(self):
        def compatible(url, **kwargs):
            kwargs["content_callback"](b"x" * 4_000_001)
        def denied(url):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        module = types.SimpleNamespace(requests=types.SimpleNamespace(get=compatible))
        with patch.dict(sys.modules, {"curl_cffi": module}), self.assertRaisesRegex(
            OSError, "ValueError: Oversized official document"
        ):
            intake.fetch_official({"url": "https://help.openai.com/en/articles/9247338"}, denied)

    def test_openai_403_failure_remains_reviewable_with_last_good_baseline(self):
        sources = rules.read_json(rules.ROOT / "sources/official.json")["sources"]
        source = next(row for row in sources if row["id"] == "openai-network")
        state = rules.read_json(rules.ROOT / "sources/official-state.json")
        baseline = state["documents"][source["id"]]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            (root / "sources/official.json").write_text(json.dumps({"sources": [source]}))
            (root / "sources/official-state.json").write_text(json.dumps({
                "schema": 1, "documents": {source["id"]: baseline}
            }))

            def denied(url, **kwargs):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

            module = types.SimpleNamespace(requests=types.SimpleNamespace(get=denied))
            with patch.dict(sys.modules, {"curl_cffi": module}):
                after, report = intake.refresh_official(root, denied)

        self.assertEqual(after["documents"][source["id"]], baseline)
        self.assertEqual(report["sources"][source["id"]]["status"], "retained-last-good")
        self.assertEqual(len(report["review_required"]), 1)
        self.assertEqual(report["review_required"][0]["source_id"], source["id"])
        self.assertEqual(
            report["review_required"][0]["reason"],
            "official-source-unavailable-or-parser-drift",
        )
        self.assertIn("403", report["review_required"][0]["error_detail"])

    def test_shared_official_dependency_is_excluded_from_gap_report(self):
        policy = rules.read_json(rules.ROOT / "sources/intake-policy.json")
        self.assertIsNotNone(intake.official_policy_reason(
            policy, rules.Rule("DOMAIN", "storage.googleapis.com")
        ))
        self.assertIsNotNone(intake.official_policy_reason(
            policy, rules.Rule("DOMAIN", "unpkg.com")
        ))
        self.assertIsNone(intake.official_policy_reason(
            policy, rules.Rule("DOMAIN", "assets.unpkg.com")
        ))

    def test_official_gap_is_evidence_only(self):
        manifest = json.loads(rules.compile_outputs(rules.ROOT)["rules/manifest.json"])
        production = {
            (row["vendor"], row["tier"], rules.Rule.from_text(row["rule"])): set(row["sources"])
            for row in manifest["provenance"]
        }
        state = rules.read_json(rules.ROOT / "sources/official-state.json")
        report = intake.analyze_official(rules.ROOT, state, production)
        self.assertTrue(all(row["reason"] == "official-uncovered-domain" for row in report["review_required"]))
        self.assertEqual(set(production), {
            (row["vendor"], row["tier"], rules.Rule.from_text(row["rule"]))
            for row in manifest["provenance"]
        })

    def test_malformed_yaml_is_rejected_by_strict_gate(self):
        for data in (b"payload: [unterminated\n", b"payload:\n  - bad\n", b"payload:\n"):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                verify_rules.parse_artifact(data, "mihomo")

    def test_missing_release_gates_cannot_pass_as_legacy(self):
        for field in ("semantic_contract", "profiles"):
            for missing in (True, False):
                manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
                if missing:
                    manifest.pop(field)
                else:
                    manifest[field] = {}
                with self.subTest(field=field, missing=missing), patch.object(verify_rules, "read_json", return_value=manifest):
                    with self.assertRaisesRegex(ValueError, "Missing required"):
                        verify_rules.verify(rules.ROOT)


class ReleaseSummaryTests(unittest.TestCase):
    def test_recovery_preflight_never_creates_a_publication_receipt(self):
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with patch.object(release, "ROOT", root), patch.object(sys, "argv", ["release.py", "--recover-only"]), \
                        patch.dict(release.os.environ, GITHUB_REPOSITORY="NET86/rules"), \
                        patch.object(release, "Publisher") as publisher:
                    if failure:
                        publisher.return_value.recover_stable.side_effect = RuntimeError("preflight unavailable")
                        with self.assertRaises(RuntimeError):
                            release.main()
                    else:
                        release.main()
                self.assertFalse((root / ".work/release-report.json").exists())
                report = rules.read_json(root / ".work/recovery-report.json")
                self.assertEqual(report["result"], "PREVALIDATION_FAILED" if failure else "PASS")

    def test_source_health_distinguishes_publication_success_from_freshness(self):
        text = release.render_actions_summary({}, {}, {"source_health": {
            "v2fly": "fresh", "openai_voice": "retained-suspicious-change",
            "official_facts": {"kept": {"status": "retained-last-good"},
                               "absent": {"status": "unavailable-no-baseline"}},
        }}, {"result": "PASS"})
        self.assertIn("V2Fly：抓取成功", text)
        self.assertIn("OpenAI 语音：沿用旧版（变化异常）", text)
        self.assertIn("`kept`：沿用最近有效版本（本次来源更新未通过）", text)
        self.assertIn("`absent`：不可用（无有效基线）", text)
        missing = release.render_actions_summary({}, {}, {}, {"result": "PASS"})
        self.assertIn("V2Fly：未知", missing)
        self.assertNotIn("抓取成功", missing)

    @staticmethod
    def row(vendor, rule, tier="core", sources=None):
        return {
            "vendor": vendor,
            "rule": rule,
            "tier": tier,
            "sources": sources or [f"source:{vendor}"],
        }

    def test_summary_lists_changes_and_caps_each_group(self):
        before_rows = [
            self.row("changed", "DOMAIN,changed.example", sources=["old-source"]),
            self.row("removed", "DOMAIN,removed.example"),
        ]
        after_rows = [
            self.row("changed", "DOMAIN,changed.example", tier="extended", sources=["new-source"]),
            *[
                self.row(f"vendor-{index:02d}", f"DOMAIN,added-{index:02d}.example")
                for index in range(12)
            ],
        ]
        text = release.render_actions_summary(
            {"provenance": before_rows},
            {"provenance": after_rows},
            {
                "review_required": [{
                    "vendor": "openai",
                    "tier": "core",
                    "rule": "DOMAIN-SUFFIX,new.example",
                    "reason": "source-not-authorized-by-catalog",
                }],
                "quarantined_count": 2,
                "retained_count": 3,
            },
            {"result": "PASS", "candidate": "a" * 40},
        )

        self.assertIn("#### 新增（12）", text)
        self.assertIn("vendor-09", text)
        self.assertIn("DOMAIN,added-09.example", text)
        self.assertNotIn("DOMAIN,added-10.example", text)
        self.assertIn("另有 **2** 条", text)
        self.assertIn("#### 变化（1）", text)
        self.assertIn("层级 core → extended；来源变化", text)
        self.assertIn("#### 删除（1）", text)
        self.assertIn("removed.example", text)
        self.assertIn("待审核 / 异常：**1**", text)
        self.assertIn("隔离：**2**", text)
        self.assertIn("保留观察：**3**", text)
        self.assertIn("### 待审核 / 异常明细（1）", text)
        self.assertIn("`openai` · `DOMAIN-SUFFIX,new.example` · core — 来源未被 catalog 授权，已隔离", text)
        self.assertIn("stable：已更新并通过远端验证", text)

    def test_summary_caps_review_details(self):
        manifest = {"provenance": [self.row("demo", "DOMAIN,example.com")]}
        review_required = [
            {
                "vendor": f"vendor-{index:02d}",
                "rule": f"DOMAIN-SUFFIX,review-{index:02d}.example",
                "reason": "source-not-authorized-by-catalog",
            }
            for index in range(12)
        ]
        text = release.render_actions_summary(
            manifest,
            manifest,
            {"review_required": review_required, "quarantined_count": 12, "retained_count": 0},
            {"result": "PASS", "stable_noop": "UNCHANGED_RELEASE_CONTENT"},
        )

        self.assertIn("### 待审核 / 异常明细（12）", text)
        self.assertIn("review-09.example", text)
        self.assertNotIn("review-10.example", text)
        self.assertIn("另有 **2** 条，详见异常 Issue 或 sync-report.json。", text)

    def test_summary_marks_no_production_change(self):
        manifest = {"provenance": [self.row("demo", "DOMAIN,example.com")]}
        text = release.render_actions_summary(
            manifest,
            manifest,
            {"review_required": [], "quarantined_count": 0, "retained_count": 0},
            {"result": "PASS", "stable_noop": "UNCHANGED_RELEASE_CONTENT"},
        )
        self.assertIn("### 规则变化\n- 无变化", text)
        self.assertNotIn("#### 新增", text)
        self.assertNotIn("#### 删除", text)
        self.assertIn("stable：订阅产物和产品契约无变化，未轮换", text)


class ReleaseTests(unittest.TestCase):
    def manifest(self, marker):
        manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
        manifest["bundles"]["ai-daily"]["mihomo"]["sha256"] = rules.sha256(marker.encode())
        return manifest

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote.git"
        self.root = self.base / "local"
        subprocess.run(["git", "init", "--template=", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "--template=", "-b", "main", str(self.root)], check=True, capture_output=True)
        self.publisher = release.Publisher(self.root)
        self.git = self.publisher.git
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", str(self.remote))
        (self.root / "rules").mkdir()
        (self.root / "rules/data").write_text("known good")
        (self.root / "rules/manifest.json").write_text(json.dumps(self.manifest("known-good")))
        (self.root / "code").write_text("old code")
        self.git("add", ".")
        self.git("commit", "-m", "known good")
        self.old = self.git("rev-parse", "HEAD")
        self.git("push", "origin", "HEAD:main", "HEAD:stable", "HEAD:last-known-good")
        (self.root / "rules/data").write_text("candidate")
        (self.root / "rules/manifest.json").write_text(json.dumps(self.manifest("candidate")))
        (self.root / "code").write_text("new recovery code")
        self.git("add", ".")
        self.git("commit", "-m", "candidate")
        self.candidate = self.git("rev-parse", "HEAD")
        self.report = {}

    def tearDown(self):
        self.temp.cleanup()

    def test_success_updates_stable_and_retains_previous_verified_release(self):
        called = []
        self.publisher.run(self.candidate, lambda ref, label, expected: called.append(label), self.report)
        stable = self.publisher.remote_ref("stable")
        self.assertEqual(self.publisher.tree(stable), self.publisher.tree(self.candidate))
        self.assertEqual(self.publisher.remote_ref("last-known-good"), self.old)
        self.assertEqual(called, ["candidate", "stable"])
        self.assertEqual(self.report["result"], "PASS")

    def test_evidence_only_change_updates_main_without_rotating_stable(self):
        (self.root / "rules/data").write_text("known good")
        manifest = self.manifest("known-good")
        manifest["upstream"]["v2fly_revision"] = "e" * 40
        manifest["automation"]["retained"] = [{"observation_days": ["2026-09-21"]}]
        (self.root / "rules/manifest.json").write_text(json.dumps(manifest))
        (self.root / "code").write_text("evidence changed; subscription content unchanged")
        self.git("add", ".")
        self.git("commit", "-m", "radar-only state change")
        candidate = self.git("rev-parse", "HEAD")
        called = []
        report = {}
        self.publisher.run(candidate, lambda ref, label, expected: called.append((label, expected)), report)
        self.assertEqual(self.publisher.remote_ref("main"), candidate)
        self.assertEqual(self.publisher.remote_ref("stable"), self.old)
        self.assertEqual(self.publisher.remote_ref("last-known-good"), self.old)
        self.assertEqual(report["stable_noop"], "UNCHANGED_RELEASE_CONTENT")
        self.assertEqual(called, [("candidate", candidate), ("stable", self.old)])

    def test_candidate_remote_failure_never_promotes_and_does_not_roll_back_main(self):
        def validate(ref, label, expected):
            if label == "candidate":
                raise ValueError("bad downloaded bytes")
        with self.assertRaises(ValueError):
            self.publisher.run(self.candidate, validate, self.report)
        self.assertEqual(self.publisher.remote_ref("stable"), self.old)
        self.assertEqual(self.publisher.remote_ref("main"), self.candidate)
        self.assertEqual(self.git("show", f"{self.candidate}:rules/data"), "candidate")
        self.assertEqual(self.git("show", f"{self.candidate}:code"), "new recovery code")
        self.assertEqual(self.report["rollback"], "NOT_NEEDED_STABLE_UNCHANGED")

    def test_postpromotion_failure_forward_rolls_back_all_rules(self):
        def validate(ref, label, expected):
            if label == "stable":
                raise ValueError("postpublication failure")
        with self.assertRaises(ValueError):
            self.publisher.run(self.candidate, validate, self.report)
        stable = self.publisher.remote_ref("stable")
        self.assertNotEqual(stable, self.old)
        self.assertEqual(self.publisher.tree(stable), self.publisher.tree(self.old))
        self.assertEqual(self.report["rollback"], "RESTORED_STABLE")
        # The next run recovers automatically with the same candidate content.
        self.git("fetch", "origin", "main")
        recovered = self.git("commit-tree", self.publisher.tree(self.candidate), "-p",
                             self.publisher.remote_ref("main"), input="retry\n")
        report = {}
        self.publisher.run(recovered, lambda *args: None, report)
        self.assertEqual(report["result"], "PASS")

    def assert_main_race_rejected(self, phase):
        other = None
        def validate(ref, label, expected):
            nonlocal other
            if label == phase:
                other = self.git("commit-tree", self.publisher.tree(self.candidate), "-p", self.candidate, input="independent edit\n")
                self.git("push", "origin", f"{other}:main")
        with self.assertRaisesRegex(RuntimeError, "Concurrent main update"):
            self.publisher.run(self.candidate, validate, self.report)
        self.assertEqual(self.publisher.remote_ref("main"), other)
        stable = self.publisher.remote_ref("stable")
        self.assertEqual(self.publisher.tree(stable), self.publisher.tree(self.old))
        self.assertEqual(self.report["result"], "FAILED")
        self.assertEqual(self.report["rollback"],
                         "RESTORED_STABLE" if phase == "stable" else "NOT_NEEDED_STABLE_UNCHANGED")

    def test_concurrent_main_edit_is_never_overwritten(self):
        self.assert_main_race_rejected("candidate")

    def test_main_race_during_stable_readback_cannot_report_success(self):
        self.assert_main_race_rejected("stable")

    def test_missing_lkg_fails_before_publication(self):
        self.git("push", "origin", ":last-known-good")
        with self.assertRaises(RuntimeError):
            self.publisher.run(self.candidate, lambda *args: None, self.report)
        self.assertEqual(self.publisher.remote_ref("main"), self.old)

    def test_next_run_recovers_interrupted_rollback(self):
        self.git("push", "origin", f"{self.candidate}:stable")
        called = []
        def validate(ref, expected):
            called.append((ref, expected))
            if len(called) == 1:
                raise ValueError("invalid or interrupted stable publication")
        self.publisher.recover_stable(validate, self.report)
        self.assertEqual(self.publisher.tree(self.publisher.remote_ref("stable")), self.publisher.tree(self.old))
        self.assertEqual(self.report["stable_preflight"], "AUTOMATICALLY_RECOVERED")
        self.assertEqual(called[1], (self.old, self.old))

    def test_total_raw_outage_does_not_replace_stable(self):
        def fail(*args):
            raise OSError("raw service unavailable")
        with self.assertRaises(OSError):
            self.publisher.recover_stable(fail, self.report)
        self.assertEqual(self.publisher.remote_ref("stable"), self.old)

    def test_download_hash_mismatch_is_rejected(self):
        manifest = {"bundles": {}}
        with self.assertRaises(ValueError):
            release.downloaded_rules(self.base / "download", self.candidate, manifest, get=lambda url: b"wrong", max_wait=0)

    def test_stale_raw_cache_must_converge_to_exact_validated_bytes(self):
        manifest = {"bundles": {}}
        expected = rules.json_text(manifest).encode()
        results = iter([b"stale old manifest", expected])
        target = self.base / "download"
        release.downloaded_rules(target, self.candidate, manifest, get=lambda url: next(results), pause=lambda seconds: None)
        self.assertEqual((target / "rules/manifest.json").read_bytes(), expected)

    def test_download_paths_cannot_escape(self):
        manifest = {"bundles": {"bad": {"mihomo": {"path": "../outside", "sha256": "x"}}}}
        with self.assertRaises(ValueError):
            release.downloaded_rules(self.base / "download", self.candidate, manifest, get=lambda url: b"")


if __name__ == "__main__":
    unittest.main()
