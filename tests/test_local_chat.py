import unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_chat import LocalChat, LocalChatError, _NoExternalRedirect, explain_local_model_failure
from bundled_vision_runtime import BundledRuntimeError


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
        self.assertEqual(chat.ask("Расскажи о себе"), "Привет! Я JARVIS.")
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(captured["endpoint"], "http://127.0.0.1:23123")
        self.assertEqual(captured["payload"]["model"], "qwen3-vl:2b-instruct")
        self.assertEqual(captured["payload"]["messages"][-1]["content"], "Расскажи о себе")
        self.assertEqual(captured["payload"]["stream"], False)
        self.assertNotIn("tools", captured["payload"])

    def test_detailed_questions_get_room_for_real_explanations(self):
        messages = []
        chat = LocalChat(FakeRuntime(), requester=lambda _url, data: (
            messages.append(data), {"message": {"content": "Тестовый ответ"}}
        )[1])
        chat.ask("Что такое Docker?")
        self.assertEqual(messages[-1]["options"]["num_predict"], 112)
        self.assertEqual(messages[-1]["options"]["num_ctx"], 1536)
        chat.ask("Объясни подробно по шагам, как устроена контейнеризация.")
        self.assertEqual(messages[-1]["options"]["num_predict"], 256)
        self.assertEqual(messages[-1]["options"]["num_ctx"], 2560)
        self.assertFalse(messages[-1]["think"])
        self.assertNotIn("tools", messages[-1])

    def test_private_runtime_errors_are_sanitized_without_fake_model_diagnosis(self):
        for error in (
            OSError("C:/Users/Alice/private/token.json"),
            RuntimeError(r"C:\\Users\\Alice\\private.txt"),
            RuntimeError("api_key=very-secret-value"),
            RuntimeError("/home/person/private/model.bin"),
        ):
            with self.subTest(message=str(error)):
                message = explain_local_model_failure(error)
                self.assertNotIn("Alice", message)
                self.assertNotIn("person", message)
                self.assertNotIn("very-secret", message)
                self.assertNotIn("token.json", message)
                self.assertIn("Ollama", message)

    def test_debate_is_opt_in_and_returns_to_normal(self):
        payloads=[]
        chat=LocalChat(FakeRuntime(),requester=lambda _,data: (
            payloads.append(data), {"message":{"content":"Контраргумент"}})[1])
        chat.ask("Обычный вопрос")
        self.assertNotIn("РЕЖИМ ДИСКУССИИ",payloads[-1]["messages"][0]["content"])
        chat.set_debate_mode(True)
        chat.ask("Тесты программ не нужны")
        self.assertIn("РЕЖИМ ДИСКУССИИ",payloads[-1]["messages"][0]["content"])
        self.assertEqual(payloads[-1]["options"]["num_predict"],240)
        self.assertNotIn("tools",payloads[-1])
        chat.set_debate_mode(False)
        chat.ask("А теперь обычный ответ")
        self.assertNotIn("РЕЖИМ ДИСКУССИИ",payloads[-1]["messages"][0]["content"])
        with self.assertRaises(ValueError):
            chat.set_debate_mode("yes")
        chat.close()
        self.assertFalse(chat.debate_mode)

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

    def test_text_greetings_never_claim_audio_listening(self):
        runtime = FakeRuntime()
        chat = LocalChat(runtime)
        for greeting in ("Привет!", "Здравствуй!", "Добрый день", "Добрый вечер"):
            answer = chat.ask(greeting)
            self.assertIn("помо", answer.casefold())
            self.assertNotIn("слушаю", answer.casefold())
        self.assertEqual(runtime.calls, 0)

    def test_missing_model_error_is_actionable_without_private_path(self):
        error = BundledRuntimeError(
            "Missing offline Vision model manifest: C:/Users/test/Models/ollama/manifests/foo")
        message = explain_local_model_failure(error)
        self.assertIn("СКАЧАТЬ QWEN", message)
        self.assertNotIn("повреждены", message)
        self.assertNotIn("C:/Users", message)
        self.assertNotIn("manifest", message)

    def test_corrupt_model_error_is_distinguished_from_missing_model(self):
        error=BundledRuntimeError("blob SHA256 mismatch in private path")
        message=explain_local_model_failure(error)
        self.assertIn("целостности",message)
        self.assertIn("СКАЧАТЬ QWEN",message)
        self.assertNotIn("private path",message)

    def test_non_model_error_is_not_misreported_as_missing_weights(self):
        message = explain_local_model_failure(RuntimeError("Connection refused"))
        self.assertIn("Connection refused", message)
        self.assertNotIn("файлы повреждены", message)

    def test_missing_dedicated_chat_rechecks_after_ollama_install(self):
        from unittest.mock import Mock
        runtime = FakeRuntime()
        transport = Mock(return_value={"message": {"content": "Модель готова"}})
        chat = LocalChat(runtime, requester=transport)
        chat.prefer_task_specialist(True)
        with patch("task_ai_registry.specialist_available",
                   side_effect=[False, True]) as present, patch(
                   "local_chat.time.monotonic", side_effect=[100., 105., 121.]):
            with self.assertRaises(LocalChatError):
                chat.ask("Расскажи о городе")
            with self.assertRaises(LocalChatError):
                chat.ask("Расскажи о городе")
            self.assertEqual(present.call_count, 1)
            self.assertEqual(chat.ask("Расскажи о городе"), "Модель готова")
            self.assertEqual(present.call_count, 2)
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(transport.call_args.args[1]["model"], "qwen3:4b")

    def test_chat_refuses_external_hosts(self):
        for host in ("https://127.0.0.1:1234", "http://localhost:1234",
                     "http://example.com:1234", "http://127.0.0.1:1234/path",
                     "http://:password@127.0.0.1:1234",
                     "http://@127.0.0.1:1234",
                     "http://user:pass@127.0.0.1:1234"):
            with self.subTest(host=host),self.assertRaises(LocalChatError):
                LocalChat._request(host, {"messages":[]})

    def test_model_http_redirect_never_leaks_local_chat_to_external_host(self):
        handler = _NoExternalRedirect()
        for url in (
            "https://attacker.example/collect",
            "http://127.0.0.1:3000/elsewhere",
            "http://localhost:11434/api/chat",
        ):
            with self.subTest(url=url), self.assertRaises(LocalChatError):
                handler.redirect_request(None, None, 307, "redirect", {}, url)

        # Verify the real requester actually registers the no-redirect handler.
        recorded = []
        class FakeReply:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return b'{"message":{"content":"OK"}}'
        class FakeOpener:
            def open(self, request, timeout):
                self.url = request.full_url
                return FakeReply()
        def opener(*handlers):
            recorded.extend(handlers)
            return FakeOpener()
        with patch.object(urllib.request, "build_opener", side_effect=opener):
            response = LocalChat._request("http://127.0.0.1:11434", {"messages":[]})
        self.assertEqual(response["message"]["content"], "OK")
        self.assertTrue(any(isinstance(h, _NoExternalRedirect) for h in recorded))
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler)
                            and not h.proxies for h in recorded))

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
