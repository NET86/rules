"""Fail-closed review of V2Fly attributes across production and source radars."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_sources
import automation
import intake
import notify_review
import release
import rules
import sync


class AttributePolicyTests(unittest.TestCase):
    @staticmethod
    def catalog(mode="sources"):
        row = {"id": "demo", "group": "global"}
        if mode == "sources":
            row["sources"] = ["dedicated"]
        else:
            row["select"] = {"dedicated": [
                "normal.example.com", "unknown.example.com",
                "mixed.example.com", "ads.example.com",
            ]}
        return {"vendors": [row], "profiles": {}}

    @staticmethod
    def patches():
        return {"add": [], "drop": {}, "surge_regex": {}}

    def test_known_nonproduction_neutral_and_unknown_metadata(self):
        self.assertEqual(rules.unreviewed_source_attributes({"@cn", "@!cn"}), [])
        self.assertFalse(rules.excluded_by_source_metadata({"@cn", "@!cn"}))
        for name in ("@ads", "@telemetry"):
            self.assertTrue(rules.excluded_by_source_metadata({name}))
        self.assertEqual(
            rules.unreviewed_source_attributes({"@cn", "@new-tag", "@!cn", "@future"}),
            ["@future", "@new-tag"],
        )
        self.assertTrue(rules.excluded_by_source_metadata({"@future"}))

    def test_dedicated_quarantines_and_reports_without_poisoning_good_rules(self):
        body = (
            "full:normal.example.com @cn\n"
            "full:unknown.example.com @preview\n"
            "full:mixed.example.com @telemetry @new-tag\n"
            "full:ads.example.com @ads\n"
            "full:neutral.example.com @!cn\n"
            "full:normal.example.com @preview\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dedicated").write_text(body, encoding="utf-8")
            issues = []
            entries = rules.collect(self.catalog(), self.patches(), root,
                                    review_mode=True, attribute_issues=issues)
        self.assertEqual(
            {key[2].text for key in entries},
            {"DOMAIN,normal.example.com", "DOMAIN,neutral.example.com"},
        )
        self.assertEqual(
            {(i["rule"], tuple(i["attributes"])) for i in issues},
            {("DOMAIN,unknown.example.com", ("@preview",)),
             ("DOMAIN,normal.example.com", ("@preview",))},
        )
        self.assertTrue(all(i["vendor"] == "demo" and
                            i["source"] == "v2fly:data/dedicated" and
                            i["entrypoint"] == "dedicated" and
                            i["reason"] == "unreviewed-upstream-attribute"
                            for i in issues))

    def test_selected_domains_are_quarantined_and_unselected_remain_ignored(self):
        body = (
            "full:normal.example.com @!cn\n"
            "full:unknown.example.com @upcoming\n"
            "full:mixed.example.com @ads @preview\n"
            "full:ads.example.com @ads\n"
            "full:unselected.example.com @irrelevant\n"
        )
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "dedicated").write_text(body, encoding="utf-8")
            issues = []
            result = rules.collect(self.catalog("select"), self.patches(), data,
                                   review_mode=True, attribute_issues=issues)
        self.assertEqual({key[2].text for key in result}, {"DOMAIN,normal.example.com"})
        self.assertEqual(
            {row["rule"] for row in issues},
            {"DOMAIN,unknown.example.com"},
        )

    def test_transitive_origin_is_reported_without_inheriting_authority(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "dedicated").write_text("include:child\n", encoding="utf-8")
            (data / "child").write_text("full:child.example.com @drift\n", encoding="utf-8")
            issues = []
            result = rules.collect(self.catalog(), self.patches(), data,
                                   review_mode=True, attribute_issues=issues)
        self.assertFalse(result)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["source"], "v2fly:data/child")
        self.assertEqual(issues[0]["entrypoint"], "dedicated")

    def test_unreviewed_attributes_without_report_sink_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "dedicated").write_text("full:unknown.example.com @new-tag\n",
                                            encoding="utf-8")
            for kwargs in ({}, {"review_mode": True}):
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "review reporting"):
                    rules.collect(self.catalog(), self.patches(), data, **kwargs)

    def test_product_section_radar_ignores_nonproduction_and_unknown_rules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "sources"
            source.mkdir()
            (source / "watch.json").write_text(json.dumps({
                "primary_sections": [{
                    "vendor": "demo", "source": "dedicated", "sections": ["Product"]
                }]
            }), encoding="utf-8")
            (source / "patches.json").write_text(json.dumps(self.patches()), encoding="utf-8")
            (source / "catalog.json").write_text(json.dumps({
                "vendors": [{"id": "demo", "select": {
                    "dedicated": ["normal.example.com", "unknown.example.com"]
                }}]
            }), encoding="utf-8")
            data = root / "data"
            data.mkdir()
            (data / "dedicated").write_text(
                "# Product\nfull:normal.example.com @cn\n"
                "full:unknown.example.com @upcoming\n"
                "full:tracking.example.com @telemetry\n", encoding="utf-8")
            pending = intake.analyze_selected_sources(root, data, {})
        self.assertEqual([(p["rule"], p["reason"]) for p in pending],
                         [("DOMAIN,normal.example.com", "selected-product-uncovered-domain")])

    def test_secondary_radar_does_not_grant_unknown_tagged_authority(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "dedicated").write_text("full:unknown.example.com @unknown\n",
                                            encoding="utf-8")
            rows = audit_sources.enrich_pending(
                [{"vendor": "demo", "rule": "DOMAIN,unknown.example.com"}],
                {"vendors": [{"id": "demo", "sources": ["dedicated"]}], "profiles": {}},
                self.patches(), {"documents": {}}, data)
        self.assertEqual(rows[0]["block_reason"], "unreviewed-upstream-attribute")
        self.assertNotIn("等待规则同步", rows[0]["block_reason_label"])

    def test_issue_and_summary_show_the_tag_and_exact_origin(self):
        row = {"vendor": "demo", "rule": "DOMAIN,unknown.example.com",
               "source": "v2fly:data/child", "entrypoint": "dedicated",
               "attributes": ["@unknown"], "reason": "unreviewed-upstream-attribute"}
        issue = notify_review.issue_body("sync", {"review_required": [row]})
        self.assertIn('"attributes": [', issue)
        self.assertIn('"@unknown"', issue)
        self.assertIn('"entrypoint": "dedicated"', issue)
        self.assertIn('"source": "v2fly:data/child"', issue)
        self.assertIn("标签：@unknown", release.format_review_item(row))

    def test_unknown_tag_freezes_retirement_even_with_reviewed_removal_override(self):
        catalog = self.catalog()
        patches = self.patches()
        old = ("demo", "core", rules.Rule("DOMAIN", "old.example.com"))
        good = ("demo", "core", rules.Rule("DOMAIN", "normal.example.com"))
        origins = {"v2fly:data/dedicated"}
        previous = {"provenance": [automation.row_of(x, origins) for x in (old, good)]}
        candidates = {good: set(origins)}
        state, report = automation.reconcile(
            candidates, previous, catalog, patches,
            {"schema": 1, "pending": [], "retained": []},
            {"removal_grace_days": 0, "removal_min_observation_days": 1},
            allow_removals=True, unhealthy_vendors={"demo"}, contracts={"vendors": {}})
        self.assertEqual(report["deletion_observation_frozen_vendors"], ["demo"])
        self.assertEqual(report["automatically_removed"], [])
        self.assertEqual({automation.key_of(row) for row in state["retained"]}, {old})
        self.assertIn(old, automation.effective_entries(candidates, catalog, patches, state))
        self.assertNotIn(old, candidates)


class SyncIntegrationTests(unittest.TestCase):
    def test_real_sync_quarantines_new_tag_and_retains_previous_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for directory in ("sources", "rules"):
                shutil.copytree(rules.ROOT / directory, root / directory)
            old_rule = "DOMAIN,copilot-proxy.githubusercontent.com"
            previous = rules.read_json(root / "rules/manifest.json")
            self.assertTrue(any(row["vendor"] == "github-copilot" and row["rule"] == old_rule
                                for row in previous["provenance"]))

            def export(_repo, snapshot, _catalog, _voice):
                shutil.copytree(root / "sources/snapshot", snapshot)
                path = snapshot / "v2fly/github-copilot"
                old = path.read_text(encoding="utf-8")
                self.assertIn("full:copilot-proxy.githubusercontent.com\n", old)
                path.write_text(
                    old.replace("full:copilot-proxy.githubusercontent.com\n",
                                "full:copilot-proxy.githubusercontent.com @newstatus\n")
                    + "full:p3-review.githubusercontent.com @future\n",
                    encoding="utf-8")
                lock = rules.read_json(snapshot / "lock.json")
                lock["sha256"]["v2fly/github-copilot"] = rules.sha256(path.read_bytes())
                (snapshot / "lock.json").write_text(rules.json_text(lock), encoding="utf-8")

            argv = ["sync.py", "--source-repo", str(root / "local-source"),
                    "--voice-file", str(root / "sources/snapshot/openai-voice.json")]
            official = (rules.read_json(root / "sources/official-state.json"),
                        {"sources": {}, "review_required": []})
            with patch.object(sync, "ROOT", root), patch.object(sys, "argv", argv), \
                 patch.object(sync, "snapshot_from_repo", side_effect=export), \
                 patch.object(sync, "refresh_official", return_value=official):
                self.assertEqual(sync.main(), 0)
            report = rules.read_json(root / ".work/sync-report.json")
            rows = [r for r in report["review_required"]
                    if r["reason"] == "unreviewed-upstream-attribute"]
            self.assertEqual({r["rule"] for r in rows},
                             {old_rule, "DOMAIN,p3-review.githubusercontent.com"})
            self.assertEqual(report["deletion_observation_frozen_vendors"], [])
            self.assertEqual(report["deletion_observation_frozen_rules"], [
                {"vendor": "github-copilot", "rule": old_rule}
            ])
            self.assertEqual(report["quarantined_count"], 2)
            self.assertEqual(report["source_health"]["v2fly"], "reviewed-local-input")
            state = rules.read_json(root / "sources/automation-state.json")
            manifest = rules.read_json(root / "rules/manifest.json")
            self.assertTrue(any(r["vendor"] == "github-copilot" and
                                r["rule"] == old_rule for r in state["retained"]))
            self.assertTrue(any(r["vendor"] == "github-copilot" and
                                r["rule"] == old_rule for r in manifest["provenance"]))
            self.assertFalse(any(r["rule"] == "DOMAIN,p3-review.githubusercontent.com"
                                 for r in manifest["provenance"]))
            self.assertNotIn("p3-review.githubusercontent.com",
                             (root / "rules/surge/github-copilot.list").read_text(encoding="utf-8"))
