import gzip
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import download_mihomo
from rules import sha256


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


    def test_primary_504_uses_official_asset_and_checks_digest(self):
        binary = b"pinned Mihomo test executable"
        archive = gzip.compress(binary)
        for payload in (archive, b"unexpected asset"):
            with self.subTest(valid=payload == archive), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                requests = []

                def open_request(opener, request, **kwargs):
                    requests.append(request)
                    if request.host == "github.com":
                        raise HTTPError(request.full_url, 504, "Gateway Time-out", None, None)
                    response = io.BytesIO(payload)
                    response.headers = {}
                    return response

                with (
                    patch.object(download_mihomo, "ROOT", root),
                    patch.object(download_mihomo.platform, "system", return_value="Linux"),
                    patch.object(download_mihomo.platform, "machine", return_value="x86_64"),
                    patch.dict(download_mihomo.ASSETS, {"Linux": ("test.gz", sha256(archive), 123)}),
                    patch("urllib.request.OpenerDirector.open", autospec=True, side_effect=open_request),
                    patch("sync.time.sleep"),
                ):
                    if payload == archive:
                        download_mihomo.main()
                        installed = list((root / ".work/bin").iterdir())
                        self.assertEqual([path.read_bytes() for path in installed], [binary])
                    else:
                        with self.assertRaisesRegex(SystemExit, "SHA-256 mismatch"):
                            download_mihomo.main()
                        self.assertFalse((root / ".work/bin").exists())

                self.assertEqual([request.host for request in requests],
                                 ["github.com"] * 3 + ["api.github.com"])
                self.assertEqual(requests[-1].full_url,
                                 "https://api.github.com/repos/MetaCubeX/mihomo/releases/assets/123")
                self.assertEqual(requests[-1].get_header("Accept"), "application/octet-stream")


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
