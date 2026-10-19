"""Real Tk overlay lifecycle with no microphone/audio model."""
import sys
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from nova_overlay import NovaOverlay, dock_geometry
from main import Jarvis


class GeometryTests(unittest.TestCase):
    def test_docks_to_right_and_clamps_small_displays(self):
        self.assertEqual(dock_geometry(1920,1080),"302x200+1598+440")
        self.assertEqual(dock_geometry(300,140),"300x140+0+0")
        self.assertEqual(dock_geometry(900,600),"302x200+578+200")


class OverlayTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app=tk.Tk()
        except tk.TclError as exc:
            if sys.platform=="win32":self.fail("Windows needs a real Tk display: "+str(exc))
            self.skipTest("Headless: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.mic_state=tk.StringVar(master=self.app,value="Микрофон: выключен")
        self.app.status=tk.StringVar(master=self.app,value="Выключено")
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        self.app.voice=SimpleNamespace(until=0)
        self.app.modes=SimpleNamespace(mode="work")
        self.app.hud_level_at=0
        self.app.hud_level_value=0
        self.app.toggle_voice=Mock()
        self.app.f9=Mock()
        self.app.show_main=lambda:Jarvis.show_main(self.app)
        self.app.overlay=NovaOverlay(self.app)
        self.app._show_overlay_if_hidden=lambda:Jarvis._show_overlay_if_hidden(self.app)

    def tearDown(self):
        if hasattr(self,"app"):
            self.app._closing=True
            if self.app.overlay.winfo_exists():
                self.app.overlay.shutdown()
            self.app.destroy()

    def test_hide_root_shows_overlay_on_right_and_restores(self):
        self.app.deiconify()
        self.app.update()
        Jarvis.hide_main(self.app)
        self.app.update()
        self.assertEqual(self.app.state(),"withdrawn")
        self.assertEqual(self.app.overlay.state(),"normal")
        self.assertGreaterEqual(self.app.overlay.winfo_x(),
                                self.app.overlay.winfo_screenwidth()-315)
        self.app.overlay.mic_button.invoke()
        self.app.toggle_voice.assert_called_once()
        self.app.overlay.restore_btn.invoke()
        self.app.update()
        self.assertEqual(self.app.state(),"normal")
        self.assertEqual(self.app.overlay.state(),"withdrawn")

    def test_root_unmap_shows_overlay_automatically(self):
        self.app.deiconify()
        self.app.update()
        self.app.bind("<Unmap>",lambda ev:Jarvis._main_unmapped(self.app,ev),add="+")
        self.app.withdraw()
        self.app.update()
        time.sleep(.08)
        self.app.update()
        self.assertEqual(self.app.overlay.state(),"normal")

    def test_overlay_has_live_state_and_one_update_timer(self):
        self.app.overlay.show()
        self.app.overlay.show()
        self.app.update()
        timer=self.app.overlay._timer_id
        self.assertIsNotNone(timer)
        self.assertIn("ВЫКЛ.",self.app.overlay.status_label.cget("text"))
        self.app.overlay.listen_button.invoke()
        self.app.f9.assert_called_once()
        self.app.voice_enabled=True
        self.app.mic_state.set("Микрофон: включён")
        self.app.voice.until=time.monotonic()+3
        self.app.hud_level_at=time.monotonic()
        self.app.hud_level_value=.06
        time.sleep(.2)
        self.app.update()
        self.assertIn("СЛУШАЮ",self.app.overlay.status_label.cget("text"))
        self.assertIn("dBFS",self.app.overlay.level.cget("text"))
        self.app.overlay.hide()
        self.assertIsNone(self.app.overlay._timer_id)
        self.assertEqual(self.app.overlay.state(),"withdrawn")

    def test_overlay_close_restores_main_instead_of_terminating(self):
        Jarvis.hide_main(self.app)
        self.app.update()
        self.app.overlay.restore_main()
        self.app.update()
        self.assertFalse(self.app._closing)
        self.assertEqual(self.app.state(),"normal")


if __name__=="__main__":
    unittest.main()
