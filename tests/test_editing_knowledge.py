# -*- coding: utf-8 -*-
"""Read-only official FFmpeg learning: no remote code execution."""
import unittest
from editing_knowledge import read_ffmpeg_guide, EditingGuideError, FFMPEG_URL

HTML = ("""
<html><script>malicious_run();</script><style>.x{color:red}</style>
<body>FFmpeg documentation shows options for editing video streams and audio.
This help page explains how to select filters and codecs safely.
<p>-ss seek into a video input to select a portion.</p>
<p>-map chooses output streams.</p>
<p>-codec chooses which codec will encode each output.</p>
<p>-filter_complex can combine many audio and video filter graphs.</p>
""" + "Additional explanatory documentation. " * 30 + "</body></html>").encode()


class DocumentationTests(unittest.TestCase):
    def test_refuses_implicit_internet_and_bad_responses(self):
        with self.assertRaises(PermissionError):
            read_ffmpeg_guide(transport=lambda *_: HTML)
        with self.assertRaises(EditingGuideError):
            read_ffmpeg_guide(consent=True, transport=lambda *_: b"small")
        with self.assertRaises(EditingGuideError):
            read_ffmpeg_guide(consent=True, transport=lambda *_: b"x" * 2_000_001)

    def test_fixed_allowlisted_reference_no_commands_executed(self):
        endpoints=[]
        text=read_ffmpeg_guide(consent=True,
             transport=lambda url: (endpoints.append(url), HTML)[1])
        self.assertEqual(endpoints, [FFMPEG_URL])
        self.assertIn("-filter_complex", text)
        self.assertIn("-codec", text)
        self.assertIn("ffmpeg.org", text)
        self.assertNotIn("malicious_run()", text)
        self.assertLessEqual(len(text), 5000)

if __name__ == "__main__":
    unittest.main()
