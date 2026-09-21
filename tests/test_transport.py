"""Exercise the real optional transport through the production fallback interface."""
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from intake import fetch_official


@unittest.skipUnless(importlib.util.find_spec("curl_cffi"), "optional transport not installed")
class TransportTests(unittest.TestCase):
    def test_real_transport_callback_and_redirect_rejection(self):
        # Dependency PR CI installs the pinned wheels before discovering tests.
        from curl_cffi import requests
        import certifi
        self.assertTrue(Path(certifi.where()).is_file())
        payload = b"<html>Verified transport response</html>"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                redirect = self.path == "/redirect"
                self.send_response(302 if redirect else 200)
                self.send_header("Location", "/ok")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        def forbidden(url):
            raise HTTPError(url, 403, "test fallback", {}, None)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original_get = requests.get
        source = {"url": "https://help.openai.com/en/articles/9247338"}
        try:
            for path in ("/ok", "/redirect"):
                local_url = f"http://127.0.0.1:{server.server_port}{path}"
                # Substitute only the destination; libcurl and all production options are real.
                with patch.object(requests, "get", side_effect=lambda _url, **kwargs: original_get(local_url, **kwargs)):
                    if path == "/ok":
                        self.assertEqual(fetch_official(source, forbidden), (payload, "browser-compatible-https"))
                    else:
                        with self.assertRaises(OSError):
                            fetch_official(source, forbidden)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
