# -*- coding: utf-8 -*-
"""No-network regression for post-render frame, audio and combined quality checks."""
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from video_frame_audit import (FRAME_BYTES, FrameAudit, FrameAuditError,
                               analyze_gray_frames, inspect_video_frames)
from video_audio_audit import (AudioAudit, AudioAuditError, analyze_pcm16,
                               inspect_audio, SAMPLE_RATE)
from video_quality_gate import audit_finished_media, combine_quality


def samples(*blocks):
    data=array("h")
    for value, count in blocks:
        data.extend([value]*count)
    return data.tobytes()


class MediaQualityTests(unittest.TestCase):
    def test_black_and_white_scenes_get_measured_not_guessed(self):
        dark=bytes(FRAME_BYTES)
        bright=bytes([255])*FRAME_BYTES
        scene=bytes([100 if i%2 else 180 for i in range(FRAME_BYTES)])
        report=analyze_gray_frames(dark*6+bright*6+scene*10)
        self.assertGreater(report.black_fraction,.2)
        self.assertGreater(report.white_fraction,.2)
        self.assertEqual(report.sampled_frames,22)
        self.assertIn("Много очень тёмных или чёрных кадров",report.warnings)
        self.assertIn("Много засвеченных или белых кадров",report.warnings)

    def test_static_footage_warning_not_always_real_video_failure(self):
        frame=bytes([100])*FRAME_BYTES
        result=analyze_gray_frames(frame*19)
        self.assertGreaterEqual(result.longest_static_seconds,4)
        self.assertIn("статичный",result.warnings[0])
        with self.assertRaises(FrameAuditError):
            analyze_gray_frames(b"x")
        with self.assertRaises(FrameAuditError):
            analyze_gray_frames(bytes(FRAME_BYTES*235))

    def test_audio_silence_clipping_energy_and_duration(self):
        silence=analyze_pcm16(samples((0,SAMPLE_RATE*2)))
        self.assertEqual(silence.quiet_fraction,1.)
        self.assertLess(silence.rms_dbfs,-90)
        self.assertIn("тихая",silence.warnings[0])
        clipped=analyze_pcm16(samples((32767,500),(-32768,500),
                                      (5000,8000)))
        self.assertGreater(clipped.clipped_fraction,.002)
        self.assertIn("перегрузка", " ".join(clipped.warnings))
        with self.assertRaises(AudioAuditError):
            analyze_pcm16(b"\x01")
        with self.assertRaises(AudioAuditError):
            analyze_pcm16(b"")

    def test_combiner_marks_uncertainty_and_penalties(self):
        video=FrameAudit(9,3.,.3,.2,4.5,("Есть чернота","Статично"))
        audio=AudioAudit(3.,-96.,-96.,1.,0.,("Тишина",))
        result=combine_quality(video,audio)
        self.assertTrue(result.checked)
        self.assertEqual(result.penalty,30)
        self.assertIn("Тишина",result.warnings)
        self.assertLessEqual(result.penalty,30)

    def test_offline_ffmpeg_only_and_cancel_both_stages(self):
        with TemporaryDirectory() as temp:
            video=Path(temp)/"result.mp4"
            video.write_bytes(b"0"*2048)
            calls=[]
            movie=bytes([100 if i%2 else 170 for i in range(FRAME_BYTES)])*9
            audio=samples((4000,8000))
            def exec_(argv,**kwargs):
                calls.append(list(argv))
                return movie if "-pix_fmt" in argv else audio
            assessment=audit_finished_media(video,ffmpeg="ffmpeg",executor=exec_)
            self.assertTrue(assessment.checked)
            self.assertEqual(assessment.penalty,0)
            self.assertEqual(len(calls),2)
            self.assertTrue(all(call[0]=="ffmpeg" for call in calls))
            self.assertTrue(all("http" not in " ".join(call) for call in calls))
            stopped=threading.Event();stopped.set()
            with self.assertRaises(FrameAuditError):
                inspect_video_frames(video,"ffmpeg",cancel=stopped,executor=exec_)
            with self.assertRaises(AudioAuditError):
                inspect_audio(video,"ffmpeg",cancel=stopped,executor=exec_)
            self.assertEqual(len(calls),2)
            with self.assertRaises(ValueError):
                audit_finished_media(Path(temp)/"missing.mp4",ffmpeg="ffmpeg",executor=exec_)

    def test_cancel_after_video_decode_cannot_continue_to_audio(self):
        event=threading.Event()
        def executor(argv,**kwargs):
            event.set()
            return bytes([127])*FRAME_BYTES*3
        with self.assertRaises(FrameAuditError):
            inspect_video_frames(Path("movie.mp4"),"ffmpeg",cancel=event,
                                 executor=executor)


if __name__=="__main__":
    unittest.main()
