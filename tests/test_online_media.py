# -*- coding: utf-8 -*-
"""Network-free regression tests: safe media discovery and user consent."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from online_media import (
    FreeClip, OnlineMediaError, search_free_video, download_free_video,
    _approved_video,
)

GOOD = "https://upload.wikimedia.org/wikipedia/commons/0/00/Example.webm"
BAD = "https://internal.example.local/private.webm"


def result(licence="CC BY 4.0", url=GOOD, mime="video/webm", size=2048):
    return json.dumps({"query": {"pages": {
        "7": {"title": "File:Example.webm", "imageinfo": [{
            "url": url, "mime": mime, "size": size,
            "extmetadata": {"LicenseShortName": {"value": licence},
                            "Artist": {"value": "<b>Example &amp; Co</b>"}},
        }]},
    }}}).encode("utf-8")


class CommonsTests(unittest.TestCase):
    def test_opt_in_required_for_network_search_and_download(self):
        with self.assertRaises(PermissionError):
            search_free_video("птицы", transport=lambda *_: result())
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PermissionError):
                download_free_video([], Path(temp) / "new")

    def test_only_licenced_supported_public_clips_are_returned(self):
        clips = search_free_video("природа", consent=True,
                                  transport=lambda url, maxsize: result())
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].license, "CC BY 4.0")
        self.assertEqual(clips[0].author, "Example & Co")
        self.assertIn("commons.wikimedia.org/wiki/File:", clips[0].page)
        for licence in ("Unknown", "All Rights Reserved", "CC BY-NC 4.0", "CC BY-SA 4.0"):
            self.assertEqual(search_free_video("природа", consent=True,
                             transport=lambda url, maxsize: result(licence=licence)), [])
        self.assertEqual(len(search_free_video("природа", consent=True,
                             transport=lambda url, maxsize: result(licence="CC0 1.0"))), 1)

    def test_untrusted_urls_and_non_video_files_are_rejected(self):
        for url in (BAD, "http://upload.wikimedia.org/wikipedia/commons/a/aa/a.webm",
                    "https://upload.wikimedia.org.evil.com/wikipedia/commons/a.webm",
                    "https://upload.wikimedia.org/wikipedia/commons/a.webm?q=1",
                    "https://user@upload.wikimedia.org/wikipedia/commons/a.webm",
                    "https://upload.wikimedia.org/wikipedia/commons/a/../../private.webm"):
            with self.subTest(url=url):
                self.assertFalse(_approved_video(url, "video/webm"))
        for url in (BAD, "http://upload.wikimedia.org/wikipedia/commons/a.webm"):
            self.assertFalse(search_free_video("priroda", consent=True,
                             transport=lambda *_: result(url=url)))
        self.assertFalse(search_free_video("priroda", consent=True,
                         transport=lambda *_: result(mime="image/jpeg")))

    def test_bad_response_is_bounded(self):
        with self.assertRaises(OnlineMediaError):
            search_free_video("test", consent=True, transport=lambda *_: b"x" * 900001)
        with self.assertRaises(ValueError):
            search_free_video("../" * 40, consent=True)

    def test_download_produces_new_numbered_clips_and_credits(self):
        clip = FreeClip("File:Example.webm", GOOD,
                        "https://commons.wikimedia.org/wiki/File:Example.webm",
                        "CC BY 4.0", 2048, "video/webm")
        webm = bytes.fromhex("1a45dfa3") + b"x" * 2044
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "clips"
            download_free_video([clip], folder, consent=True,
                                transport=lambda *_: webm)
            self.assertEqual((folder / "01.webm").read_bytes(), webm)
            data = json.loads((folder / "SOURCES_AND_LICENSES.json").read_text("utf-8"))
            self.assertEqual(data[0]["url"], GOOD)
            self.assertIn("CC BY", (folder / "CREDITS_RU.md").read_text("utf-8"))
            with self.assertRaises(OnlineMediaError):
                download_free_video([clip], folder, consent=True,
                                    transport=lambda *_: webm)

    def test_download_denies_forged_and_canceled_clips(self):
        bad = FreeClip("Bad", BAD, "https://commons.wikimedia.org", "CC BY 4.0", 2048, "video/webm")
        good = FreeClip("Good", GOOD, "https://commons.wikimedia.org", "CC BY 4.0", 2048, "video/webm")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(OnlineMediaError):
                download_free_video([bad], Path(temp) / "bad", consent=True,
                                    transport=lambda *_: b"x" * 2048)
            with self.assertRaises(OnlineMediaError):
                download_free_video([good], Path(temp) / "invalid", consent=True,
                                    transport=lambda *_: b"<script>" * 270)
            stop = threading.Event(); stop.set()
            with self.assertRaises(OnlineMediaError):
                download_free_video([good], Path(temp) / "stopped", consent=True, cancel=stop)

if __name__ == "__main__":
    unittest.main()
