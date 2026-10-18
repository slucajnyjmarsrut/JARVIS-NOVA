# -*- coding: utf-8 -*-
import unittest
from unittest.mock import Mock
from local_chat import LocalChat, ChatError, request_chat


class LocalChatTests(unittest.TestCase):
    def test_bundled_model_answers_without_remote_api(self):
        runtime = Mock()
        runtime.start.return_value = "http://127.0.0.1:21678"
        def request(url, payload):
            self.assertEqual(url, "http://127.0.0.1:21678")
            self.assertEqual(payload["model"], "qwen3-vl:2b-instruct")
            self.assertEqual(payload["messages"][1]["content"], "Кто ты?")
            self.assertFalse(payload["stream"])
            return {"message": {"content": "Я JARVIS NOVA."}}
        c = LocalChat(runtime_factory=lambda:runtime, requester=request)
        self.assertEqual(c.answer("Кто ты?"), "Я JARVIS NOVA.")
        runtime.stop.assert_called_once()

    def test_invalid_payload_closes_runtime(self):
        runtime=Mock()
        runtime.start.return_value="http://127.0.0.1:9999"
        c=LocalChat(runtime_factory=lambda:runtime,requester=lambda *args: {})
        with self.assertRaises(ChatError):c.answer("Привет")
        runtime.stop.assert_called_once()

    def test_no_chat_after_shutdown(self):
        c=LocalChat(runtime_factory=lambda:None)
        c.close()
        with self.assertRaises(ChatError):c.answer("Сколько времени")

    def test_empty_and_large_requests_fail_without_model(self):
        r=Mock()
        c=LocalChat(runtime_factory=r)
        for q in ["", "a"*701]:
            with self.assertRaises(ChatError):c.answer(q)
        r.assert_not_called()

    def test_remote_endpoints_not_allowed(self):
        with self.assertRaises(ChatError):request_chat("http://some-cloud.example:11434", {})
        with self.assertRaises(ChatError):request_chat("http://127.0.0.1:42/evil", {})


if __name__ == "__main__":
    unittest.main()
