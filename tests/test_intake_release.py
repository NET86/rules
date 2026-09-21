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

    def test_google_discovery_identity_and_endpoints(self):
        source = next(s for s in rules.read_json(rules.ROOT / "sources/official.json")["sources"] if s["format"] == "discovery")
        doc = {"name": "generativelanguage", "kind": "discovery#restDescription",
               "rootUrl": "https://generativelanguage.googleapis.com/", "mtlsRootUrl": "https://generativelanguage.mtls.googleapis.com/"}
        self.assertEqual(len(intake.extract_document(source, json.dumps(doc).encode())["rules"]), 2)
        doc["name"] = "wrong-api"
        with self.assertRaises(ValueError):
            intake.extract_document(source, json.dumps(doc).encode())

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
            before = copy.deepcopy(production)
            report = intake.analyze_official(root, state, production)
        self.assertEqual(production, before)
        self.assertEqual(report["decisions"][0]["action"], "already-covered")
        self.assertEqual(report["review_required"][0]["reason"], "official-uncovered-domain")

    def test_all_official_failures_preserve_baselines(self):
        before = rules.read_json(rules.ROOT / "sources/official-state.json")
        def fail(url):
            raise OSError("offline")
        after, report = intake.refresh_official(rules.ROOT, fail)
        self.assertEqual(before, after)
        self.assertEqual(len(report["review_required"]), 6)
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

    def test_shared_official_dependency_is_excluded_from_gap_report(self):
        policy = rules.read_json(rules.ROOT / "sources/intake-policy.json")
        reason = intake.official_policy_reason(policy, rules.Rule("DOMAIN", "storage.googleapis.com"))
        self.assertIsNotNone(reason)

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
    def test_source_health_distinguishes_publication_success_from_freshness(self):
        text = release.render_actions_summary({}, {}, {"source_health": {
            "v2fly": "fresh", "openai_voice": "retained-suspicious-change",
            "official_facts": {"kept": {"status": "retained-last-good"},
                               "absent": {"status": "unavailable-no-baseline"}},
        }}, {"result": "PASS"})
        self.assertIn("V2Fly：本轮抓取成功", text)
        self.assertIn("OpenAI Voice：沿用旧版（本轮变化异常）", text)
        self.assertIn("`kept`：沿用旧版（本轮抓取失败）", text)
        self.assertIn("`absent`：不可用（无有效基线）", text)
        missing = release.render_actions_summary({}, {}, {}, {"result": "PASS"})
        self.assertIn("V2Fly：未知", missing)
        self.assertNotIn("本轮抓取成功", missing)

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
        self.assertIn("另有 **2** 条，详见 exception Issue / sync-report.json。", text)

    def test_summary_marks_no_production_change(self):
        manifest = {"provenance": [self.row("demo", "DOMAIN,example.com")]}
        text = release.render_actions_summary(
            manifest,
            manifest,
            {"review_required": [], "quarantined_count": 0, "retained_count": 0},
            {"result": "PASS", "stable_noop": "UNCHANGED_RELEASE_CONTENT"},
        )
        self.assertIn("### 生产规则\n- 无变化", text)
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

    def test_concurrent_main_edit_is_never_overwritten(self):
        other = None
        def validate(ref, label, expected):
            nonlocal other
            if label == "candidate":
                other = self.git("commit-tree", self.publisher.tree(self.candidate), "-p", self.candidate, input="independent edit\n")
                self.git("push", "origin", f"{other}:main")
                raise ValueError("later validation failure")
        with self.assertRaises(ValueError):
            self.publisher.run(self.candidate, validate, self.report)
        self.assertEqual(self.publisher.remote_ref("main"), other)
        self.assertEqual(self.publisher.remote_ref("stable"), self.old)
        self.assertEqual(self.report["rollback"], "NOT_NEEDED_STABLE_UNCHANGED")

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
