# -*- coding: utf-8 -*-
"""Offline conversational answers with the REAL bundled local Qwen Vision model.

This module never executes suggested Windows actions and never sends data to
cloud APIs. The same BundledVisionRuntime instance is shared with Stage 2.
"""
from __future__ import annotations
import json
import threading
from urllib.parse import urlsplit
import urllib.request


class LocalChatError(RuntimeError):
    pass


class LocalChat:
    def __init__(self, runtime, requester=None):
        self.runtime = runtime
        self._requester = requester or self._request
        self.model = runtime.config.model
        self._conversation = []
        self._lock = threading.Lock()
        self._closed = False

    def close(self):
        # Forget conversation when app exits. The shared runtime is owned by TrimodalService.
        self._closed = True
        self._conversation.clear()

    @staticmethod
    def _request(endpoint: str, payload: dict) -> dict:
        parts = urlsplit(endpoint)
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
                or not (1 <= (parts.port or 0) <= 65535) or
                parts.path or parts.query or parts.fragment or parts.username):
            raise LocalChatError("Локальная модель должна отвечать только с 127.0.0.1")
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
        if self._closed:
            raise LocalChatError("JARVIS закрывается")
        if not self._lock.acquire(blocking=False):
            raise LocalChatError("Предыдущий ответ ещё обрабатывается")
        try:
            return self._ask_locked(question)
        finally:
            self._lock.release()

    def _ask_locked(self, question: str) -> str:
        if self._closed:
            raise LocalChatError("JARVIS закрывается")
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
                *self._conversation,
                {"role": "user", "content": question},
            ],
            "options": {"num_predict": 220, "temperature": 0.35},
        }
        result = self._requester(endpoint, payload)
        answer = result.get("message", {}).get("content", "") if isinstance(result, dict) else ""
        if not isinstance(answer, str) or not answer.strip():
            raise LocalChatError("Локальная модель не дала ответа")
        if self._closed:
            raise LocalChatError("JARVIS закрывается")
        answer = answer.strip()[:2500]
        # Up to four recent turns, only in RAM; never saves speech or conversations.
        self._conversation = (
            self._conversation + [{"role": "user", "content": question},
                                  {"role": "assistant", "content": answer}])[-8:]
        return answer
