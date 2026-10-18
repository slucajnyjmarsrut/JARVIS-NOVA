# -*- coding: utf-8 -*-
"""Regression tests for visible real AI chat routing without Tk hardware."""
import queue
import unittest
from unittest.mock import Mock
from main import Jarvis


class RealChatRoutingTests(unittest.TestCase):
    @staticmethod
    def app():
        app=Mock()
        app._closing=False
        app.executing=False
        app.engine="local"
        app.q=queue.Queue()
        app.modes.parse.return_value=None
        app.voice.vision_source.return_value=None
        app.chat.answer.return_value="Я JARVIS NOVA."
        return app

    def test_natural_question_uses_offline_chat_instead_of_unknown_command(self):
        app=self.app()
        Jarvis.handle_text(app,"Кто ты?")
        tag,result=app.q.get(timeout=5)
        self.assertEqual(tag,"chat_result")
        self.assertEqual(result,(True,"Я JARVIS NOVA."))
        app.chat.answer.assert_called_once_with("Кто ты?")
        app.execute_plan.assert_not_called()

    def test_windows_command_uses_safe_local_parser_not_ai(self):
        app=self.app()
        Jarvis.handle_text(app,"джарвис открой хром")
        app.execute_plan.assert_called_once()
        self.assertEqual(app.execute_plan.call_args.args[0].steps[0].kind,"open_app")
        app.chat.answer.assert_not_called()

    def test_does_not_start_two_llms_simultaneously(self):
        app=self.app()
        app.executing=True
        Jarvis.handle_text(app,"Расскажи о себе")
        app.chat.answer.assert_not_called()
        app.reply.assert_called_once()


if __name__=="__main__":
    unittest.main()
