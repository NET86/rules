"""Routing probes must cover IP boundaries and classify touching networks correctly."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
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


if __name__ == "__main__":
    unittest.main()
