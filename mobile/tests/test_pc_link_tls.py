"""Actual loopback TLS handshake + bearer auth. Does NOT require Android hardware."""
from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pc_link_server import make_handler, cert_pin_sha256


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI unavailable")
class RealTlsServerTests(unittest.TestCase):
    def test_tls_authentication_and_read_only_status(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cert = base / "cert.pem"
            key = base / "private.key"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-sha256", "-days", "1", "-nodes",
                "-keyout", str(key), "-out", str(cert),
                "-subj", "/CN=Jarvis PC Test",
                "-addext", "subjectAltName=IP:127.0.0.1",
            ], check=True, capture_output=True, timeout=30)
            self.assertEqual(len(cert_pin_sha256(cert)), 64)

            token = "a" * 64
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(token))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                endpoint = f"https://127.0.0.1:{port}/v1/status"
                verify = ssl.create_default_context(cafile=str(cert))
                good = urllib.request.Request(endpoint, headers={"Authorization": "Bearer " + token})
                with urllib.request.urlopen(good, context=verify, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read())
                    self.assertEqual(payload["status"], "online")
                    self.assertEqual(payload["protocol"], 1)
                for bad in ("", "Bearer wrong", "Bearer " + "b" * 64):
                    request = urllib.request.Request(endpoint, headers={"Authorization": bad})
                    with self.subTest(header=bad[:12]), self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(request, context=verify, timeout=5)
                    self.assertEqual(raised.exception.code, 401)
                post = urllib.request.Request(endpoint, method="POST", data=b"{}")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(post, context=verify, timeout=5)
                self.assertEqual(raised.exception.code, 405)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
