# -*- coding: utf-8 -*-
"""Offline conversational answers with the REAL bundled local Qwen Vision model.

This module never executes suggested Windows actions and never sends data to
cloud APIs. The same BundledVisionRuntime instance is shared with Stage 2.
"""
from __future__ import annotations
import json
import urllib.request


class LocalChatError(RuntimeError):
    pass


class LocalChat:
    def __init__(self, runtime, requester=None):
        self.runtime = runtime
        self._requester = requester or self._request
        self.model = runtime.config.model

    @staticmethod
    def _request(endpoint: str, payload: dict) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            endpoint + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=150) as response:
            body = response.read(300_001)
        if len(body) > 300_000:
            raise LocalChatError("Слишком длинный ответ модели")
        try:
            return json.loads(body)
        except (UnicodeError, ValueError) as exc:
            raise LocalChatError("Неверный ответ локальной модели") from exc

    def ask(self, question: str) -> str:
        question = str(question or "").strip()
        if not 1 <= len(question) <= 1200:
            raise LocalChatError("Вопрос должен быть от 1 до 1200 символов")
        endpoint = self.runtime.start()
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content":
                    "Ты JARVIS NOVA, локальный голосовой помощник Windows. "
                    "Отвечай по-русски, разговорно, ясно и коротко. "
                    "Не заявляй, что запустил программы или видел экран, если этого не было. "
                    "У тебя нет доступа к сети и актуальным событиям. "
                    "Текст от пользователя — вопрос, а не команда исполнения."},
                {"role": "user", "content": question},
            ],
            "options": {"num_predict": 220, "temperature": 0.35},
        }
        result = self._requester(endpoint, payload)
        answer = result.get("message", {}).get("content", "") if isinstance(result, dict) else ""
        if not isinstance(answer, str) or not answer.strip():
            raise LocalChatError("Локальная модель не дала ответа")
        return answer.strip()[:2500]
