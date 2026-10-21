# -*- coding: utf-8 -*-
"""Fast Russian replies and safe local app aliases (zero network/models)."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from local_chat import LocalChat
from agent_core import parse_local, validate_plan


class FastRoutesTests(unittest.TestCase):
    def test_extended_smalltalk_skips_qwen(self):
        runtime = SimpleNamespace(config=SimpleNamespace(model="local"),
                                  start=Mock(side_effect=AssertionError("Qwen started")))
        chat = LocalChat(runtime)
        samples = ("Доброе утро!", "Ты здесь?", "Что ты умеешь?",
                   "До свидания!", "Кто ты?", "Помоги", "Благодарю!")
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(chat.ask(text))
        runtime.start.assert_not_called()

    def test_normal_nontrivial_questions_still_use_local_qwen(self):
        runtime = SimpleNamespace(config=SimpleNamespace(model="local"),
                                  start=Mock(return_value="http://127.0.0.1:11434"))
        chat = LocalChat(runtime, requester=lambda ep,p: {"message":{"content":"Ответ"}})
        self.assertEqual(chat.ask("Как написать презентацию?"), "Ответ")
        runtime.start.assert_called_once()

    def test_more_popular_programs_use_local_allowlisted_open_action(self):
        mappings = {"файрфокс":"Mozilla Firefox", "эдж":"Microsoft Edge",
                    "пейнт":"Paint", "ворд":"Word", "эксель":"Excel",
                    "пауэрпоинт":"PowerPoint", "влс":"VLC media player",
                    "обс":"OBS Studio", "спотифай":"Spotify",
                    "вс код":"Visual Studio Code", "зум":"Zoom",
                    "фотошоп":"Adobe Photoshop"}
        for alias, official in mappings.items():
            with self.subTest(alias=alias):
                plan = parse_local("Джарвис, открой " + alias)
                self.assertEqual(len(plan.steps),1)
                self.assertEqual(plan.steps[0].kind,"open_app")
                self.assertEqual(plan.steps[0].value,official)
                validate_plan(plan)

    def test_shell_commands_remain_refused(self):
        for cmd in ("cmd", "powershell", "regedit"):
            plan=parse_local("открой " + cmd)
            self.assertEqual(plan.steps,[])
            self.assertIn("не поддерживается",plan.question)

if __name__ == "__main__":
    unittest.main()
