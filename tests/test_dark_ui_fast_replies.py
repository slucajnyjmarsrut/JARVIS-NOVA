"""Dark NOVA interface and quick replies regression tests."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from local_chat import LocalChat

ROOT=Path(__file__).resolve().parents[1]

class AppearanceTests(unittest.TestCase):
    def test_chrome(self):
        main=(ROOT/"main.py").read_text(encoding="utf-8")
        self.assertIn("DwmSetWindowAttribute",main)
        self.assertNotIn("self.config(menu=menu)",main)
        self.assertIn("self.nova_settings_menu=menu",main)

    def test_sidebar_and_scroll(self):
        ui=(ROOT/"nova_ui.py").read_text(encoding="utf-8")
        self.assertLess(ui.index("app.hud_settings_button=_action"),
                        ui.index("app.mic_toggle_button=_action"))
        self.assertIn("scroll=ttk.Scrollbar(",ui)
        self.assertNotIn("scroll=tk.Scrollbar(",ui)

class QuickReplyTests(unittest.TestCase):
    def test_small_talk_skips_model(self):
        runtime=SimpleNamespace(config=SimpleNamespace(model="qwen3-vl:2b-instruct"),
                                start=Mock(side_effect=AssertionError("called")))
        chat=LocalChat(runtime)
        self.assertEqual(chat.ask("Как дела?"),"Всё хорошо. Чем помочь?")
        self.assertEqual(chat.ask("Что делаешь?"),"Жду твою команду.")
        runtime.start.assert_not_called()

    def test_work_requests_still_ask_model(self):
        requests=[]
        runtime=SimpleNamespace(config=SimpleNamespace(model="test"),
                                start=lambda:"http://127.0.0.1:11434")
        chat=LocalChat(runtime,requester=lambda endpoint,data:
                       (requests.append(data),{"message":{"content":"Готово"}})[1])
        self.assertEqual(chat.ask("Как дела с проектом?"),"Готово")
        self.assertEqual(len(requests),1)
        self.assertLessEqual(requests[0]["options"]["num_predict"],72)

if __name__=="__main__":
    unittest.main()
