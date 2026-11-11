# -*- coding: utf-8 -*-
"""Audio-aware long-form edit selection without speech recognition or uploads."""
from array import array
from pathlib import Path
import tempfile
import threading
import unittest

from audio_highlight_signal import audio_activity, sample_audio_activity
from smart_highlight_selection import (
    FRAME_BYTES, select_active_cuts)
from video_timeline import draft_longform_cuts


def pcm(value):
    return array("h", [value,-value]*4000).tobytes()


class AudioHighlightTests(unittest.TestCase):
    def test_loudness_is_bounded_and_silence_is_not_highlight(self):
        self.assertEqual(audio_activity(b""),0.)
        self.assertEqual(audio_activity(pcm(0)),0.)
        self.assertGreater(audio_activity(pcm(3000)),.4)
        self.assertGreater(audio_activity(pcm(3000)),audio_activity(pcm(150)))
        self.assertGreater(audio_activity(pcm(150)),0.)
        for broken in (b"abc", b"x"*40000, "sound"):
            with self.subTest(broken=str(type(broken))):
                with self.assertRaises(ValueError):
                    audio_activity(broken)

    def test_audio_saves_quiet_dialogue_windows_in_two_hour_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"recording.mp4"
            source.write_bytes(b"x"*4096)
            seen=[]
            static=bytes([110])*(3*FRAME_BYTES)
            loud=pcm(3500)
            silent=pcm(0)
            def executor(args,*,timeout,cancel):
                position=float(args[args.index("-ss")+1])
                if args[-2]=="s16le":
                    seen.append(("audio",position))
                    return loud if position%300>185 else silent
                self.assertEqual(args[-2],"rawvideo")
                seen.append(("video",position))
                return static
            baseline=draft_longform_cuts(((source,7200.),))
            cuts,report=select_active_cuts(
                ((source,7200.),),ffmpeg="ffmpeg",executor=executor,
                audio_sources={source:True},max_audio_windows=96)
            self.assertEqual(len(cuts),len(baseline))
            self.assertGreater(
                sum(c.source_start>b.source_start+70
                    for c,b in zip(cuts,baseline)),
                len(cuts)//2)
            self.assertAlmostEqual(sum(c.duration for c in cuts),900.,delta=.05)
            self.assertEqual(report.method,"local-motion-and-audio")
            self.assertGreater(report.audio_usable,60)
            self.assertLessEqual(report.audio_examined,96)
            self.assertEqual(report.audio_examined,report.audio_usable)
            self.assertEqual(
                sum(kind=="audio" for kind,_ in seen),report.audio_examined)

    def test_silent_or_broken_audio_cannot_break_video_selection(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"film.mp4"
            f.write_bytes(b"x"*4000)
            attempts=[]
            def execute(args,*,timeout,cancel):
                if args[-2]=="s16le":
                    attempts.append("audio")
                    raise RuntimeError("Unsupported audio track")
                return bytes([110])*(3*FRAME_BYTES)
            selected,report=select_active_cuts(
                ((f,7200.),),ffmpeg="ffmpeg",executor=execute,
                audio_sources={f:True},max_audio_windows=5)
            self.assertEqual(report.audio_examined,5)
            self.assertEqual(report.audio_usable,0)
            self.assertEqual(report.fallback,0)
            self.assertEqual(selected,draft_longform_cuts(((f,7200.),)))
            self.assertEqual(len(attempts),5)

    def test_cancelled_audio_does_not_fall_back_or_export(self):
        cancel=threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            sample_audio_activity(
                Path("anything.mp4"),0,ffmpeg="ffmpeg",
                executor=lambda *a,**k:self.fail("No decoder should run"),
                cancel=cancel)

    def test_audio_is_never_decoded_if_not_confirmed_by_probe(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"noaudio.mp4"
            f.write_bytes(b"x"*3000)
            all_video=[]
            def runner(args,**kwargs):
                self.assertNotIn("s16le",args)
                all_video.append(args)
                return bytes([110])*(3*FRAME_BYTES)
            cuts,report=select_active_cuts(
                ((f,7200.),),ffmpeg="ffmpeg",executor=runner,
                audio_sources={f:False})
            self.assertFalse(report.audio_examined)
            self.assertEqual(report.method,"local-grayscale-motion")
            self.assertTrue(all_video)
            self.assertEqual(len(cuts),len(draft_longform_cuts(((f,7200.),))))


if __name__=="__main__":
    unittest.main()
