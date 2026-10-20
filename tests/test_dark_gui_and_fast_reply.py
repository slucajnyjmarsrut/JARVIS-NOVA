"""Prevent regression of dark window chrome, missing left controls and instant reply."""
from pathlib import Path
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from quick_replies import quick_reply
from nova_ui import build_interface,SURFACE,CYAN_DIM
from windows_theme import make_titlebar_dark


class QuickRepliesTests(unittest.TestCase):
    def test_common_conversation_needs_no_qwen(self):
        self.assertIn("Всё хорошо",quick_reply("Как дела?"))
        self.assertIn("Слушаю",quick_reply("Джарвис, что делаешь?"))
        self.assertIn("JARVIS NOVA",quick_reply("кто ты"))
        self.assertIsNone(quick_reply("открой блокнот"))
        self.assertIsNone(quick_reply("что ты делаешь в браузере"))
        self.assertIsNone(quick_reply("пожалуйста, удали файлы"))
        self.assertIsNone(quick_reply("как дела с монтажом видео"))
        self.assertIsNone(quick_reply(None))

    def test_dark_titlebar_never_forces_borderless_window(self):
        self.assertFalse(make_titlebar_dark(object()) if sys.platform!="win32"
                         else make_titlebar_dark(SimpleNamespace(
                            update_idletasks=lambda:None,winfo_id=lambda:0)))
        source=(Path(__file__).resolve().parents[1]/"main.py").read_text(encoding="utf-8")
        self.assertNotIn("self.config(menu=menu)",source)
        self.assertNotIn("overrideredirect(",source)
        self.assertIn("make_titlebar_dark",source)
        self.assertIn("self._settings_menu=menu",source)


class DarkGuiTests(unittest.TestCase):
    def setUp(self):
        try:self.app=tk.Tk()
        except tk.TclError as exc:
            if sys.platform=="win32":self.fail(str(exc))
            self.skipTest("No Tk window: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.engine="bundled"
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        self.app.show_settings_menu=Mock()
        for name in ("toggle_voice","select_microphone","test_microphone","f9",
                     "enter","open_viral_studio","activate_mode",
                     "request_trimodal","show_capabilities","revoke"):
            setattr(self.app,name,Mock())
        build_interface(self.app)
        self.app.update_idletasks()

    def tearDown(self):
        if hasattr(self,"app"):
            self.app._closing=True
            self.app.destroy()

    def test_right_chat_scrollbar_is_dark_ttk_not_native_white(self):
        scroll=self.app.hud_history_scrollbar
        self.assertEqual(scroll.winfo_class(),"TScrollbar")
        self.assertEqual(scroll.cget("style"),"Nova.Vertical.TScrollbar")
        style=self.app.hud_scroll_style
        self.assertEqual(style.lookup("Nova.Vertical.TScrollbar","background"),CYAN_DIM)
        self.assertEqual(style.lookup("Nova.Vertical.TScrollbar","troughcolor"),SURFACE)

    def test_left_sidebar_is_scrollable_and_settings_button_opens_menu(self):
        self.assertEqual(self.app.hud_rail_scrollbar.winfo_class(),"TScrollbar")
        self.assertIs(self.app.hud_shortcuts.master,self.app.hud_rail)
        self.assertIs(self.app.hud_rail.master,self.app.hud_rail_canvas)
        self.assertGreaterEqual(len(self.app.hud_shortcut_buttons),6)
        self.app.hud_settings_button.invoke()
        self.app.show_settings_menu.assert_called_once()
        self.app.hud_rail_canvas.yview_moveto(1.0)
        self.assertTrue(self.app.hud_shortcut_buttons[-1].winfo_exists())


if __name__=="__main__":
    unittest.main()
