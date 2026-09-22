import gzip
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import download_mihomo


class MihomoDownloadTests(unittest.TestCase):
    def test_zip_extracts_single_executable(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("mihomo.exe", b"binary")
        self.assertEqual(download_mihomo.extracted_binary("mihomo.zip", payload.getvalue()), b"binary")

    def test_gzip_extracts_binary(self):
        self.assertEqual(download_mihomo.extracted_binary("mihomo.gz", gzip.compress(b"binary")), b"binary")

    def test_zip_rejects_multiple_executables(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("one.exe", b"one")
            archive.writestr("two.exe", b"two")
        with self.assertRaisesRegex(ValueError, "executable count"):
            download_mihomo.extracted_binary("mihomo.zip", payload.getvalue())


class EmbeddedCoreIntegrityTests(unittest.TestCase):
    def test_cached_core_rejects_wrong_origin_or_dirty_source_without_cleaning_it(self):
        import json
        import tempfile
        from unittest.mock import patch
        import build_flclash_core
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources").mkdir()
            (root / "sources/engines.json").write_text(json.dumps({"flclash": {
                "core_repository": "https://github.com/owner/core", "core_revision": "a" * 40,
                "app_version": "fixture"}}))
            (root / ".work/flclash-core-source/.git").mkdir(parents=True)
            for origin, status in [("https://github.com/other/core", ""),
                                   ("https://github.com/owner/core", " M main.go"),
                                   ("https://github.com/owner/core", "?? injected.go"),
                                   ("https://github.com/owner/core", "")]:
                with self.subTest(origin=origin, status=status), patch.object(build_flclash_core, "ROOT", root), \
                        patch.object(build_flclash_core.subprocess, "check_output", side_effect=[origin, status]), \
                        patch.object(build_flclash_core.subprocess, "run") as run:
                    if status or origin.endswith("other/core"):
                        with self.assertRaises(ValueError):
                            build_flclash_core.main()
                        run.assert_not_called()
                    else:
                        build_flclash_core.main()
                        self.assertEqual(run.call_args.args[0][:3], ["go", "build", "-mod=readonly"])


if __name__ == "__main__":
    unittest.main()
