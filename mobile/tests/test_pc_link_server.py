"""Read-only PC link security policy tests (no certificates/network needed)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pc_link_server import private_bind_address, read_pair_token, make_handler


class PcLinkTests(unittest.TestCase):
    def test_only_private_ip_bind(self):
        for address in ("192.168.1.22", "172.16.0.5", "10.0.0.1", "127.0.0.1"):
            self.assertEqual(private_bind_address(address), address)
        for address in ("0.0.0.0", "8.8.8.8", "1.1.1.1", "example.com", "::1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                private_bind_address(address)

    def test_pair_token_must_be_256_bits(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "token"
            for content in ("short", "g" * 64, "secret password"):
                f.write_text(content)
                with self.assertRaises(ValueError):
                    read_pair_token(f)
            f.write_text("A" * 64)
            self.assertEqual(read_pair_token(f), "a" * 64)

    def test_handler_does_not_expose_remote_methods(self):
        handler = make_handler("a" * 64)
        self.assertTrue(callable(handler.do_GET))
        self.assertTrue(callable(handler.do_POST))
        self.assertFalse(hasattr(handler, "do_PUT"))
        self.assertFalse(hasattr(handler, "do_DELETE"))


if __name__ == "__main__":
    unittest.main()
