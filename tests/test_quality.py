"""Regression guards for observed discovery, policy and publication blind spots."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import automation
import intake
import release
import rules
import sync
import verify_rules


class SemanticShapeTests(unittest.TestCase):
    def test_empty_missing_and_contradictory_contracts_are_rejected(self):
        baseline = rules.read_json(rules.ROOT / "sources/semantic-contracts.json")
        mutations = [
            lambda c: c.update(vendors={}),
            lambda c: c["vendors"].pop("openai"),
            lambda c: c["vendors"].pop("tencent-ai"),
            lambda c: c["profiles"].pop("ai-cn"),
            lambda c: c["profiles"]["ai-daily"].update(must_match=[]),
            lambda c: c["profiles"]["ai-core"].update(must_not_match=[]),
            lambda c: c["vendors"]["openai"].update(must_not_match=["api.openai.com"]),
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            for mutate in mutations:
                contract = copy.deepcopy(baseline)
                mutate(contract)
                data = rules.json_text(contract).encode()
                (root / "sources/semantic-contracts.json").write_bytes(data)
                manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
                manifest["semantic_contract"]["sha256"] = rules.sha256(data)
                with self.assertRaises(ValueError):
                    verify_rules.load_contracts(root, manifest)

    def test_valid_gate_reports_real_independent_case_count(self):
        report = verify_rules.verify(rules.ROOT)
        contract = rules.read_json(rules.ROOT / "sources/semantic-contracts.json")
        expected = sum(len(c[field]) for group in ("vendors", "profiles")
                       for c in contract[group].values() for field in ("must_match", "must_not_match"))
        self.assertEqual(report["semantic_case_count"], expected)
        self.assertGreater(expected, 0)

    def test_vendor_swap_cannot_hide_inside_an_unchanged_aggregate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(rules.ROOT / "sources", root / "sources")
            catalog = rules.read_json(root / "sources/catalog.json")
            vendors = {v["id"]: v for v in catalog["vendors"]}
            baidu, tencent = vendors["baidu-wenxin"], vendors["tencent-ai"]
            baidu["select"], tencent["select"] = tencent["select"], baidu["select"]
            (root / "sources/catalog.json").write_text(rules.json_text(catalog), encoding="utf-8")
            rules.publish_files(root, rules.compile_outputs(root))
            with self.assertRaisesRegex(ValueError, "Semantic contract miss: vendor/(baidu-wenxin|tencent-ai)"):
                verify_rules.verify(root)

    def test_legacy_contracts_can_be_recovered_but_not_compile_new_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(rules.ROOT / "sources", root / "sources")
            contracts = rules.read_json(root / "sources/semantic-contracts.json")
            contracts["schema"] = 1
            contracts["vendors"] = {name: contracts["vendors"][name] for name in
                                    ("openai", "claude", "grok", "perplexity", "google-ai", "cursor")}
            data = rules.json_text(contracts).encode()
            (root / "sources/semantic-contracts.json").write_bytes(data)
            manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
            manifest["semantic_contract"]["sha256"] = rules.sha256(data)
            self.assertEqual(verify_rules.load_contracts(root, manifest)["schema"], 1)
            with self.assertRaisesRegex(ValueError, "schema 2 contracts"):
                rules.compile_outputs(root)

    def test_new_vendor_contract_preserves_last_critical_entry_on_removal(self):
        manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
        before = {(row["vendor"], row["tier"], rules.Rule.from_text(row["rule"])): set(row["sources"])
                  for row in manifest["provenance"] if row["tier"] == "core"}
        key = next(key for key in before if key[0] == "tencent-ai" and key[2].value == "yuanbao.tencent.com")
        before.pop(key)
        state, report = automation.reconcile(before, manifest,
            rules.read_json(rules.ROOT / "sources/catalog.json"),
            rules.read_json(rules.ROOT / "sources/patches.json"), {},
            rules.read_json(rules.ROOT / "sources/automation.json"), allow_removals=True,
            contracts=rules.read_json(rules.ROOT / "sources/semantic-contracts.json"))
        self.assertTrue(any(row["rule"] == key[2].text and row["protected"] for row in state["retained"]))


class ScopeBoundaryTests(unittest.TestCase):
    def test_shared_roots_are_quarantined_but_exact_tenant_rules_still_pass(self):
        catalog = {"vendors": [{"id": "demo", "sources": ["demo"]}]}
        patches = {"add": [], "drop": {}, "surge_regex": {}}
        origins = {"v2fly:data/demo"}
        for value in ("co.uk", "s3.us-east-1.amazonaws.com", "s3.eu-west-2.amazonaws.com",
                      "s3-cn-north-1.amazonaws.com.cn", "workers.dev", "github.io"):
            key = ("demo", "core", rules.Rule("DOMAIN-SUFFIX", value))
            self.assertEqual(automation.scope_problem(key, origins, catalog, patches),
                             "shared-platform-forbidden-in-core", value)
        for value in ("product.s3.us-east-1.amazonaws.com", "product.workers.dev", "product.co.uk"):
            key = ("demo", "core", rules.Rule("DOMAIN", value))
            self.assertIsNone(automation.scope_problem(key, origins, catalog, patches), value)


class VoiceChangeTests(unittest.TestCase):
    @staticmethod
    def payload(*values):
        return {"prefixes": [{"ipv4Prefix": value} for value in values]}

    def test_truncated_voice_response_retains_verified_previous_list(self):
        previous = (rules.ROOT / "sources/snapshot/openai-voice.json").read_bytes()
        candidate = json.loads(previous)
        candidate["prefixes"] = candidate["prefixes"][:1]
        with patch.object(sync, "fetch", return_value=json.dumps(candidate).encode()):
            payload, status = sync.fetch_voice(rules.ROOT)
        self.assertEqual(payload, previous)
        self.assertEqual(status, "retained-suspicious-change")

    def test_small_changes_and_equivalent_consolidation_are_automatic(self):
        before = self.payload("8.8.8.8/32", "8.8.8.9/32", "8.8.8.10/32", "8.8.8.11/32")
        self.assertIsNone(sync.voice_change_problem(before, self.payload("8.8.8.8/30")))
        self.assertIsNone(sync.voice_change_problem(before, self.payload("8.8.8.8/32", "8.8.8.9/32", "8.8.4.4/32")))
        self.assertIsNone(sync.voice_change_problem(self.payload("8.8.8.0/24"),
                                                   self.payload("8.8.8.0/25", "8.8.8.128/25")))

    def test_address_space_expansion_and_new_family_require_review(self):
        before = self.payload("8.8.8.8/32")
        self.assertIn("expanded", sync.voice_change_problem(before, self.payload("8.8.0.0/16")))
        self.assertIn("shrank", sync.voice_change_problem(self.payload("8.8.8.0/24"), before))
        after = copy.deepcopy(before)
        after["prefixes"].append({"ipv6Prefix": "2606:4700::/48"})
        self.assertIn("IPv6", sync.voice_change_problem(before, after))


class SelectionRadarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(rules.ROOT / "sources", self.root / "sources")
        self.data = self.root / "sources/snapshot/v2fly"
        self.source = self.data / "google-deepmind"
        manifest = rules.read_json(rules.ROOT / "rules/manifest.json")
        self.entries = {(r["vendor"], r["tier"], rules.Rule.from_text(r["rule"])): set(r["sources"])
                        for r in manifest["provenance"]}

    def test_new_product_endpoint_stays_pending_without_becoming_production(self):
        self.assertFalse(intake.analyze_selected_sources(self.root, self.data, self.entries))
        self.source.write_text(self.source.read_text().replace("# NotebookLM", "# NotebookLM\nnew-notebook.google"))
        before = copy.deepcopy(self.entries)
        first = intake.analyze_selected_sources(self.root, self.data, self.entries)
        second = intake.analyze_selected_sources(self.root, self.data, self.entries)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["rule"], "DOMAIN-SUFFIX,new-notebook.google")
        self.assertEqual(self.entries, before)
        key = ("google-ai", "core", rules.Rule("DOMAIN-SUFFIX", "new-notebook.google"))
        self.entries[key] = {"reviewed"}
        self.assertFalse(intake.analyze_selected_sources(self.root, self.data, self.entries))

    def test_reviewed_exclusion_and_out_of_scope_sections_are_quiet(self):
        self.source.write_text(self.source.read_text().replace("# NotebookLM", "# NotebookLM\nexcluded.google")
                               + "\n# Unmaintained product\nunrelated.google\n")
        path = self.root / "sources/patches.json"
        patches = rules.read_json(path)
        patches["drop"]["google-ai"] = {"DOMAIN-SUFFIX,excluded.google": "Explicit scope decision"}
        path.write_text(rules.json_text(patches), encoding="utf-8")
        self.assertFalse(intake.analyze_selected_sources(self.root, self.data, self.entries))

    def test_changed_section_name_is_visible(self):
        self.source.write_text(self.source.read_text().replace("# NotebookLM", "# Renamed product"))
        report = intake.analyze_selected_sources(self.root, self.data, self.entries)
        self.assertEqual(report[0]["reason"], "selected-product-section-drift")
        self.assertEqual(report[0]["section"], "NotebookLM")


class ReleaseSurfaceTests(unittest.TestCase):
    def test_product_and_contract_changes_cannot_be_skipped(self):
        baseline = rules.read_json(rules.ROOT / "rules/manifest.json")
        publisher = release.Publisher(rules.ROOT)
        for field in ("bundles", "profiles", "profile_features", "semantic_contract", "conversion_warnings", "license", "formats"):
            changed = copy.deepcopy(baseline)
            changed[field] = "changed fixture"
            with patch.object(publisher, "git", side_effect=[json.dumps(baseline), json.dumps(changed)]):
                self.assertFalse(publisher.same_release("candidate", "stable"), field)
