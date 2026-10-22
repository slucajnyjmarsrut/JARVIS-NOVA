# -*- coding: utf-8 -*-
"""Offline test: evidence-bound viewing metrics, reviewer and non-destructive recuts."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest

from channel_audience import VideoMetric
from post_montage_review import (analyze_and_recut, revised_brief,
                                 MontageReviewError)
from video_forecast import FinalReview
from viral_studio import Brief, Shot, template_brief


def slow_brief():
    original=template_brief("Камеры")
    shots=list(original.shots)
    shots[0]=Shot(10,"Покажи камеру","Смотри какая камера с очень длинной надписью " +
                  "не успеешь прочитать это предложение на экране вообще")
    shots[1]=Shot(10,shots[1].film,shots[1].caption)
    return Brief(original.title,original.topic,original.hook,original.script,
                 tuple(shots),original.call_to_action,original.generator)


def renderer_factory(calls, fail_second=False):
    def render(brief, raw, path, *, cancel=None):
        calls.append((brief,path))
        if fail_second and len(calls)==2:
            raise OSError("broken FFmpeg")
        Path(path).write_bytes(b"FAKE"*700)
        return {"duration":round(sum(s.seconds for s in brief.shots),2),
                "output":str(path),
                "technical_quality":{"quality_checked":True,"audio_codec":"aac","video_codec":"h264"},
                "segments":[{"seconds":s.seconds} for s in brief.shots]}
    return render


class PostMontageReviewTests(unittest.TestCase):
    def test_bad_pacing_gets_real_second_export_and_explains_why(self):
        calls=[]
        with TemporaryDirectory() as td:
            root=Path(td)
            output=analyze_and_recut(slow_brief(),root,root,renderer=renderer_factory(calls))
            self.assertEqual(len(calls),2)
            self.assertEqual(output.output.name,"JARVIS_NOVA_AUTO_VERTICAL_V2.mp4")
            self.assertGreater(output.attempts[1].structure_score,output.attempts[0].structure_score)
            self.assertTrue(all(x[1].exists() for x in calls))
            self.assertIn("Я сделал",output.speech)
            data=json.loads((root/"POST_MONTAGE_REVIEW.json").read_text("utf-8"))
            self.assertFalse(data["viewer_metrics_are_predictions"])
            self.assertEqual(data["historical_channel_data"]["status"],"no_channel_csv")
            self.assertEqual(data["selected_version"],2)
            self.assertIn("НЕ прогноз",output.report.read_text("utf-8"))

    def test_good_edit_stops_without_pointless_retries(self):
        calls=[]
        with TemporaryDirectory() as td:
            root=Path(td)
            o=analyze_and_recut(template_brief("Лес"),root,root,
                                filename="JARVIS_NOVA_VERTICAL.mp4",
                                renderer=renderer_factory(calls))
            self.assertEqual(len(o.attempts),1)
            self.assertEqual(o.output.name,"JARVIS_NOVA_VERTICAL.mp4")
            self.assertIn("статистики",o.speech)

    def test_real_channel_history_is_not_predicted_future_views(self):
        calls=[]
        profile=SimpleNamespace(
            videos=tuple(VideoMetric(f"Камеры обзор {i}",views,
                        avg_view_pct=ret,ctr=ctr) for i,(views,ret,ctr) in enumerate([
                            (1200,60.,2.),(1300,70.,3.),(1600,80.,4.),(1500,75.,5.)])),
            sample_size=4,typical_views=1400)
        reviews=[]
        def review(brief,p,path,rendered=None):
            self.assertIs(p,profile)
            self.assertTrue(path.exists())
            self.assertEqual(rendered["technical_quality"]["video_codec"],"h264")
            reviews.append(path)
            return FinalReview(60 if len(reviews)==1 else 75,"формальные критерии","низкая",
                               4,(1200,1600),(),("Укороти первые сцены",),(),30.,str(path))
        with TemporaryDirectory() as td:
            root=Path(td)
            o=analyze_and_recut(slow_brief(),root,root,profile=profile,
                                renderer=renderer_factory(calls),reviewer=review)
            data=json.loads((root/"POST_MONTAGE_REVIEW.json").read_text("utf-8"))
            self.assertEqual(data["historical_channel_data"]["historical_view_band"],[1200,1500])
            self.assertEqual(data["historical_channel_data"]["median_retention_pct"],72.5)
            self.assertEqual(data["historical_channel_data"]["median_ctr_pct"],3.5)
            self.assertEqual(o.output.name,"JARVIS_NOVA_AUTO_VERTICAL_V2.mp4")
            self.assertIn("не прогноз",o.speech)
            self.assertEqual(len(reviews),2)

    def test_failed_recut_keeps_previous_video_and_reports_failure(self):
        calls=[]
        with TemporaryDirectory() as td:
            root=Path(td)
            o=analyze_and_recut(slow_brief(),root,root,
                                renderer=renderer_factory(calls,fail_second=True))
            self.assertEqual(len(o.attempts),1)
            self.assertTrue(o.output.exists())
            self.assertEqual(o.output.name,"JARVIS_NOVA_AUTO_VERTICAL.mp4")
            self.assertIn("ошибкой",o.speech)
            self.assertEqual(len(json.loads((root/"POST_MONTAGE_REVIEW.json").
                       read_text("utf-8"))["revision_errors"]),1)

    def test_cancel_and_invalid_media_never_pretend_to_succeed(self):
        stopped=threading.Event()
        stopped.set()
        with TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(MontageReviewError):
                analyze_and_recut(slow_brief(),root,root,cancel=stopped,
                                  renderer=lambda *_a,**_kw:self.fail("rendered"))
            with self.assertRaises(MontageReviewError):
                analyze_and_recut(slow_brief(),root,root,
                                  renderer=lambda *_a,**_kw:{
                                      "duration":20,"technical_quality":{"quality_checked":False}})

    def test_revisions_are_bounded_and_preserve_original_brief(self):
        original=slow_brief()
        revised=revised_brief(original)
        self.assertEqual(original.shots[0].seconds,10)
        self.assertLessEqual(revised.shots[0].seconds,3)
        self.assertLessEqual(len(revised.shots[0].caption),55)
        self.assertIsNone(revised_brief(revised))
        with TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(ValueError):
                analyze_and_recut(original,root,root,max_revisions=12)
            with self.assertRaises(ValueError):
                analyze_and_recut(original,root,root,filename="../../x.mp4")


if __name__=="__main__":
    unittest.main()
