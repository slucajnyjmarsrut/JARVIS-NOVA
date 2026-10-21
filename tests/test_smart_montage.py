# -*- coding: utf-8 -*-
"""Automated footage scoring/output checks, deterministic and entirely offline."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from smart_montage import (
    FRAME_BYTES, MAX_ANALYSIS_SECONDS, MontageQualityError, _frame_scores,
    best_start, choose_highlight_start, verify_output_media, caption_subtitles,
)


class SmartMontageTests(unittest.TestCase):
    def test_selects_content_over_blank_starts(self):
        black = bytes([0]) * FRAME_BYTES
        # Detailed, exposed scene (alternating luminance).
        interesting = bytes([65 if i%2 else 180 for i in range(FRAME_BYTES)])
        scores = _frame_scores(black*6 + interesting*12)
        self.assertEqual(len(scores),18)
        self.assertLess(max(scores[:6]),min(scores[7:]))
        start = best_start(scores,9.,3.,fps=2)
        self.assertGreaterEqual(start,2.5)
        self.assertLessEqual(start,6.)

    def test_srt_captions_align_with_cuts_and_reject_bad_lengths(self):
        captions=caption_subtitles([
            {"seconds":2.5,"on_screen":"  ПРИВЕТ  МИР  "},
            {"seconds":1.,"on_screen":"Второй кадр"},
        ])
        self.assertIn("00:00:00,000 --> 00:00:02,500",captions)
        self.assertIn("00:00:02,500 --> 00:00:03,500",captions)
        self.assertIn("ПРИВЕТ МИР",captions)
        with self.assertRaises(MontageQualityError):
            caption_subtitles([{"seconds":float("nan"),"on_screen":"ошибка"}])
        with self.assertRaises(MontageQualityError):
            caption_subtitles([{"seconds":2.,"on_screen":""}])

    def test_safe_bounded_selection_and_fallback(self):
        self.assertEqual(best_start([.5]*20,2.,2.5),0.)
        self.assertEqual(best_start([.5],9.,2.),0.)
        with self.assertRaises(MontageQualityError):
            _frame_scores(b"x"*3)
        with self.assertRaises(MontageQualityError):
            _frame_scores(bytes(FRAME_BYTES*(MAX_ANALYSIS_SECONDS+3)*2))
        self.assertEqual(choose_highlight_start(Path("test.mp4"),12.,3.,"ffmpeg",
            executor=lambda *_a,**_kw: (_ for _ in ()).throw(OSError("offline"))),.15)

    def test_highlight_uses_only_bounded_local_ffmpeg(self):
        calls=[]
        good = bytes([128 if i%3 else 200 for i in range(FRAME_BYTES)])
        def executor(argv,**kwargs):
            calls.append((argv,kwargs))
            return bytes(FRAME_BYTES)*5+good*20
        start=choose_highlight_start(Path("clip.mp4"),18000.,4.,"local-ffmpeg",executor=executor)
        self.assertGreater(start,1)
        self.assertEqual(calls[0][0][0],"local-ffmpeg")
        self.assertLessEqual(float(calls[0][0][calls[0][0].index("-t")+1]),75.)
        self.assertNotIn("http",repr(calls))
        canceled=threading.Event();canceled.set()
        with self.assertRaises(MontageQualityError):
            choose_highlight_start(Path("clip.mp4"),12.,2.,"ffmpeg",cancel=canceled,
                                  executor=lambda *_a,**_kw: self.fail("called"))

    def test_technical_output_accepts_only_vertical_h264_and_aac(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"out.mp4"
            file.write_bytes(b"x"*2048)
            def sample(codec="h264",sound="aac",width=720,height=1280,duration=8.):
                return json.dumps({"streams":[
                    {"codec_type":"video","codec_name":codec,
                     "width":width,"height":height},
                    {"codec_type":"audio","codec_name":sound}],
                    "format":{"duration":str(duration)}}).encode()
            good=verify_output_media(file,"ffprobe",8.,executor=lambda *_a,**_kw:sample())
            self.assertTrue(good["quality_checked"])
            self.assertEqual(good["audio_codec"],"aac")
            for payload in [sample(codec="mpeg4"),sample(sound="mp3"),
                            sample(width=1280,height=720),sample(duration=19.),
                            b"not-json",json.dumps({"streams":[]}).encode()]:
                with self.subTest(payload=payload[:55]),self.assertRaises(MontageQualityError):
                    verify_output_media(file,"ffprobe",8.,executor=lambda *_a,**_kw:payload)


if __name__ == "__main__":
    unittest.main()
