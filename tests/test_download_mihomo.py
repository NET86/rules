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


if __name__ == "__main__":
    unittest.main()
