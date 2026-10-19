import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_chat import LocalChat, LocalChatError


class FakeRuntime:
    config = SimpleNamespace(model="qwen3-vl:2b-instruct")
    def __init__(self):
        self.calls = 0
    def start(self):
        self.calls += 1
        return "http://127.0.0.1:23123"


class LocalChatTests(unittest.TestCase):
    def test_model_runs_locally_and_never_requests_tools(self):
        runtime = FakeRuntime()
        captured = {}
        def requester(endpoint, payload):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"message": {"content": "Привет! Я JARVIS."}}
        chat = LocalChat(runtime, requester=requester)
        self.assertEqual(chat.ask("Привет"), "Привет! Я JARVIS.")
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(captured["endpoint"], "http://127.0.0.1:23123")
        self.assertEqual(captured["payload"]["model"], "qwen3-vl:2b-instruct")
        self.assertEqual(captured["payload"]["messages"][-1]["content"], "Привет")
        self.assertEqual(captured["payload"]["stream"], False)
        self.assertNotIn("tools", captured["payload"])

    def test_followup_context_is_short_and_ram_only(self):
        captured=[]
        chat=LocalChat(FakeRuntime(),requester=lambda _,payload: (
            captured.append(payload["messages"]), {"message":{"content":"Ответ"}})[1])
        self.assertEqual(chat.ask("Кто ты?"),"Ответ")
        self.assertEqual(chat.ask("А подробнее?"),"Ответ")
        self.assertEqual(captured[1][-3]["content"],"Кто ты?")
        self.assertEqual(captured[1][-2]["content"],"Ответ")
        self.assertEqual(captured[1][-1]["content"],"А подробнее?")
        chat.close()
        with self.assertRaises(LocalChatError):
            chat.ask("Новый вопрос")

    def test_chat_refuses_external_hosts(self):
        for host in ("https://127.0.0.1:1234", "http://localhost:1234",
                     "http://example.com:1234", "http://127.0.0.1:1234/path"):
            with self.subTest(host=host),self.assertRaises(LocalChatError):
                LocalChat._request(host, {"messages":[]})

    def test_rejects_empty_and_unreasonably_long_prompts(self):
        chat = LocalChat(FakeRuntime(), requester=lambda *_: None)
        for prompt in ("", " " * 3, "x" * 1201):
            with self.subTest(value=prompt[:8]), self.assertRaises(LocalChatError):
                chat.ask(prompt)

    def test_empty_model_answer_fails_explicitly(self):
        chat = LocalChat(FakeRuntime(), requester=lambda *_: {"message": {"content": "  "}})
        with self.assertRaises(LocalChatError):
            chat.ask("Что ты умеешь?")


if __name__ == "__main__":
    unittest.main()
