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
from text_only_main import TextJarvis
from main import screen_question


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

    def test_real_overlay_never_constructs_audio_buttons(self):
        from nova_overlay import NovaOverlay
        from text_only_overlay import TextOverlay
        base=inspect.getsource(NovaOverlay.__init__)
        text=inspect.getsource(TextOverlay.__init__)
        self.assertNotIn("mic_button",base)
        self.assertIn("super().__init__(app)",text)
        self.assertNotIn("mic_button.destroy()",text)

    def test_screen_question_is_pure_typed_text_not_audio(self):
        self.assertTrue(screen_question("опиши экран"))
        self.assertFalse(screen_question("напиши код на Java"))

    def test_reply_never_calls_speaker(self):
        app=Mock()
        app._closing=False
        TextJarvis.reply(app,"Письменный ответ")
        app.log.assert_called_once_with("JARVIS","Письменный ответ")
        app.status.set.assert_called_once()
        self.assertNotIn("speaker", inspect.getsource(TextJarvis.reply))

    def test_video_window_is_not_passed_a_speaker(self):
        source=inspect.getsource(TextJarvis.open_viral_studio)
        self.assertIn("ViralStudioWindow(self)",source)
        self.assertNotIn("speaker=",source)

    def test_audio_controls_absent_in_text_layout(self):
        from text_only_ui import build_text_interface
        source=inspect.getsource(build_text_interface)
        self.assertNotIn("toggle_voice",source)
        self.assertNotIn("mic_toggle_button",source)
        self.assertNotIn("LevelMeter(",source)
        self.assertNotIn('"МИКРОФОН"',source)
        self.assertNotIn('"ОЗВУЧИТЬ"',source)

    def test_qwen_badge_matches_actual_model_state(self):
        from text_only_ui import engine_badge, build_text_interface
        missing,missing_color=engine_badge("bundled",False)
        ready,ready_color=engine_badge("bundled",True)
        self.assertIn("НЕ ПОДКЛЮЧЕНА",missing)
        self.assertEqual(ready,"QWEN · ЛОКАЛЬНО")
        self.assertNotEqual(missing_color,ready_color)
        self.assertIn("_local_model_ready", inspect.getsource(build_text_interface))
        self.assertIn("_local_model_ready", inspect.getsource(TextJarvis.check_models))
        self.assertIn("_local_model_ready", inspect.getsource(TextJarvis._pump_model_download))

    def test_debate_mode_has_visible_ui_indicator_and_runner_coverage(self):
        from text_only_ui import build_text_interface
        source=inspect.getsource(build_text_interface)
        self.assertIn('label="РЕЖИМ СПОРА"',source)
        self.assertIn('_debate_mode',source)
        suite=(ROOT/"scripts"/"run_text_only_tests.py").read_text(
            encoding="utf-8")
        self.assertIn('"test_debate_mode.py"',suite)

    def test_chat_first_ui_has_visible_model_controls_without_unrelated_shortcuts(self):
        from text_only_ui import build_text_interface
        source=inspect.getsource(build_text_interface)
        self.assertIn('app.hud_mode_buttons = {}',source)
        self.assertIn('app.hud_settings_button.pack(',source)
        self.assertIn('app.hud_quick_actions = {}',source)
        self.assertIn('button.grid(row=index // 2',source)
        self.assertIn('app.hud_model_hint',source)
        self.assertIn('app.hud_find_models.pack(',source)
        self.assertIn('app.hud_download_qwen.pack(',source)
        self.assertIn('app.hud_enable_screen.pack(',source)
        self.assertIn('app.hud_show_screenshot.pack(',source)
        self.assertIn('app.hud_cancel_scan',source)
        self.assertNotIn('"ОТПРАВИТЬ"',source)
        self.assertNotIn('"СКРИН"',source)
        self.assertIn('app.entry.bind("<Return>",app.enter)',source)
        self.assertIn('app.hud_cancel_model',source)

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
                    self.assertFalse(hasattr(app,"voice_enabled"))
                    self.assertFalse(hasattr(app,"speaker"))
                    self.assertFalse(hasattr(app,"voice"))
                    self.assertFalse(hasattr(app,"mic_toggle_button"))
                    self.assertFalse(hasattr(app.overlay,"mic_button"))
                    self.assertFalse(hasattr(app.overlay,"listen_button"))
                    self.assertFalse(hasattr(app.overlay,"level"))
                    self.assertTrue(app.entry.winfo_exists())
                    self.assertTrue(app.overlay.quick_entry.winfo_exists())
                    self.assertEqual(app.hud_mode_buttons,{})
                    self.assertEqual(app.hud_settings_button.winfo_manager(),"pack")
                    self.assertEqual(set(app.hud_quick_actions),
                                     {"video","edit","code","image"})
                    self.assertTrue(all(
                        x.winfo_manager()=="grid"
                        for x in app.hud_quick_actions.values()))
                    self.assertTrue(app.hud_model_hint.winfo_exists())
                    # Primary entry remains usable on a compact laptop display.
                    app.geometry("390x600")
                    # WM Configure is a real event, not an idle geometry job.
                    # update_idletasks alone still reports the prior 448x735
                    # child layout while the root already says 390x600.
                    app.update()
                    app.update_idletasks()
                    self.assertTrue(app.entry.winfo_ismapped())
                    self.assertGreater(app.entry.winfo_height(),12)
                    shell=app.entry.master.master
                    writer=app.entry.master
                    chat=app.history.master.master
                    footer=app.hud_access.master
                    layout={
                        name:(w.winfo_geometry(),w.winfo_reqheight(),
                              w.winfo_rooty(),w.winfo_ismapped())
                        for name,w in (("app",app),("shell",shell),
                                       ("chat",chat),("writer",writer),
                                       ("footer",footer),("entry",app.entry))
                    }
                    self.assertLessEqual(
                        app.entry.winfo_rooty()+app.entry.winfo_height(),
                        app.winfo_rooty()+app.winfo_height()+2,
                        f"Compact layout widgets: {layout}")
                    self.assertEqual(app.hud_find_models.winfo_manager(),"pack")
                    self.assertEqual(app.hud_download_qwen.winfo_manager(),"pack")
                    self.assertEqual(app.hud_enable_screen.winfo_manager(),"pack")
                    self.assertEqual(app.hud_show_screenshot.winfo_manager(),"pack")
                    self.assertFalse(app.hud_update_button.winfo_manager())
                    self.assertFalse(app.hud_minimize_button.winfo_manager())
                    self.assertIn("Готов", app.status.get())
                finally:
                    app.close()
        except tk.TclError as exc:
            if sys.platform=="win32":
                self.fail("Windows text-only interface must start: "+str(exc))
            self.skipTest("No display: "+str(exc))



if __name__=="__main__":
    unittest.main()
