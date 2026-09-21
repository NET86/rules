"""Routing probes must cover IP boundaries and classify touching networks correctly."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_mihomo
from verify_mihomo import voice_probe_cases


class VoiceProbeTests(unittest.TestCase):
    def test_every_network_boundary_with_adjacent_cidrs_and_ipv6(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rules = ["IP-CIDR,8.8.8.0/31,no-resolve", "IP-CIDR,8.8.8.2/31,no-resolve",
                     "IP-CIDR6,2606:4700::/126,no-resolve"]
            (root / "voice.yaml").write_text("payload:\n" + "".join("  - " + json.dumps(r) + "\n" for r in rules))
            manifest = {"bundles": {"openai-voice-ip": {"mihomo": {"path": "voice.yaml"}}}}
            cases = dict(voice_probe_cases(root, manifest, True))
            for address in ("8.8.8.0", "8.8.8.1", "8.8.8.2", "8.8.8.3", "2606:4700::", "2606:4700::3"):
                self.assertTrue(cases[address], address)
            for address in ("8.8.7.255", "8.8.8.4", "2606:46ff:ffff:ffff:ffff:ffff:ffff:ffff", "2606:4700::4"):
                self.assertFalse(cases[address], address)
            self.assertEqual(set(cases), set(dict(voice_probe_cases(root, manifest, False))))
            self.assertFalse(any(matches for _, matches in voice_probe_cases(root, manifest, False)))


class ProviderRecoveryTests(unittest.TestCase):
    def test_recovery_requires_original_cache_and_working_original_route(self):
        for failure in (None, "empty-active-provider", "stale-cache"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                directory = root / "providers"
                directory.mkdir()
                (root / "cache").mkdir()
                path = directory / "demo.yaml"
                cached = root / "cache/demo.yaml"
                original = b'payload:\n  - "DOMAIN,original.example"\n'
                path.write_bytes(original)
                response = MagicMock()
                response.__enter__.return_value.status = 204
                updates = []

                def update(request, timeout):
                    updates.append(request)
                    # Successful update, outage retaining cache, malformed content,
                    # then an acknowledged restore which may silently be ineffective.
                    if len(updates) in (1, 3) or (len(updates) == 4 and failure != "stale-cache"):
                        cached.write_bytes(path.read_bytes())
                    return response

                opener = MagicMock()
                opener.open.side_effect = update
                outcomes = [True, True, False, False, failure != "empty-active-provider"]
                with patch.object(verify_mihomo, "probe", side_effect=outcomes):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, "restore original rules"):
                            verify_mihomo.verify_http_refresh(opener, 1, 2, directory, "demo", "original.example")
                    else:
                        report = verify_mihomo.verify_http_refresh(opener, 1, 2, directory, "demo", "original.example")
                        self.assertEqual(report["recovery"], "PASS")
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(verify_mihomo.QuietFileHandler.unavailable)


if __name__ == "__main__":
    unittest.main()
