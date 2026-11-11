# -*- coding: utf-8 -*-
"""Quality and safety of local, bounded scene activity selection."""
from pathlib import Path
import tempfile
import threading
import unittest

from smart_highlight_selection import (
    FRAME_BYTES, frame_activity, select_active_cuts)
from video_timeline import draft_longform_cuts


class SceneSelectionTests(unittest.TestCase):
    def test_activity_prefers_motion_over_static_and_black(self):
        still=bytes([110])*(3*FRAME_BYTES)
        moving=(bytes([10])+bytes([240])+bytes([10]))
        moving=(bytes([10])*FRAME_BYTES +
                bytes([240])*FRAME_BYTES + bytes([10])*FRAME_BYTES)
        black=bytes(3*FRAME_BYTES)
        self.assertGreater(frame_activity(moving),frame_activity(still)+.25)
        self.assertLess(frame_activity(black),frame_activity(still))
        for damaged in (b"", b"123",b"x"*(FRAME_BYTES*4)):
            with self.assertRaises(ValueError):
                frame_activity(damaged)

    def test_two_hour_highlight_selection_uses_local_scene_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"source.mp4"
            file.write_bytes(b"x"*3000)
            baseline=draft_longform_cuts(((file,7200.),),target_seconds=900.)
            observed=[]
            progress=[]
            moving=(bytes([30])*FRAME_BYTES +
                    bytes([210])*FRAME_BYTES + bytes([30])*FRAME_BYTES)
            static=bytes([110])*(3*FRAME_BYTES)
            def runner(cmd,*,timeout,cancel):
                self.assertEqual(cmd[0],"ffmpeg")
                self.assertIn("-frames:v",cmd)
                self.assertIn("-ss",cmd)
                self.assertEqual(timeout,25)
                at=float(cmd[cmd.index("-ss")+1])
                observed.append(at)
                return moving if at%300>180 else static
            cuts,report=select_active_cuts(
                ((file,7200.),),target_seconds=900.,
                ffmpeg="ffmpeg",executor=runner,
                progress=lambda *args:progress.append(args))
            self.assertEqual(len(cuts),len(baseline))
            self.assertTrue(any(c.source_start>b.source_start+50
                                for c,b in zip(cuts,baseline)))
            self.assertAlmostEqual(sum(c.duration for c in cuts),900.,delta=.05)
            self.assertLessEqual(report.examined,192)
            self.assertEqual(report.examined,len(observed))
            self.assertEqual(report.usable,len(observed))
            self.assertEqual(progress[-1][0],len(cuts))
            self.assertTrue(all(0<=c.source_start
                                and c.source_start+c.duration<=7200.001
                                for c in cuts))

    def test_errors_fall_back_without_lying_about_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"source.mp4"
            p.write_bytes(b"x"*3000)
            expected=draft_longform_cuts(((p,7200.),),target_seconds=900.)
            def corrupted(*a,**kw):
                raise OSError("codec not supported")
            actual,report=select_active_cuts(
                ((p,7200.),),ffmpeg="ffmpeg",executor=corrupted)
            self.assertEqual(actual,expected)
            self.assertEqual(report.usable,0)
            self.assertEqual(report.fallback,len(expected))
            self.assertLessEqual(report.examined,192)

    def test_cancel_or_small_sampling_budget_never_overflows(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"source.mp4"
            p.write_bytes(b"x"*3000)
            stop=threading.Event()
            stop.set()
            with self.assertRaises(InterruptedError):
                select_active_cuts(
                    ((p,7200.),),ffmpeg="ffmpeg",
                    executor=lambda *a,**k:self.fail("Cancelled request"),
                    cancel=stop)
            calls=[]
            def runner(*args,**kw):
                calls.append(args)
                return bytes([110])*(FRAME_BYTES*3)
            cuts,report=select_active_cuts(
                ((p,7200.),),ffmpeg="ffmpeg",executor=runner,
                max_windows=5)
            self.assertEqual(len(calls),5)
            self.assertEqual(report.examined,5)
            self.assertEqual(len(cuts),len(draft_longform_cuts(((p,7200.),)))


if __name__=="__main__":
    unittest.main()
