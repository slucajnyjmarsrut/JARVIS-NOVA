# -*- coding: utf-8 -*-
"""Conversational responses from the ALREADY bundled local Qwen Vision model.

No cloud, no arbitrary Windows actions, no camera or microphone access.
The runtime is deliberately scoped to one request to free RAM for real Vision
and to ensure closing JARVIS never leaves a permanently running AI process.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import threading
import urllib.request
from bundled_vision_runtime import BundledVisionRuntime, BundledRuntimeConfig


class ChatError(RuntimeError):
    pass


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


def request_chat(endpoint: str, payload: dict, *, timeout: int = 150) -> dict:
    # Forbid changing the target host; the only transport is this app's localhost server.
    if not endpoint.startswith("http://127.0.0.1:"):
        raise ChatError("Локальный сервер должен работать только на 127.0.0.1")
    from urllib.parse import urlsplit
    parts = urlsplit(endpoint)
    if parts.hostname != "127.0.0.1" or not (1 <= (parts.port or 0) <= 65535) or parts.path or parts.query:
        raise ChatError("Недопустимый адрес локального сервера")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(endpoint + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read(120_001)
    if len(data) > 120_000:
        raise ChatError("Слишком длинный ответ локальной модели")
    return json.loads(data)


SYSTEM = (
    "Ты JARVIS NOVA, локальный русскоязычный помощник Windows. "
    "Отвечай на разговорные вопросы кратко, понятно, по-русски. "
    "Если не знаешь ответа, честно скажи об этом. "
    "Не утверждай, что смотрел камеру, экран, телефон, интернет, файлы или канал, "
    "если тебе не передали их содержимое. "
    "Ты отвечаешь ТОЛЬКО текстом и никогда не выполняешь системных действий. "
    "При вопросах о программах кратко подскажи голосовую команду или раздел интерфейса."
)


class LocalChat:
    def __init__(self, *, runtime_factory=None, requester=None):
        self._runtime_factory = runtime_factory or (
            lambda: BundledVisionRuntime(BundledRuntimeConfig(root=bundled_root()))
        )
        self._requester = requester or request_chat
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def close(self):
        self._closed.set()

    def answer(self, question: str) -> str:
        if self._closed.is_set():
            raise ChatError("Помощник выключается")
        question = (question or "").strip()
        if not question or len(question) > 700:
            raise ChatError("Вопрос должен содержать от 1 до 700 символов")
        # Other tasks must wait, rather than spawning multiple 2 GB Ollama processes.
        if not self._lock.acquire(blocking=False):
            raise ChatError("Я ещё отвечаю на предыдущий вопрос")
        runtime = None
        try:
            if self._closed.is_set():
                raise ChatError("Помощник выключается")
            runtime = self._runtime_factory()
            endpoint = runtime.start()
            if self._closed.is_set():
                raise ChatError("Помощник выключается")
            result = self._requester(endpoint, {
                "model": "qwen3-vl:2b-instruct",
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": question},
                ],
                "options": {"temperature": 0.5, "num_predict": 220},
            })
            text = result.get("message", {}).get("content", "")
            if not isinstance(text, str) or not text.strip():
                raise ChatError("Модель вернула пустой ответ")
            return text.strip()[:1600]
        except ChatError:
            raise
        except Exception as exc:
            raise ChatError(f"Не удалось получить локальный ответ: {str(exc)[:150]}") from exc
        finally:
            if runtime is not None:
                runtime.stop()
            self._lock.release()
