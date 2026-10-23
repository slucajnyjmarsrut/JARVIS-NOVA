"""NOVA HUD presentation tests; no voice model, audio device or API calls."""
import tkinter as tk
import time
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nova_ui import (AMBER, CYAN, GREEN, MUTED, RED, VIOLET,
                     build_interface, level_readout, visual_state)


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


class LevelReadoutTests(unittest.TestCase):
    def test_real_rms_math_with_explicit_no_data(self):
        self.assertEqual(level_readout(None),(0.0,"НЕТ ДАННЫХ"))
        fraction, caption = level_readout(.01)
        self.assertAlmostEqual(fraction,25/60,places=3)
        self.assertEqual(caption,"-40 dBFS")
        self.assertEqual(level_readout(0.0),(0.0,"ТИШИНА"))
        self.assertEqual(level_readout(float("nan")),(0.0,"НЕТ ДАННЫХ"))
        self.assertEqual(level_readout(1.0),(1.0,"0 dBFS"))


class HudWidgetTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app=tk.Tk()
        except tk.TclError as exc:
            if __import__("sys").platform=="win32":
                self.fail("Windows GUI runner must have Tk: "+str(exc))
            self.skipTest("Tk display unavailable: "+str(exc))
        self.app.withdraw()
        self.app._closing=False
        self.app.voice_enabled=False
        self.app.executing=False
        self.app.engine="bundled"
        self.app.speaker=SimpleNamespace(busy=False)
        self.app.trimodal=SimpleNamespace(speaking=False)
        # An unusual user-adjusted setting proves the HUD never resets the
        # live mic sensitivity to a hard-coded 1.0 during initialization.
        self.app.voice=SimpleNamespace(sensitivity=1.35,set_sensitivity=Mock())
        self.actions={}
        for name in ("toggle_voice","select_microphone","test_microphone",
                     "f9","enter","open_viral_studio","activate_mode",
                     "request_trimodal","show_capabilities","revoke"):
            callback=Mock()
            self.actions[name]=callback
            setattr(self.app,name,callback)
        build_interface(self.app)
        self.app.update_idletasks()

    def tearDown(self):
        if hasattr(self,"app"):
            self.app._closing=True
            self.app.destroy()
            self.assertIsNone(self.app._nova_after_id,
                              "Destroy must cancel the scheduled animation")

    def test_widgets_and_shortcuts_exist(self):
        self.assertEqual(self.app.history.cget("state"),"disabled")
        self.assertEqual(self.app.mic_toggle_button.cget("text"),
                         "ВКЛЮЧИТЬ МИКРОФОН")
        self.assertTrue(self.app.entry.winfo_exists())
        self.app.mic_toggle_button.invoke()
        self.actions["toggle_voice"].assert_called_once()
        self.assertIsNotNone(self.app.bind("<F9>"))
        self.assertIsNotNone(self.app.bind("<Control-l>"))
        self.assertIsNotNone(self.app.bind("<Control-Shift-M>"))
        self.assertIsNotNone(self.app.bind("<Control-Shift-R>"))

    def test_live_state_and_cloud_indicator(self):
        self.app.voice_enabled=True
        self.app.engine="openai"
        self.app.mic_state.set("Микрофон: включён")
        time.sleep(.17)
        self.app.update()
        self.assertEqual(self.app.mic_toggle_button.cget("text"),
                         "ОТКЛЮЧИТЬ МИКРОФОН")
        self.assertIn("СЕТЬ",self.app.hud_engine.cget("text"))

    def test_reactor_draws_vector_layers_and_supports_reduced_motion(self):
        self.app.hud_animate.set(False)
        self.assertFalse(self.app.hud_animate.get())
        with patch.object(type(self.app.hud_reactor),"winfo_viewable",return_value=True):
            self.app.hud_reactor.paint("listening")
        self.assertGreaterEqual(len(self.app.hud_reactor.find_all()),60)
        self.assertEqual(self.app.hud_reactor._mode,"listening")
        with patch.object(type(self.app.hud_reactor),"winfo_viewable",return_value=True):
            self.app.hud_reactor.paint("listening",.1)
        self.assertGreater(self.app.hud_reactor.last_energy,0)

    def test_mic_meter_shows_live_rms_and_stales_out(self):
        self.app.voice_enabled=True
        self.app.mic_state.set("Микрофон: включён")
        self.app.hud_level_value=.02
        self.app.hud_level_at=time.monotonic()
        time.sleep(.17)
        self.app.update()
        self.assertIn("dBFS",self.app.hud_meter_label.cget("text"))
        self.assertGreater(self.app.hud_meter.last_fraction,0)
        self.app.hud_level_at=time.monotonic()-5
        time.sleep(.17)
        self.app.update()
        self.assertIn("НЕТ ДАННЫХ",self.app.hud_meter_label.cget("text"))
        self.app.voice_enabled=False
        time.sleep(.17)
        self.app.update()
        self.assertIn("ВЫКЛ.",self.app.hud_meter_label.cget("text"))

    def test_privacy_labels_reveal_granted_permissions(self):
        self.app.control_allowed=True
        self.app.vision_allowed=True
        time.sleep(.17)
        self.app.update()
        self.assertIn("УПРАВЛЕНИЕ: ДОСТУП",self.app.hud_access.cget("text"))
        self.assertIn("ЗРЕНИЕ*: ДОСТУП",self.app.hud_access.cget("text"))
        self.app.control_allowed=False
        self.app.vision_allowed=False
        time.sleep(.17)
        self.app.update()
        self.assertIn("УПРАВЛЕНИЕ: ЗАПРЕТ",self.app.hud_access.cget("text"))

    def test_quick_actions_remain_in_left_rail_even_when_chat_resizes(self):
        self.app.hud_reflow(SimpleNamespace(width=480))
        self.assertEqual(self.app.hud_shortcut_columns,2)
        self.assertEqual(int(self.app.hud_shortcut_buttons[4].grid_info()["row"]),3)
        self.app.hud_reflow(SimpleNamespace(width=820))
        self.assertEqual(self.app.hud_shortcut_columns,2)
        self.assertEqual(int(self.app.hud_shortcut_buttons[4].grid_info()["row"]),3)
        self.app.update_idletasks()
        self.assertIs(self.app.hud_shortcuts.master,self.app.hud_rail)
        self.assertIsNot(self.app.hud_chat,self.app.hud_rail)
        self.app.hud_shortcut_buttons[1].invoke()
        self.actions["activate_mode"].assert_called_with("gaming")

    def test_mic_sensitivity_scale_preserves_engine_setting(self):
        self.assertAlmostEqual(float(self.app.hud_sensitivity.get()),1.35)
        self.assertIn("1.35",self.app.hud_sensitivity_readout.cget("text"))
        self.assertNotIn(1.0,[call.args[0]
            for call in self.app.voice.set_sensitivity.call_args_list])
        self.app.hud_sensitivity.set(1.8)
        self.assertIn("1.80",self.app.hud_sensitivity_readout.cget("text"))
        self.app.voice.set_sensitivity.assert_called_with(1.8)

    def test_current_mode_and_real_focus_timer_display(self):
        self.app.modes=SimpleNamespace(mode="study")
        self.app._focus_deadline=time.monotonic()+95
        time.sleep(.17)
        self.app.update()
        self.assertIn("УЧЁБА",self.app.hud_footer.cget("text"))
        self.assertEqual(self.app.hud_mode_buttons["study"].cget("bg"),"#236C80")
        self.assertIn("ФОКУС",self.app.hud_footer.cget("text"))

    def test_conversation_is_read_only_until_log_writes(self):
        self.assertEqual(self.app.history.cget("state"),"disabled")
        self.app.history.configure(state="normal")
        self.app.history.insert("end","Вы: ",("Вы",))
        self.app.history.insert("end","Привет")
        self.app.history.configure(state="disabled")
        self.assertIn("Привет",self.app.history.get("1.0","end"))


if __name__=="__main__":
    unittest.main()
