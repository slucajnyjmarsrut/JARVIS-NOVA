"""NOVA HUD presentation tests; no voice model, audio device or API calls."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from nova_ui import (AMBER, CYAN, GREEN, MUTED, RED, VIOLET,
                     build_interface, visual_state)


class HudLogicTests(unittest.TestCase):
    def test_off_state_beats_old_listening_message(self):
        self.assertEqual(visual_state(False, "Микрофон: выключен",
                                      "Vosk готов")[0], "offline")

    def test_recognition_status(self):
        mode, caption, color = visual_state(
            True, "Микрофон: жду команду (8 секунд)", "Готов")
        self.assertEqual((mode,color),("listening",CYAN))
        self.assertIn("СЛУШАЮ",caption)

    def test_speaker_and_processing_take_priority(self):
        self.assertEqual(visual_state(True,"ready","x",speaking=True),
                         ("speaking","ОТВЕЧАЮ",GREEN))
        self.assertEqual(visual_state(True,"ready","x",executing=True)[2],
                         VIOLET)

    def test_error_does_not_look_like_ready(self):
        self.assertEqual(visual_state(False,"Микрофон: ошибка устройства",
                                      "Ошибка микрофона: PortAudio")[2],RED)

    def test_boot_and_idle(self):
        self.assertEqual(visual_state(True,"Микрофон: подключается…","")[2],AMBER)
        self.assertEqual(visual_state(False,"Микрофон: выключен","")[2],MUTED)
        self.assertEqual(visual_state(True,"Микрофон: включён","В порядке")[0],"ready")


class HudWidgetTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app=tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display unavailable: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.engine="bundled"
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        self.actions={}
        for name in ("toggle_voice","select_microphone","test_microphone",
                     "f9","enter","open_viral_studio","activate_mode",
                     "request_trimodal","show_capabilities"):
            callback=Mock()
            self.actions[name]=callback
            setattr(self.app,name,callback)
        build_interface(self.app)
        self.app.update_idletasks()

    def tearDown(self):
        if hasattr(self,"app"):
            self.app._closing=True
            self.app.destroy()

    def test_widgets_and_shortcuts_exist(self):
        self.assertEqual(self.app.history.cget("state"),"disabled")
        self.assertEqual(self.app.mic_toggle_button.cget("text"),
                         "ВКЛЮЧИТЬ МИКРОФОН")
        self.assertTrue(self.app.entry.winfo_exists())
        self.app.mic_toggle_button.invoke()
        self.actions["toggle_voice"].assert_called_once()
        self.assertIsNotNone(self.app.bind("<F9>"))
        self.assertIsNotNone(self.app.bind("<Control-l>"))

    def test_live_state_and_cloud_indicator(self):
        self.app.voice_enabled=True
        self.app.engine="openai"
        self.app.mic_state.set("Микрофон: включён")
        self.app.update()
        self.assertEqual(self.app.mic_toggle_button.cget("text"),
                         "ОТКЛЮЧИТЬ МИКРОФОН")
        self.assertIn("СЕТЬ",self.app.hud_engine.cget("text"))

    def test_conversation_is_read_only_until_log_writes(self):
        self.assertEqual(self.app.history.cget("state"),"disabled")
        self.app.history.configure(state="normal")
        self.app.history.insert("end","Вы: ",("Вы",))
        self.app.history.insert("end","Привет")
        self.app.history.configure(state="disabled")
        self.assertIn("Привет",self.app.history.get("1.0","end"))


if __name__=="__main__":
    unittest.main()
