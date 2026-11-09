# -*- coding: utf-8 -*-
"""Regression: real entrypoint cannot instantiate microphone or speech engines."""
import ast
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import text_only_main as text_main
from text_only_main import TextJarvis, NoAudio


class TextModeTests(unittest.TestCase):
    def test_production_entrypoint_is_text_only(self):
        for filename in ("main.py","bootstrap.py"):
            source=(ROOT/filename).read_text(encoding="utf-8")
            self.assertIn("TextJarvis().mainloop()",source)
        self.assertEqual(TextJarvis.reply.__qualname__.split(".")[0], TextJarvis.__name__)

    def test_voice_is_never_created_in_constructor(self):
        source=inspect.getsource(TextJarvis.__init__)
        tree=ast.parse(source.strip() if not source.startswith("    ") else
                       "class Fake:\n"+source)
        self.assertNotIn("RC4Voice(",source)
        self.assertNotIn("Speaker(",source)
        self.assertNotIn("TrimodalService(",source)
        self.assertNotIn(".start()",source)

    def test_no_audio_object_does_not_have_hardware_methods(self):
        obj=NoAudio()
        self.assertFalse(obj.busy)
        self.assertFalse(obj.speaking)
        self.assertFalse(hasattr(obj,"start"))
        self.assertFalse(hasattr(obj,"say"))
        self.assertEqual(obj.vision_source("опиши экран"),"screen")
        self.assertIsNone(obj.vision_source("напиши код на Java"))

    def test_reply_never_calls_speaker(self):
        app=Mock()
        app._closing=False
        TextJarvis.reply(app,"Письменный ответ")
        app.log.assert_called_once_with("JARVIS","Письменный ответ")
        app.status.set.assert_called_once()
        app.speaker.say.assert_not_called()

    def test_video_window_is_not_passed_a_speaker(self):
        source=inspect.getsource(TextJarvis.open_viral_studio)
        self.assertIn("speaker=None",source)

    def test_audio_controls_absent_in_text_layout(self):
        from text_only_ui import build_text_interface
        source=inspect.getsource(build_text_interface)
        self.assertNotIn("toggle_voice",source)
        self.assertNotIn("mic_toggle_button",source)
        self.assertNotIn("LevelMeter(",source)

    def test_qwen_badge_matches_actual_model_state(self):
        from text_only_ui import engine_badge, build_text_interface
        missing,missing_color=engine_badge("bundled",False)
        ready,ready_color=engine_badge("bundled",True)
        self.assertIn("НЕ УСТАНОВЛЕНА",missing)
        self.assertEqual(ready,"QWEN · ЛОКАЛЬНО")
        self.assertNotEqual(missing_color,ready_color)
        self.assertIn("_local_model_ready", inspect.getsource(build_text_interface))
        self.assertIn("_local_model_ready", inspect.getsource(TextJarvis.check_models))
        self.assertIn("_local_model_ready", inspect.getsource(TextJarvis._pump_model_download))

    def test_real_text_panel_without_devices(self):
        import tkinter as tk
        from contextlib import ExitStack
        from unittest.mock import patch
        try:
            with ExitStack() as stack:
                for target in (
                    "text_only_main.LearningStore", "text_only_main.ModeManager",
                    "text_only_main.GameCatalog", "text_only_main.Desktop",
                    "text_only_main.BundledVisionRuntime",
                    "text_only_main.LocalChat"
                ):
                    stack.enter_context(patch(target))
                stack.enter_context(patch("text_only_main.load_layout", return_value={}))
                app=TextJarvis()
                try:
                    app.update_idletasks()
                    app.update()
                    self.assertFalse(app.voice_enabled)
                    self.assertFalse(hasattr(app,"mic_toggle_button"))
                    self.assertFalse(hasattr(app.overlay,"mic_button"))
                    self.assertFalse(hasattr(app.overlay,"listen_button"))
                    self.assertTrue(app.entry.winfo_exists())
                    self.assertTrue(app.overlay.quick_entry.winfo_exists())
                    self.assertIn("Готов", app.status.get())
                finally:
                    app.close()
        except tk.TclError as exc:
            if sys.platform=="win32":
                self.fail("Windows text-only interface must start: "+str(exc))
            self.skipTest("No display: "+str(exc))



if __name__=="__main__":
    unittest.main()
