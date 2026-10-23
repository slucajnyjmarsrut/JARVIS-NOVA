"""NOVA conversation-only bubble: Windows Tk lifecycle and privacy tests."""
import sys
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from nova_overlay import NovaOverlay, clamp_drag_position, dock_geometry
from main import Jarvis


class MiniGeometryTests(unittest.TestCase):
    def test_right_docking_on_normal_and_tiny_monitors(self):
        self.assertEqual(dock_geometry(1920,1080),"334x242+1566+279")
        self.assertEqual(dock_geometry(300,140),"300x140+0+0")
        self.assertEqual(dock_geometry(900,600),"334x242+546+119")

    def test_drag_is_clamped_at_desktop_edges(self):
        self.assertEqual(clamp_drag_position(-400,9999,1920,1080),(0,838))
        self.assertEqual(clamp_drag_position(9999,-3,1920,1080),(1586,0))


class ConversationMiniTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app=tk.Tk()
        except tk.TclError as exc:
            if sys.platform=="win32":
                self.fail("Windows GUI runner needs Tk: "+str(exc))
            self.skipTest("No desktop display: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.mic_state=tk.StringVar(master=self.app,value="Микрофон: выключен")
        self.app.status=tk.StringVar(master=self.app,value="Выключено")
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        self.app.voice=SimpleNamespace(until=0)
        self.app.hud_level_at=0
        self.app.hud_level_value=0
        self.app.overlay_show_text=True
        self.app.overlay_last_user=""
        self.app.overlay_last_answer=""
        self.app.toggle_voice=Mock()
        self.app.f9=Mock()
        self.app.revoke=Mock()
        self.app.save_window_layout=Mock(return_value=True)
        self.app.set_overlay_preview=lambda enabled:self._set_preview(enabled)
        self.app.show_main=lambda:Jarvis.show_main(self.app)
        self.app.overlay=NovaOverlay(self.app)
        self.app._show_overlay_if_hidden=lambda:Jarvis._show_overlay_if_hidden(self.app)

    def _set_preview(self,enabled):
        self.app.overlay_show_text=enabled
        if not enabled:
            self.app.overlay_last_user=""
            self.app.overlay_last_answer=""

    def tearDown(self):
        if hasattr(self,"app"):
            self.app._closing=True
            if self.app.overlay.winfo_exists():
                self.app.overlay.shutdown()
            self.app.destroy()

    def test_mini_shows_only_conversation_and_voice_actions(self):
        self.app.overlay.show()
        panel=self.app.overlay
        self.assertLessEqual(panel.winfo_width(),334)
        self.assertLessEqual(panel.winfo_height(),242)
        self.assertIsNotNone(panel.last_user)
        self.assertIsNotNone(panel.last_answer)
        self.assertFalse(hasattr(panel,"mode_buttons"))
        self.assertFalse(hasattr(panel,"privacy"))
        self.assertIsNotNone(panel.listen_button)

    def test_minimizing_main_keeps_only_mini_visible_and_restores(self):
        self.app.deiconify()
        self.app.update()
        Jarvis.hide_main(self.app)
        self.app.update()
        self.assertEqual(self.app.state(),"withdrawn")
        self.assertEqual(self.app.overlay.state(),"normal")
        self.assertEqual(self.app.overlay.winfo_x(),
                         max(0,self.app.winfo_screenwidth()-334-20))
        self.app.overlay.listen_button.invoke()
        self.app.f9.assert_called_once()
        self.app.overlay.restore_button.invoke()
        self.app.update()
        self.assertEqual(self.app.state(),"normal")
        self.assertEqual(self.app.overlay.state(),"withdrawn")

    def test_normal_minimize_iconify_opens_same_mini(self):
        self.app.deiconify()
        self.app.update()
        self.app.bind("<Unmap>",lambda event:Jarvis._main_unmapped(self.app,event),add="+")
        self.app.iconify()
        self.app.update()
        time.sleep(.07)
        self.app.update()
        self.assertEqual(self.app.state(),"iconic")
        self.assertEqual(self.app.overlay.state(),"normal")
        self.app.show_main()
        self.app.update()
        self.assertEqual(self.app.state(),"normal")

    def test_conversation_text_refreshes_from_original_app(self):
        self.app.overlay_last_user="Вы: открой блокнот"
        self.app.overlay_last_answer="NOVA: открываю блокнот"
        self.app.overlay.show()
        self.app.overlay.refresh_preview()
        self.assertIn("открой блокнот",self.app.overlay.last_user.cget("text"))
        self.assertIn("открываю блокнот",self.app.overlay.last_answer.cget("text"))

    def test_text_privacy_can_be_toggled_without_disabling_voice(self):
        self.app.voice_enabled=True
        self.app.overlay_last_user="Вы: приватная фраза"
        self.app.overlay.show()
        self.app.overlay.privacy_button.invoke()
        self.assertFalse(self.app.overlay_show_text)
        self.assertFalse(self.app.overlay_last_user)
        self.assertNotIn("приватная",self.app.overlay.last_user.cget("text"))
        self.assertTrue(self.app.voice_enabled)
        self.app.overlay.privacy_button.invoke()
        self.assertTrue(self.app.overlay_show_text)

    def test_drag_clamping_and_manual_position_persisted(self):
        panel=self.app.overlay
        panel.show()
        panel.update()
        panel.start_drag(SimpleNamespace(
            x_root=panel.winfo_x()+5,y_root=panel.winfo_y()+5))
        panel.drag(SimpleNamespace(x_root=-500,y_root=-500))
        panel.update_idletasks()
        self.assertEqual((panel.winfo_x(),panel.winfo_y()),(0,0))
        panel.end_drag()
        self.app.save_window_layout.assert_called()
        self.assertTrue(panel._manual_position)
        panel.dock_btn.invoke()
        panel.update_idletasks()
        self.assertFalse(panel._manual_position)
        self.assertEqual(panel.winfo_x(),
                         max(0,panel.winfo_screenwidth()-354))

    def test_mic_button_reflects_state_and_f9_listening(self):
        panel=self.app.overlay
        panel.show()
        self.assertIn("ВКЛ.",panel.mic_button.cget("text"))
        panel.mic_button.invoke()
        self.app.toggle_voice.assert_called_once()
        self.app.voice_enabled=True
        self.app.mic_state.set("Микрофон: включён")
        self.app.voice.until=time.monotonic()+3
        self.app.hud_level_at=time.monotonic()
        self.app.hud_level_value=.08
        panel.refresh()
        self.assertIn("СЛУШАЮ",panel.status_label.cget("text"))
        self.assertIn("ВЫКЛ.",panel.mic_button.cget("text"))
        self.assertIn("dBFS",panel.level.cget("text"))

    def test_overlay_has_only_one_timer_and_cleans_up(self):
        panel=self.app.overlay
        panel.show()
        original=panel._timer_id
        self.assertIsNotNone(original)
        panel.show()
        self.assertEqual(original,panel._timer_id)
        panel.hide()
        self.assertIsNone(panel._timer_id)
        self.assertEqual(panel.state(),"withdrawn")

    def test_close_mini_restores_main_instead_of_exit(self):
        self.app.deiconify()
        self.app.update()
        Jarvis.hide_main(self.app)
        self.app.overlay.restore_main()
        self.app.update()
        self.assertFalse(self.app._closing)
        self.assertEqual(self.app.state(),"normal")


if __name__=="__main__":
    unittest.main()
