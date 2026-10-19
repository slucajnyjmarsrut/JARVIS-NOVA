"""Explicit opt-in LAN HTTPS status endpoint for JARVIS NOVA Mobile.

NOT a remote desktop or speech-control server. It never starts with JARVIS.
Pairing requires a pre-shared 256-bit token and pinned certificate fingerprint.
Supply a TLS certificate with subjectAltName matching the PC's private IPv4.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import secrets
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ALLOWED = tuple(ipaddress.ip_network(n) for n in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))


def private_bind_address(raw: str) -> str:
    address = ipaddress.ip_address(raw)
    if address.version != 4 or not any(address in net for net in _ALLOWED):
        raise ValueError("Use a numeric private IPv4 address or 127.0.0.1")
    return str(address)


def read_pair_token(path: str | Path) -> str:
    token = Path(path).read_text(encoding="ascii").strip()
    if len(token) != 64 or any(c not in "0123456789abcdefABCDEF" for c in token):
        raise ValueError("Token file must contain exactly 64 hex digits (256 bits)")
    return token.lower()


def cert_pin_sha256(path: str | Path) -> str:
    pem = Path(path).read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return hashlib.sha256(der).hexdigest()


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JarvisPcLink/0.1"
        sys_version = ""

        def log_message(self, format, *args):
            # Never print Authorization headers, addresses or paired-device tokens.
            return

        def respond(self, code: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/v1/status":
                self.respond(404, {"error": "not_found"})
                return
            expected = "Bearer " + token
            provided = self.headers.get("Authorization", "")
            if not secrets.compare_digest(provided, expected):
                self.respond(401, {"error": "unauthorized"})
                return
            self.respond(200, {"name": "JARVIS NOVA PC", "protocol": 1, "status": "online"})

        def do_POST(self):
            # No remote execution, file transfer, screenshots or phone actions.
            self.respond(405, {"error": "read_only"})

    return Handler


def serve(bind: str, port: int, cert: str, key: str, token_file: str):
    host = private_bind_address(bind)
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    token = read_pair_token(token_file)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert, keyfile=key)
    server = ThreadingHTTPServer((host, port), make_handler(token))
    server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"JARVIS PC Link status-only HTTPS on https://{host}:{port}")
    print("Leaf certificate SHA256 pin:", cert_pin_sha256(cert))
    print("Never share the pairing token or private key. Ctrl+C stops the server.")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explicit local HTTPS status server")
    parser.add_argument("--bind", required=True, help="Private numeric IPv4")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", required=True, help="PEM certificate with IPv4 SAN")
    parser.add_argument("--key", required=True, help="Private PEM key")
    parser.add_argument("--token-file", required=True, help="File containing 64 hex digits")
    options = parser.parse_args()
    serve(options.bind, options.port, options.cert, options.key, options.token_file)
