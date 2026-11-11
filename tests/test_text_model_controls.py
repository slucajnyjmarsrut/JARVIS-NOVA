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
            ):
                setattr(root,name,mock.Mock())
            with mock.patch("model_storage.local_model_available",
                            return_value=False):
                build_text_interface(root)
            for name in ("hud_settings_button","hud_find_models",
                         "hud_download_qwen"):
                control=getattr(root,name)
                self.assertEqual(control.winfo_manager(),"pack",name)
                self.assertTrue(control.winfo_exists(),name)
            root.hud_settings_button.invoke()
            root.show_settings_menu.assert_called_once_with()
            root.hud_find_models.invoke()
            root.scan_models_on_pc.assert_called_once_with()
            root.hud_download_qwen.invoke()
            root.check_models.assert_called_once_with(offer_scan=False)
            root.cancel_local_model_download.assert_not_called()
        finally:
            root.destroy()


if __name__=="__main__":
    unittest.main()
