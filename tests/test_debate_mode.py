# -*- coding: utf-8 -*-
"""Debate mode commands remain explicit, reversible and action-free."""
import unittest
from unittest.mock import Mock
from debate_mode import debate_command
from main import Jarvis
from nova_command_palette import entries

class DebateModeTests(unittest.TestCase):
    def test_exact_commands_and_wake_word(self):
        for command in ("Давай поспорим!", "Спорь со мной",
                        "Включи режим спора", "Джарвис, давай поспорим",
                        "Эй, Джарвис, включи режим дебатов"):
            with self.subTest(command=command):
                self.assertEqual(debate_command(command),"on")
        for command in ("Хватит спорить", "Не спорь со мной!",
                        "Отключи режим спора", "Верни обычный режим"):
            with self.subTest(command=command):
                self.assertEqual(debate_command(command),"off")
        self.assertEqual(debate_command("Режим спора?"),"status")

    def test_casual_mentions_and_desktop_commands_not_intercepted(self):
        for command in ("Расскажи про режим спора","Почему люди спорят?",
                        "Открой браузер","Джарвис, открой Chrome",
                        "Напиши код спора","Мой тезис: давай поспорим",
                        "Когда я сказал давай поспорим, он засмеялся",
                        "","х"*181):
            with self.subTest(command=command):
                self.assertIsNone(debate_command(command))

    def test_main_routes_without_exec_or_coding(self):
        app=Mock()
        app._closing=False
        app._debate_mode=False
        Jarvis.handle_text(app,"Давай поспорим!")
        app.set_debate_mode.assert_called_once_with(True)
        app.open_code_assistant.assert_not_called()
        app.execute_plan.assert_not_called()
        app.set_debate_mode.reset_mock()
        Jarvis.handle_text(app,"Режим спора?")
        app.reply.assert_called_with("Режим спора выключен.")
        app.set_debate_mode.assert_not_called()

    def test_both_clients_update_without_permissions(self):
        app=Mock()
        app._closing=False
        app.executing=False
        app._debate_mode=False
        Jarvis.set_debate_mode(app,True)
        self.assertTrue(app._debate_mode)
        app.local_chat.set_debate_mode.assert_called_once_with(True)
        app.freellm_chat.set_debate_mode.assert_called_once_with(True)
        app.execute_plan.assert_not_called()
        Jarvis.set_debate_mode(app)
        self.assertFalse(app._debate_mode)
        app.local_chat.set_debate_mode.assert_called_with(False)

    def test_cannot_change_mode_during_pending_response(self):
        app=Mock()
        app._closing=False
        app.executing=True
        app._debate_mode=False
        Jarvis.set_debate_mode(app,True)
        self.assertFalse(app._debate_mode)
        app.local_chat.set_debate_mode.assert_not_called()

    def test_palette_exposes_toggle(self):
        app=Mock()
        item=next(entry for entry in entries(app)
                  if entry is not None and "Режим спора" in entry[1])
        item[2]()
        app.set_debate_mode.assert_called_once_with()

if __name__=="__main__":
    unittest.main()
