# -*- coding: utf-8 -*-
"""Topic-only offline MP4: no user clips, Internet, model download or publishing."""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import os
import unittest

from quick_video_brief import quick_brief
from night_supervisor import NightSupervisor
from topic_video_engine import (
    TopicVideoError, _theme, _draw_card, _music, _wrapped, _font, render_topic_video,
)
from viral_studio import ViralStudioError, ffmpeg_tools


def ai_story(job, progress):
    brief=replace(quick_brief(job.prompt),generator="локальная Gemma3:4b")
    return {"brief":asdict(brief), "model":"gemma3:4b"}


class TopicOnlyVideoTests(TestCase):
    def story(self):
        return replace(quick_brief("Minecraft"),generator="локальная Gemma3:4b")

    def test_theme_is_based_on_topic_not_fake_real_footage(self):
        self.assertEqual(_theme("Minecraft"),"pixel")
        self.assertEqual(_theme("лес и деревья"),"nature")
        self.assertEqual(_theme("Марс"),"space")
        self.assertEqual(_theme("искусственный интеллект"),"tech")
        self.assertEqual(_theme("абстрактный сюжет"),"abstract")

    def test_very_long_russian_captions_fit_the_frame_in_pixels(self):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (240, 426), "white")
        draw = ImageDraw.Draw(image)
        font = _font(19)
        for text in (
            "СУПЕРДЛИННОЕЗАГЛАВИЕ" * 12,
            "Нейросетевая система создаёт полноценное видео " * 20,
            "https://very-long-example.com/special/not-a-shell-command" * 5,
        ):
            with self.subTest(text=text[:30]):
                output = _wrapped(draw, text, font, 150, max_lines=2)
                lines = output.splitlines()
                self.assertGreaterEqual(len(lines), 1)
                self.assertLessEqual(len(lines), 2)
                for line in lines:
                    x0, _y0, x1, _y1 = draw.textbbox((0, 0), line, font=font)
                    self.assertLessEqual(x1 - x0, 150)
                self.assertTrue(output.endswith("…"))
        self.assertEqual(_wrapped(draw, "Привет", font, -1), "")

    def test_original_cards_and_audio_exist_without_source_files(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            card=root/"card.png"
            tone=root/"original.wav"
            _draw_card(self.story(),self.story().shots[0],1,card,(180,320))
            _music(tone,1,2.0)
            self.assertGreater(card.stat().st_size,500)
            self.assertGreater(tone.stat().st_size,80_000)

    def test_output_path_must_be_empty_and_new(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"private.mp4").write_bytes(b"PRIVATE")
            with self.assertRaises(TopicVideoError):
                render_topic_video(self.story(),root,
                                   tools=("missing_ffmpeg","missing_ffprobe"))
            self.assertEqual((root/"private.mp4").read_bytes(),b"PRIVATE")

    def test_fixed_ffmpeg_command_and_technical_gate_with_fake_render(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            outputs=[]
            def fake_exec(argv, **kwargs):
                self.assertIn("-nostdin",argv)
                self.assertIn("libx264",argv)
                self.assertIn("-shortest",argv)
                self.assertNotIn("Minecraft",argv)
                Path(argv[-1]).write_bytes(b"synthetic clip")
                outputs.append(argv)
            def fake_render(brief,clips,result,**kwargs):
                self.assertEqual(len(list(clips.glob("*.mp4"))),5)
                self.assertEqual(result.name,"JARVIS_NOVA_FROM_TOPIC.mp4")
                result.write_bytes(b"X"*1200)
                return {"technical_quality":{"quality_checked":True},
                        "duration":30.,"segments":[]}
            result=render_topic_video(self.story(),root,size=(180,320),
                 tools=("ffmpeg","ffprobe"),executor=fake_exec,
                 renderer=fake_render)
            self.assertEqual(len(outputs),5)
            self.assertTrue(result["technical_quality"]["quality_checked"])
            self.assertTrue((root/"JARVIS_NOVA_FROM_TOPIC.mp4").is_file())
            self.assertIn("а не реалистичные кадры",
                          (root/"README_RU.md").read_text(encoding="utf-8"))
            self.assertFalse(__import__("json").loads(
                (root/"ORIGIN_AND_QUALITY.json").read_text(
                    encoding="utf-8"))["real_video_generation_model"])

    def test_invalid_renderer_does_not_report_completion(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fake_exec(argv,**kwargs):
                Path(argv[-1]).write_bytes(b"clip")
            def failed_renderer(brief,clips,target,**kwargs):
                target.write_bytes(b"mp4")
                return {"technical_quality":{"quality_checked":False}}
            with self.assertRaises(TopicVideoError):
                render_topic_video(self.story(),root,size=(180,320),
                                   tools=("ffmpeg","ffprobe"),
                                   executor=fake_exec,renderer=failed_renderer)
            self.assertFalse((root/"ORIGIN_AND_QUALITY.json").exists())

    def test_night_queue_topic_video_requires_approval_and_checkpoints(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"queue"
            manager=NightSupervisor(root,executor=ai_story)
            with self.assertRaises(PermissionError):
                manager.enqueue("topic_video","Minecraft")
            task=manager.enqueue("topic_video","Minecraft",
                approved=True,allow_new_files=True)
            def simulated_render(brief,destination,*,cancel=None):
                self.assertEqual(brief.generator,"локальная Gemma3:4b")
                (destination/"JARVIS_NOVA_FROM_TOPIC.mp4").write_bytes(b"X"*1200)
                (destination/"ORIGIN_AND_QUALITY.json").write_text(
                    '{"mode":"motion_graphics"}',encoding="utf-8")
            with mock.patch("topic_video_engine.render_topic_video",
                            side_effect=simulated_render):
                self.assertTrue(manager.run_next())
            job=manager.list_jobs()[0]
            self.assertEqual(job.id,task)
            self.assertEqual(job.status,"completed",job.error)
            self.assertTrue((Path(job.output)/
                             "JARVIS_NOVA_FROM_TOPIC.mp4").exists())
            self.assertEqual(manager._read_checkpoint(task,"verified")["verification"],
                             "structural_only")

    def test_night_queue_failed_render_cannot_claim_completed(self):
        with TemporaryDirectory() as tmp:
            manager=NightSupervisor(Path(tmp)/"queue",executor=ai_story)
            manager.enqueue("topic_video","Minecraft",
                approved=True,allow_new_files=True)
            with mock.patch("topic_video_engine.render_topic_video",
                            side_effect=TopicVideoError("ffmpeg failure")):
                manager.run_next()
            self.assertEqual(manager.list_jobs()[0].status,"blocked")
            self.assertFalse((manager.root/"outputs"/
                              manager.list_jobs()[0].id).exists())

    @unittest.skipUnless(os.environ.get("JARVIS_TEST_REAL_TOPIC_VIDEO")=="1",
                         "Real MP4 E2E runs only in video render workflow")
    def test_real_ffmpeg_from_no_material_creates_h264_aac_mp4(self):
        try:
            tools=ffmpeg_tools()
        except ViralStudioError as exc:
            self.skipTest(str(exc))
        from smart_montage import verify_output_media
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=render_topic_video(self.story(),root,size=(180,320),
                                      tools=tools)
            video=root/"JARVIS_NOVA_FROM_TOPIC.mp4"
            self.assertTrue(video.is_file())
            self.assertTrue((root/"JARVIS_NOVA_FROM_TOPIC.srt").is_file())
            self.assertTrue((root/"JARVIS_NOVA_FROM_TOPIC_EDL.json").is_file())
            self.assertTrue(result["technical_quality"]["quality_checked"])
            report=verify_output_media(video,tools[1],result["duration"])
            self.assertTrue(report["quality_checked"])
            self.assertEqual(report["video_codec"],"h264")
            self.assertEqual(report["audio_codec"],"aac")


if __name__=="__main__":
    unittest.main()
