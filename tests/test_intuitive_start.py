# -*- coding: utf-8 -*-
"""First-use guidance is actionable, understandable and consent-preserving."""
import unittest

from intuitive_start import (
    QUICK_ACTIONS, CLARIFICATIONS, initial_guidance, model_hint, clarification,
)
from chat_first_intent import route_chat_request


class IntuitiveStartTests(unittest.TestCase):
    def test_home_has_four_distinct_plain_russian_tasks(self):
        self.assertEqual(
            [key for _,key in QUICK_ACTIONS], ["video","edit","code","image"])
        for label,key in QUICK_ACTIONS:
            self.assertTrue(label.isupper())
            self.assertTrue(key)
            self.assertLessEqual(len(label),21)
        self.assertIn("СОЗДАТЬ ВИДЕО",dict(QUICK_ACTIONS))

    def test_model_status_is_truthful_and_does_not_install_by_itself(self):
        self.assertIn("не подключена",model_hint(False))
        self.assertIn("СКАЧАТЬ QWEN",model_hint(False))
        self.assertIn("подключена",model_hint(True))
        self.assertIn("для изображений",model_hint(True))
        self.assertIn("Qwen3:4b",model_hint(True))
        self.assertIn("Gemma3:4b",initial_guidance(True))
        self.assertNotIn("для переписки уже подключена",initial_guidance(True))
        self.assertIn("загружается",model_hint(False,True))
        self.assertNotIn("подключена",model_hint(False,True))
        self.assertIn("подтверди",initial_guidance(False))
        self.assertIn("Enter",initial_guidance(True))
        # The very first suggested sentence must work even with no Qwen.
        self.assertIn("хочу создать видео",initial_guidance(False))
        self.assertEqual(route_chat_request("хочу создать видео").kind,"studio")

    def test_ambiguous_requests_ask_questions_not_claim_execution(self):
        self.assertEqual(
            set(CLARIFICATIONS),
            {"clarify_video","clarify_model","clarify_screen","clarify_code"})
        for kind in CLARIFICATIONS:
            with self.subTest(kind=kind):
                explanation=clarification(kind)
                self.assertIn("?",explanation)
                self.assertGreater(len(explanation),60)
                self.assertNotIn("Я уже запустил",explanation)
        self.assertEqual(clarification("no_such_action"),"")
        self.assertIn("отдельное подтверждение",
                      clarification("clarify_screen"))
        self.assertIn("СМОНТИРОВАТЬ",clarification("clarify_video"))
        self.assertIn("ИИ ПО ЗАДАЧАМ",clarification("clarify_model"))
        self.assertIn("Gemma3",clarification("clarify_model"))


if __name__=="__main__":
    unittest.main()
