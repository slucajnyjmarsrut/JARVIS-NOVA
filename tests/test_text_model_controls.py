# -*- coding: utf-8 -*-
"""Lite's model controls must actually be visible and call consent-gated routes."""
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from nova_command_palette import entries
from text_only_ui import build_text_interface


class VisibleModelControlsTests(unittest.TestCase):
    def test_palette_has_distinct_find_check_and_download_actions(self):
        app=mock.Mock()
        app._model_download_busy=False
        controls={row[1]:row[2] for row in entries(app) if row is not None}
        self.assertIn("Найти модели на дисках",controls)
        self.assertIn("Проверить локальную модель",controls)
        self.assertIn("Скачать Qwen3-VL",controls)
        controls["Найти модели на дисках"]()
        app.scan_models_on_pc.assert_called_once_with()
        controls["Скачать Qwen3-VL"]()
        app.check_models.assert_called_once_with(offer_scan=False)
        app.download_local_model.assert_not_called()

    def test_after_qwen_download_guide_has_next_step_without_screen_capture(self):
        import queue
        from text_only_main import TextJarvis
        app=mock.Mock()
        app._closing=False
        app._model_download_busy=True
        app._local_model_ready=False
        app._model_download_queue=queue.Queue()
        app._model_download_queue.put(("done",None))
        TextJarvis._pump_model_download(app)
        self.assertTrue(app._local_model_ready)
        self.assertFalse(app._model_download_busy)
        message=app.log.call_args.args[1]
        self.assertIn("РАЗОБРАТЬ СНИМОК",message)
        self.assertIn("отдельное разрешение",message)
        app.grant_vision.assert_not_called()
        app.request_trimodal.assert_not_called()
        app.open_screenshot_review.assert_not_called()
        app.download_local_model.assert_not_called()

    def test_real_tk_header_and_model_buttons_are_packed_and_clickable(self):
        try:
            root=tk.Tk()
        except tk.TclError:
            self.skipTest("No graphical Tk display on this runner")
        try:
            root.withdraw()
            root.geometry("470x800")
            root._asset_root=Path(".")
            root.engine="bundled"
            root.executing=False
            root._closing=False
            root._model_download_busy=False
            root._model_scan_busy=False
            root._debate_mode=False
            root.modes=SimpleNamespace(mode="neutral")
            for name in (
                "show_settings_menu", "show_update_center", "hide_main",
                "scan_models_on_pc", "check_models", "cancel_model_scan",
                "cancel_local_model_download", "enter", "f9", "revoke",
                "grant_vision", "open_screenshot_review",
                "open_viral_studio", "open_timeline",
                "open_code_assistant",
            ):
                setattr(root,name,mock.Mock())
            with mock.patch("model_storage.local_model_available",
                            return_value=False):
                build_text_interface(root)
            for name in ("hud_settings_button","hud_find_models",
                         "hud_download_qwen", "hud_enable_screen",
                         "hud_show_screenshot"):
                control=getattr(root,name)
                self.assertEqual(control.winfo_manager(),"pack",name)
                self.assertTrue(control.winfo_exists(),name)
            self.assertEqual(set(root.hud_quick_actions),
                             {"video", "edit", "code", "image"})
            for action in root.hud_quick_actions.values():
                self.assertEqual(action.winfo_manager(),"grid")
                self.assertTrue(action.winfo_exists())
            root.hud_quick_actions["video"].invoke()
            root.open_viral_studio.assert_called_once_with(stage="audience")
            root.hud_quick_actions["edit"].invoke()
            root.open_timeline.assert_called_once_with()
            root.hud_quick_actions["code"].invoke()
            root.open_code_assistant.assert_called_once_with(
                "python", "", auto_start=False)
            root.hud_quick_actions["image"].invoke()
            root.open_screenshot_review.assert_called_once_with()
            root.open_screenshot_review.reset_mock()
            self.assertIn("Qwen не подключена",root.hud_model_hint.cget("text"))
            root.hud_settings_button.invoke()
            root.show_settings_menu.assert_called_once_with()
            root.hud_find_models.invoke()
            root.scan_models_on_pc.assert_called_once_with()
            root.hud_download_qwen.invoke()
            root.check_models.assert_called_once_with(offer_scan=False)
            root.hud_enable_screen.invoke()
            root.grant_vision.assert_called_once_with()
            root.hud_show_screenshot.invoke()
            root.open_screenshot_review.assert_called_once_with()
            root.request_trimodal = mock.Mock()
            root.request_trimodal.assert_not_called()
            root.cancel_local_model_download.assert_not_called()
        finally:
            root.destroy()


if __name__=="__main__":
    unittest.main()
