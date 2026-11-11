# -*- coding: utf-8 -*-
"""Semantic video assist cannot change timeline length, access cloud or run code."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from semantic_video_selection import (
    MAX_PAIRS, _chosen_label, review_longform_offsets)
from video_timeline import draft_longform_cuts


def jpeg(value):
    image=Image.new("RGB",(240,136),(value,70,90))
    buffer=BytesIO()
    image.save(buffer,format="JPEG",quality=70)
    return buffer.getvalue()


class SemanticTimelineTests(unittest.TestCase):
    def project(self,folder):
        path=Path(folder)/"two_hours.mp4"
        path.write_bytes(b"x"*4000)
        sources=((path,7200.),)
        baseline=draft_longform_cuts(sources,target_seconds=900)
        candidates=tuple(replace(c,source_start=c.source_start+45.)
                         for c in baseline)
        return sources,baseline,candidates

    def test_real_vision_object_can_only_pick_existing_safe_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources,base,candidates=self.project(tmp)
            calls=[]
            def decode(argv,*,timeout,cancel):
                self.assertIn("-frames:v",argv)
                self.assertIn("mjpeg",argv)
                self.assertEqual(timeout,22)
                calls.append(("ffmpeg",argv[argv.index("-ss")+1]))
                return jpeg(120)
            class FakeVision:
                def describe(self,question,data):
                    self_outer.assertTrue(data.startswith(b"\xff\xd8\xff"))
                    self_outer.assertTrue(data.endswith(b"\xff\xd9"))
                    self_outer.assertIn("одной латинской",question.casefold())
                    calls.append(("vision",len(data)))
                    return "B"
            self_outer=self
            result,report=review_longform_offsets(
                candidates,sources,target_seconds=900,ffmpeg="ffmpeg",
                executor=decode,vision=FakeVision(),confirmed=True)
            self.assertEqual(report.compared,MAX_PAIRS)
            self.assertEqual(report.chosen_alternative,MAX_PAIRS)
            self.assertEqual(report.failed,0)
            self.assertEqual(len(result),len(base))
            self.assertEqual(sum(c.duration for c in result),900.)
            self.assertEqual(sum(x[0]=="vision" for x in calls),MAX_PAIRS)
            self.assertEqual(sum(x[0]=="ffmpeg" for x in calls),2*MAX_PAIRS)
            self.assertTrue(all(
                x.source_start in (a.source_start,b.source_start)
                for x,a,b in zip(result,candidates,base)))
            self.assertEqual(len(list(Path(tmp).iterdir())),1)
            self.assertEqual(
                Path(tmp,"two_hours.mp4").read_bytes(),b"x"*4000)

    def test_permission_or_invalid_vision_cannot_decode_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources,baseline,candidates=self.project(tmp)
            runner=lambda *a,**k:self.fail("Not authorized to sample frames")
            with self.assertRaises(PermissionError):
                review_longform_offsets(
                    candidates,sources,target_seconds=900,
                    ffmpeg="ffmpeg",executor=runner,vision=object())
            with self.assertRaises(ValueError):
                review_longform_offsets(
                    candidates,sources,target_seconds=900,
                    ffmpeg="ffmpeg",executor=runner,vision=object(),
                    confirmed=True)

    def test_ambiguous_ai_or_ffmpeg_failure_leaves_previous_motion_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources,base,candidates=self.project(tmp)
            class Ambiguous:
                def describe(self,*args):
                    return "I would prefer B because"
            actual,report=review_longform_offsets(
                candidates,sources,target_seconds=900,ffmpeg="ffmpeg",
                executor=lambda *args,**kwargs:jpeg(120),
                vision=Ambiguous(),confirmed=True)
            self.assertEqual(actual,candidates)
            self.assertEqual(report.compared,0)
            self.assertEqual(report.failed,MAX_PAIRS)
            actual,report=review_longform_offsets(
                candidates,sources,target_seconds=900,ffmpeg="ffmpeg",
                executor=lambda *args,**kw:(_ for _ in ()).throw(
                    OSError("damaged clip")),vision=Ambiguous(),
                confirmed=True)
            self.assertEqual(actual,candidates)
            self.assertEqual(report.failed,MAX_PAIRS)

    def test_only_two_strict_vision_tokens_accepted(self):
        self.assertEqual(_chosen_label("B"),"B")
        self.assertEqual(_chosen_label(" a! "),"A")
        for response in ("A or B","Option B","A; delete files",
                         "",None,"B "+("x"*500)):
            self.assertIsNone(_chosen_label(response))

    def test_cancelled_or_damaged_timeline_blocks_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources,baseline,candidates=self.project(tmp)
            stop=threading.Event()
            stop.set()
            class UnusedVision:
                def describe(self,*args):
                    self_outer.fail("Cancelled, must not call the model.")
            self_outer=self
            with self.assertRaises(InterruptedError):
                review_longform_offsets(
                    candidates,sources,target_seconds=900,
                    ffmpeg="ffmpeg",executor=lambda *a,**k:self.fail(),
                    vision=UnusedVision(),confirmed=True,cancel=stop)
            changed=(replace(candidates[0],duration=42),*candidates[1:])
            with self.assertRaises(ValueError):
                review_longform_offsets(
                    changed,sources,target_seconds=900,ffmpeg="ffmpeg",
                    executor=lambda *a,**k:self.fail(),
                    vision=object(),confirmed=True)

    def test_real_pillow_jpeg_composite_does_not_touch_disk(self):
        from semantic_video_selection import _paired_jpeg
        first=Image.new("RGB",(240,136),"black")
        second=Image.new("RGB",(240,136),"white")
        data=_paired_jpeg(first,second)
        self.assertLess(len(data),250000)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size,(480,164))


class SemanticUIConsentTests(unittest.TestCase):
    def _drive(self, *, ready):
        from unittest import mock
        from types import SimpleNamespace
        from video_timeline_ui import TimelineWindow
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"footage.mp4"
            source.write_bytes(b"x"*4096)
            cuts=draft_longform_cuts(((source,7200.),),target_seconds=900)
            runtime=mock.Mock()
            runtime.config.model="qwen3-vl:2b-instruct"
            runtime.start.return_value="http://127.0.0.1:42567"
            win=mock.Mock()
            win.master=SimpleNamespace(
                _local_model_ready=ready,runtime=runtime)
            win._busy=False
            win._auto_export_token=None
            win._cancel=threading.Event()
            win._events=__import__("queue").Queue()
            analysis=__import__("types").SimpleNamespace(
                examined=6,usable=6,fallback=0,
                audio_examined=6,audio_usable=6)
            semantic=__import__("types").SimpleNamespace(
                compared=6,chosen_alternative=2,failed=0)
            with mock.patch("video_timeline_ui.filedialog.askopenfilenames",
                            return_value=(str(source),)), \
                 mock.patch("video_timeline_ui.messagebox.askyesno",
                            return_value=True) as consent, \
                 mock.patch("video_timeline_ui.threading.Thread") as thread, \
                 mock.patch("viral_studio.ffmpeg_tools",
                            return_value=("ffmpeg","ffprobe")), \
                 mock.patch("viral_studio._probe",return_value=(7200,True)), \
                 mock.patch("smart_highlight_selection.select_active_cuts",
                            return_value=(cuts,analysis)), \
                 mock.patch("semantic_video_selection.review_longform_offsets",
                            return_value=(cuts,semantic)) as review, \
                 mock.patch("vision_engine.LocalOllamaVision") as vision:
                TimelineWindow.prepare_longform(win,auto_export=True)
                consent.assert_called_once()
                self.assertIsNotNone(win._auto_export_token)
                thread.return_value.start.assert_called_once()
                thread.call_args.kwargs["target"]()
                event,payload=win._events.get_nowait()
                self.assertEqual(event,"longform")
                self.assertEqual(len(payload),5)
                self.assertEqual(payload[3],win._auto_export_token)
                if ready:
                    review.assert_called_once()
                    self.assertTrue(review.call_args.kwargs["confirmed"])
                    vision.return_value.initialize.assert_called_once()
                    self.assertIs(payload[-1],semantic)
                else:
                    review.assert_not_called()
                    vision.assert_not_called()
                    self.assertIsNone(payload[-1])

    def test_only_one_permission_can_launch_local_vision(self):
        self._drive(ready=True)

    def test_missing_qwen_uses_motion_and_audio_without_model_call(self):
        self._drive(ready=False)


if __name__=="__main__":
    unittest.main()
