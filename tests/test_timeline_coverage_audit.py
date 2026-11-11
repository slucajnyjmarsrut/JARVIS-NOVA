# -*- coding: utf-8 -*-
"""All-period diagnostics for a finished 15-minute MP4, not just its intro."""
from array import array
from pathlib import Path
import tempfile
import threading
import unittest

from video_frame_audit import FRAME_BYTES, FrameAuditError
from video_audio_audit import AudioAuditError
from timeline_coverage_audit import audit_coverage


class TimelineCoverageTests(unittest.TestCase):
    def test_samples_start_middle_and_end_without_full_decode(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"finished.mp4"
            file.write_bytes(b"x"*4096)
            positions=[]
            def fake(args,*,timeout,cancel):
                self.assertEqual(args[0],"ffmpeg")
                start=float(args[args.index("-ss")+1])
                positions.append(start)
                self.assertEqual(args[args.index("-t")+1],"3.000")
                if args[-2]=="rawvideo":
                    return (bytes(FRAME_BYTES*9) if start>=800
                            else bytes([110])*(FRAME_BYTES*9))
                self.assertEqual(args[-2],"s16le")
                return array("h",[1000,-1000]*12000).tobytes()
            report=audit_coverage(
                file,900.,ffmpeg="ffmpeg",executor=fake)
            self.assertTrue(report["checked"])
            self.assertEqual(len(report["regions"]),5)
            self.assertEqual(positions[0],0.)
            self.assertEqual(positions[-1],897.)
            self.assertEqual(len(positions),10)
            self.assertEqual(sum(x["black_fraction"]>.9
                                 for x in report["regions"]),1)
            self.assertTrue(any("чёрный" in x for x in report["warnings"]))

    def test_explicit_cancel_stops_before_any_read(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"sample.mp4"
            file.write_bytes(b"x"*4096)
            cancel=threading.Event()
            cancel.set()
            with self.assertRaises(InterruptedError):
                audit_coverage(
                    file,900.,ffmpeg="ffmpeg",cancel=cancel,
                    executor=lambda *a,**k:self.fail("Cancelled"))

    def test_corrupt_video_or_audio_cannot_claim_success(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"sample.mp4"
            file.write_bytes(b"x"*4096)
            def broken_video(*args,**kwargs):
                return b"x"
            with self.assertRaises(FrameAuditError):
                audit_coverage(
                    file,900.,ffmpeg="ffmpeg",executor=broken_video)
            def broken_audio(args,**kwargs):
                return (bytes([80])*FRAME_BYTES*9
                        if args[-2]=="rawvideo" else b"abc")
            with self.assertRaises(AudioAuditError):
                audit_coverage(
                    file,900.,ffmpeg="ffmpeg",executor=broken_audio)

    def test_invalid_bounds_do_not_launch_ffmpeg(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"sample.mp4"
            file.write_bytes(b"x"*4096)
            for duration in (float("nan"),float("inf"),-3,0):
                with self.subTest(duration=duration),self.assertRaises(ValueError):
                    audit_coverage(file,duration,ffmpeg="ffmpeg",
                                   executor=lambda *a,**k:self.fail("No run"))
            for window_count in (0,1,6,900,"5"):
                with self.subTest(windows=window_count),self.assertRaises(ValueError):
                    audit_coverage(file,900.,ffmpeg="ffmpeg",
                                   windows=window_count,
                                   executor=lambda *a,**k:self.fail("No run"))


if __name__=="__main__":
    unittest.main()
