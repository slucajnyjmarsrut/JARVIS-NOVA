"""Compact right-hand NOVA interface smoke tests (real Tk, no models)."""
import sys
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nova_compact_ui import build_interface, compact_geometry, PANEL_WIDTH, PANEL_HEIGHT


class CompactGeometryTests(unittest.TestCase):
    def test_right_docking_and_small_displays(self):
        self.assertEqual(compact_geometry(1920,1080), "468x810+1434+135")
        self.assertEqual(compact_geometry(300,240), "300x240+0+0")
        self.assertEqual(compact_geometry(800,600), "468x600+314+0")
        self.assertLess(PANEL_WIDTH, 500)
        self.assertLess(PANEL_HEIGHT, 850)


class CompactGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = tk.Tk()
        except tk.TclError as exc:
            if sys.platform == "win32":
                self.fail("Windows CI must provide a Tk display: "+str(exc))
            self.skipTest("Headless: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.engine="bundled"
        self.app.voice=SimpleNamespace(until=0)
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        self.app.modes=SimpleNamespace(mode="work")
        self.app.control_allowed=False
        self.app.vision_allowed=False
        self.app.calls={}
        for name in ("show_settings_menu","hide_main","toggle_voice","f9",
                     "activate_mode","enter","revoke"):
            self.app.calls[name]=Mock()
            setattr(self.app,name,self.app.calls[name])
        build_interface(self.app)
        self.app.update_idletasks()

    def tearDown(self):
        if getattr(self,"app",None) is not None:
            self.app._closing=True
            self.app.destroy()
            self.assertIsNone(self.app._nova_after_id)

    def test_main_panel_is_vertical_and_voice_first(self):
        self.assertIsNotNone(self.app.hud_reactor)
        self.assertEqual(self.app.hud_reactor.winfo_manager(),"pack")
        self.assertTrue(self.app.hud_minimize_button.winfo_exists())
        self.assertTrue(self.app.history.winfo_exists())
        self.assertEqual(self.app.history.cget("state"),"disabled")
        self.assertIn("РАСПОЗНАНО",self.app.hud_last_transcript.cget("text"))
        self.assertLessEqual(int(self.app.hud_reactor.cget("height")),150)

    def test_minimize_button_opens_conversation_bubble(self):
        self.app.hud_minimize_button.invoke()
        self.app.calls["hide_main"].assert_called_once()

    def test_f9_and_microphone_are_live_actions(self):
        self.app.hud_listen_button.invoke()
        self.app.calls["f9"].assert_called_once()
        self.app.mic_toggle_button.invoke()
        self.app.calls["toggle_voice"].assert_called_once()
        self.assertIsNotNone(self.app.bind("<F9>"))

    def test_modes_route_through_permission_checked_controller(self):
        self.app.hud_mode_buttons["gaming"].invoke()
        self.app.calls["activate_mode"].assert_called_with("gaming")
        self.app.hud_mode_buttons["study"].invoke()
        self.app.calls["activate_mode"].assert_called_with("study")

    def test_settings_and_chat_entry_survive_compact_layout(self):
        self.app.hud_settings_button.invoke()
        self.app.calls["show_settings_menu"].assert_called_once()
        self.app.entry.insert(0,"Привет")
        self.assertEqual(self.app.entry.get(),"Привет")
        self.assertIsNotNone(self.app.bind("<Control-l>"))
        self.assertIsNotNone(self.app.bind("<Control-Shift-M>"))

    def test_voice_status_updates_on_main_thread(self):
        self.app.voice_enabled=True
        self.app.mic_state.set("Микрофон: включён")
        self.app.voice.until=time.monotonic()+3
        self.app.hud_level_at=time.monotonic()
        self.app.hud_level_value=.05
        self.app.after(1,lambda:None)
        time.sleep(.19)
        self.app.update()
        self.assertIn("СЛУШАЮ",self.app.hud_mode.cget("text"))
        self.assertIn("dBFS",self.app.hud_meter_label.cget("text"))

    def test_permissions_not_granted_by_render_or_mode_change(self):
        self.app.hud_mode_buttons["work"].invoke()
        self.assertFalse(self.app.control_allowed)
        self.assertFalse(self.app.vision_allowed)
        self.assertIn("ЗАПРЕТ",self.app.hud_access.cget("text"))


if __name__=="__main__":
    unittest.main()
