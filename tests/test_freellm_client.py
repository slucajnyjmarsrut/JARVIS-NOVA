# -*- coding: utf-8 -*-
"""FreeLLM gateway regressions: no internet or actual API keys required."""
import os
import unittest
from unittest.mock import patch

from freellm_client import FreeLLMChat, FreeLLMError, validated_base_url


class GatewayTests(unittest.TestCase):
    def test_only_loopback_endpoint(self):
        for url in ("http://127.0.0.1:4000/v1",
                    "http://localhost:3001/v1",
                    "http://[::1]:4000/v1"):
            self.assertEqual(validated_base_url(url),url)
        for url in (
            "https://attacker.example/v1", "http://1.2.3.4:4000/v1",
            "http://127.0.0.1:4000", "http://127.0.0.1:4000/v1?token=abc",
            "http://name:pass@localhost:4000/v1", "file:///tmp/token",
            "http://127.0.0.1:4000/v1/extra", "http://localhost:0/v1"):
            with self.subTest(url=url), self.assertRaises(FreeLLMError):
                validated_base_url(url)

    def test_key_only_in_authorization_header_not_body(self):
        requests=[]
        def send(url, payload, headers, timeout):
            requests.append((url, payload, headers, timeout))
            return {"choices":[{"message":{"content":"Текстовый ответ"}}]}
        with patch.dict(os.environ, {"FREELLM_API_KEY":"test-key-do-not-publish"}):
            client=FreeLLMChat(transport=send)
            self.assertEqual(client.ask("Напиши пример Java"),"Текстовый ответ")
        url, payload, headers, timeout=requests[0]
        self.assertEqual(url,"http://127.0.0.1:4000/v1/chat/completions")
        self.assertEqual(headers["Authorization"],"Bearer test-key-do-not-publish")
        self.assertNotIn("test-key-do-not-publish",str(payload))
        self.assertEqual(payload["model"],"auto")
        self.assertEqual(timeout,90)

    def test_conversation_is_bounded_and_memory_only(self):
        calls=[]
        def send(url, payload, headers, timeout):
            calls.append(payload)
            return {"choices":[{"message":{"content":"OK"}}]}
        client=FreeLLMChat(transport=send)
        for i in range(6):
            self.assertEqual(client.ask("Вопрос "+str(i)),"OK")
        self.assertEqual(len(client._history),8)
        self.assertEqual(len(calls[-1]["messages"]),10)
        client.close()
        self.assertFalse(client._history)
        with self.assertRaises(FreeLLMError):
            client.ask("Привет")

    def test_code_uses_separate_context_and_model(self):
        requests=[]
        def send(url,payload,headers,timeout):
            requests.append(payload)
            return {"choices":[{"message":{"content":'{"language":"java","files":[]}'}}]}
        with patch.dict(os.environ,{"FREELLM_CODE_MODEL":"auto-code"}):
            client=FreeLLMChat(transport=send)
            client.ask("Секретный прежний чат")
            client.generate_code("Создай Main.java","java")
        self.assertEqual(requests[1]["model"],"auto-code")
        self.assertEqual(len(requests[1]["messages"]),2)
        self.assertNotIn("Секретный прежний чат",str(requests[1]))

    def test_missing_or_empty_reply_fails_closed(self):
        client=FreeLLMChat(transport=lambda *args: {"choices":[]})
        with self.assertRaisesRegex(FreeLLMError,"не вернул"):
            client.ask("Вопрос")

    def test_no_key_required_when_gateway_is_local(self):
        def send(url,payload,headers,timeout):
            self.assertNotIn("Authorization",headers)
            return {"choices":[{"message":{"content":"Hello"}}]}
        with patch.dict(os.environ,{"FREELLM_API_KEY":""}):
            self.assertEqual(FreeLLMChat(transport=send).ask("Hi"),"Hello")

    def test_code_requires_valid_language(self):
        client=FreeLLMChat(transport=lambda *args:None)
        with self.assertRaises(FreeLLMError):
            client.generate_code("x","python")


if __name__=="__main__":
    unittest.main()
