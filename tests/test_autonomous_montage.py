# -*- coding: utf-8 -*-
"""No cloud calls: full automatic edit GUI/voice routing and explicit consent."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, mock
import threading

from main import Jarvis
from viral_studio import template_brief
from viral_studio_ui import ViralStudioWindow


class AutonomousMontageTests(TestCase):
    def test_voice_topic_opens_autostudio_but_does_not_download(self):
        window=SimpleNamespace(topic=mock.Mock())
        app=SimpleNamespace(_closing=False, log=mock.Mock(),
            show_main=mock.Mock(), hide_main=mock.Mock(),
            modes=SimpleNamespace(parse=lambda *_:None),
            desktop=SimpleNamespace(is_installed=lambda _:False),
            open_viral_studio=mock.Mock(return_value=window),
            status=SimpleNamespace(set=mock.Mock()))
        Jarvis.handle_text(app,"создай ролик про Minecraft")
        app.open_viral_studio.assert_called_once_with("auto")
        window.topic.set.assert_called_once_with("Minecraft")
        self.assertIn("разрешение", app.status.set.call_args.args[0])

    def test_declined_consent_never_starts_research_or_download(self):
        app=SimpleNamespace(topic=SimpleNamespace(get=lambda:"природа"),
            status=SimpleNamespace(set=mock.Mock()),
            _spawn=mock.Mock(side_effect=AssertionError("Started without permission")))
        with mock.patch("viral_studio_ui.messagebox.askyesno",return_value=False):
            ViralStudioWindow.auto_montage(app)
        app._spawn.assert_not_called()

    def test_topic_alone_runs_autonomous_pipeline_without_csv_or_footage(self):
        with TemporaryDirectory() as t:
            source=Path(t)
            brief=template_brief("лес")
            items=[object() for _ in brief.shots]
            app=SimpleNamespace(topic=SimpleNamespace(get=lambda:"лес"),
                profile=None,status=SimpleNamespace(set=mock.Mock()),
                stop_event=threading.Event(), _spawn=lambda work: work(),
                _notify=lambda callback:callback(),_show=mock.Mock(),
                _speak=mock.Mock(),project=None,brief=None,rendered_video=None)
            def downloader(clips,folder,**opts):
                self.assertTrue(opts["consent"])
                self.assertEqual(len(clips),len(brief.shots))
                self.assertEqual(folder.name,"licensed_media")
                folder.mkdir()
                return folder
            def finishing(b,folder,project,**opts):
                self.assertEqual(b,brief)
                self.assertEqual(folder.name,"licensed_media")
                self.assertEqual(project.name[:5],"auto_")
                self.assertIsNone(opts["profile"])
                self.assertEqual(opts["filename"],"JARVIS_NOVA_AUTO_VERTICAL.mp4")
                output=project/"JARVIS_NOVA_AUTO_VERTICAL.mp4"
                output.write_bytes(b"fake-FFmpeg-test-output")
                return SimpleNamespace(brief=brief,output=output,
                   rendered={"duration":23.,"technical_quality":{"quality_checked":True}},
                   attempts=[1],report=project/"POST_MONTAGE_REVIEW_RU.md",
                   speech="Проверил ролик. Повторный монтаж не нужен.")
            with (mock.patch("viral_studio_ui.messagebox.askyesno",return_value=True),
                  mock.patch("viral_studio_ui._home",return_value=source),
                  mock.patch("viral_studio_ui.create_local_brief",return_value=brief) as ai,
                  mock.patch("viral_studio_ui.search_free_video",return_value=items) as search,
                  mock.patch("viral_studio_ui.download_free_video",side_effect=downloader),
                  mock.patch("viral_studio_ui.analyze_and_recut",side_effect=finishing)):
                ViralStudioWindow.auto_montage(app)
            ai.assert_called_once_with("лес",audience=None)
            search.assert_called_once_with("лес",consent=True)
            self.assertTrue((app.project/"brief.json").exists())
            self.assertEqual(app.rendered_video.parent,app.project)
            self.assertTrue(app._show.called)
            self.assertIn("Отчёт о просмотрах",app._show.call_args.args[0])
            app._speak.assert_called_once()

    def test_model_failure_uses_explicitly_marked_template_not_fake_ai(self):
        with TemporaryDirectory() as t:
            app=SimpleNamespace(topic=SimpleNamespace(get=lambda:"Игры"),
                profile=None,status=SimpleNamespace(set=mock.Mock()),
                stop_event=threading.Event(),_spawn=lambda work:work(),
                _notify=lambda cb:cb(),_show=mock.Mock(),
                _speak=mock.Mock(),project=None,brief=None,rendered_video=None)
            with (mock.patch("viral_studio_ui.messagebox.askyesno",return_value=True),
                  mock.patch("viral_studio_ui._home",return_value=Path(t)),
                  mock.patch("viral_studio_ui.create_local_brief",
                             side_effect=RuntimeError("model not installed")),
                  mock.patch("viral_studio_ui.search_free_video",
                             return_value=[object() for _ in range(10)]),
                  mock.patch("viral_studio_ui.download_free_video",
                             side_effect=lambda c,p,**k:p.mkdir()),
                  mock.patch("viral_studio_ui.analyze_and_recut",
                             side_effect=lambda brief,folder,project,**k:SimpleNamespace(
                               brief=brief,output=project/"result.mp4",
                               rendered={"duration":23.,"technical_quality":{}},
                               attempts=[1],report=project/"review.md",
                               speech="Проверил и объяснил результат."))):
                ViralStudioWindow.auto_montage(app)
            self.assertIn("шаблон",app.brief.generator)
            self.assertIn("шаблон",app._show.call_args.args[0])

if __name__=="__main__":
    import unittest
    unittest.main()
