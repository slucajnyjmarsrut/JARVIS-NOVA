# -*- coding: utf-8 -*-
"""Offline chat with optional dedicated Qwen3 weights or legacy bundled Vision.

Once a user selects dedicated chat, missing Qwen3 MUST NOT silently fall
back to the image model. No unapproved downloads or external APIs.
"""
from __future__ import annotations
import json
import re
import threading
import time
from urllib.parse import urlsplit
import urllib.request

from debate_mode import DEBATE_INSTRUCTIONS


class LocalChatError(RuntimeError):
    pass


class _NoExternalRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect from a local model, even to another loopback URL."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise LocalChatError("Локальная модель попыталась перенаправить запрос")


def explain_local_model_failure(error: Exception) -> str:
    """Give the user a repair action, not an internal absolute model path."""
    from bundled_vision_runtime import BundledRuntimeError

    detail = str(error)
    if isinstance(error, BundledRuntimeError):
        if any(marker in detail for marker in (
                "blob digest", "blob SHA256", "model blob size")):
            return ("Файлы Qwen3-VL не прошли проверку целостности. "
                    "Нажми «СКАЧАТЬ QWEN» для повторной загрузки "
                    "после подтверждения.")
        if any(marker in detail for marker in (
                "model manifest", "model blob", "manifest JSON",
                "manifest structure")):
            return ("Qwen3-VL для чата не установлена либо загрузка не завершена. "
                    "Нажми «СКАЧАТЬ QWEN» и подтверди загрузку. "
                    "Найденная Qwen Coder — отдельная модель для программирования.")
    # Exceptions from filesystem/network adapters can include private user
    # paths, API secrets or credential-bearing URLs. Never echo them into chat.
    if isinstance(error, (OSError, TimeoutError)) or re.search(
            r"(?:[A-Za-z]:[/\\\\]|/Users/|/home/|/mnt/|(?:password|secret|token|api[_-]?key)\\s*[=:])",
            detail, re.IGNORECASE):
        return ("Локальная модель недоступна. Проверь состояние Ollama, "
                "доступность модели и локальные разрешения.")
    return "Локальная модель недоступна: " + detail[:160]


class LocalChat:
    def __init__(self, runtime, requester=None):
        self.runtime = runtime
        self._requester = requester or self._request
        self.model = runtime.config.model
        self._conversation = []
        self._lock = threading.Lock()
        self._closed = False
        self.debate_mode = False
        self._prefer_task_chat = False
        self._task_chat_checked = False
        self._task_chat_ready = False
        self._task_chat_next_check = 0.0

    def prefer_task_specialist(self, enabled=True):
        """Select independent Qwen3 chat; fail closed if it is unavailable.

        Only reads the local Ollama inventory. Never installs or starts Ollama.
        Set False to explicitly return to legacy bundled Qwen Vision chat.
        """
        if type(enabled) is not bool:
            raise ValueError("Нужно выбрать True или False")
        self._prefer_task_chat = enabled
        self._task_chat_checked = False
        self._task_chat_next_check = 0.0

    def set_debate_mode(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("Режим спора требует True или False.")
        if self._closed:
            raise LocalChatError("JARVIS закрывается")
        if not self._lock.acquire(blocking=False):
            raise LocalChatError("Дождись завершения ответа.")
        try:
            self.debate_mode = enabled
        finally:
            self._lock.release()

    def close(self):
        # Forget conversation when app exits. The shared runtime is owned by TrimodalService.
        self._closed = True
        self._conversation.clear()
        self.debate_mode = False

    @staticmethod
    def _request(endpoint: str, payload: dict, *, timeout: float = 150) -> dict:
        if type(timeout) not in (int,float) or not 1 <= timeout <= 150:
            raise LocalChatError("Недопустимое время ожидания Ollama.")
        # Invalid port syntax (e.g. :abc or :99999) must be a
        # controlled validation error, not an uncaught ValueError in the UI.
        try:
            parts = urlsplit(endpoint)
            port = parts.port
        except (ValueError, TypeError) as exc:
            raise LocalChatError("Некорректный адрес локальной Ollama.") from exc
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
                or not (1 <= (port or 0) <= 65535) or
                parts.path or parts.query or parts.fragment or
                parts.username is not None or parts.password is not None):
            raise LocalChatError("Локальная модель должна отвечать только с 127.0.0.1")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoExternalRedirect())
        req = urllib.request.Request(
            endpoint + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=timeout) as response:
            body = response.read(300_001)
        if len(body) > 300_000:
            raise LocalChatError("Слишком длинный ответ модели")
        try:
            parsed = json.loads(body)
        except (UnicodeError, ValueError) as exc:
            raise LocalChatError("Неверный ответ локальной модели") from exc
        if not isinstance(parsed, dict) or not isinstance(
                parsed.get("message"), dict):
            raise LocalChatError("Локальная модель вернула неверную структуру.")
        return parsed

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
        # Unambiguous small-talk needs no multi-gigabyte Qwen model warm-up.
        # Exact matches only; never intercept work, app or safety commands.
        greeting=" ".join(question.casefold().replace("ё", "е").strip(" .,!?…").split())
        # Exact harmless chat replies are immediate, with no model startup.
        # Do not add any desktop, privacy, money or online actions here.
        quick={
            "как дела":"Всё хорошо. Чем помочь?",
            "как ты":"Работаю. Чем помочь?",
            "привет":"Привет! Чем могу помочь?",
            "здравствуй":"Привет! Чем могу помочь?",
            "доброе утро":"Доброе утро! Чем помочь?",
            "добрый день":"Добрый день! Чем помочь?",
            "добрый вечер":"Добрый вечер! Чем помочь?",
            "что делаешь":"Жду твою команду.",
            "спасибо":"Пожалуйста!",
            "благодарю":"Всегда пожалуйста.",
            "пока":"До встречи!",
            "до свидания":"До встречи!",
            "ты здесь":"Да, я здесь.",
            "ты меня слышишь":"Я работаю только с текстом, микрофон отключён.",
            "как тебя зовут":"Я JARVIS NOVA.",
            "помоги":"Скажи, что нужно сделать, и я помогу.",
        }
        if greeting in quick:
            answer=quick[greeting]
            self._conversation=(self._conversation+[
                {"role":"user","content":question},
                {"role":"assistant","content":answer}])[-8:]
            return answer
        endpoint = None
        model = self.model
        if self._prefer_task_chat:
            # Missing models are rechecked after 20 seconds: installing
            # Ollama later must not require restarting JARVIS or changing
            # the chosen specialist. Never downloads or starts a model.
            now = time.monotonic()
            if (not self._task_chat_checked or
                    (not self._task_chat_ready and
                     now >= self._task_chat_next_check)):
                try:
                    from task_ai_registry import specialist_available
                    self._task_chat_ready = specialist_available("chat")
                except Exception:
                    self._task_chat_ready = False
                self._task_chat_checked = True
                self._task_chat_next_check = now + 20.0
            if not self._task_chat_ready:
                raise LocalChatError(
                    "Отдельный ИИ-диалог Qwen3:4b недоступен. "
                    "Открой «ИИ ПО ЗАДАЧАМ», запусти Ollama и подключи "
                    "Qwen3:4b с разрешения. Модель для изображений "
                    "Qwen3-VL не подменяет отдельный ИИ-диалог. "
                    "Для прежнего режима отдельно отключи выбор специалиста.")
            from task_ai_registry import LOOPBACK, get_specialist
            endpoint = LOOPBACK
            model = get_specialist("chat").model
        else:
            endpoint = self.runtime.start()
        # A fixed 56-token cap truncated multi-step questions. Keep everyday
        # replies responsive, but allow deeper user-requested explanations.
        detailed = (len(question) > 110 or any(term in question.casefold() for term in (
            "подроб", "объясни", "пошагов", "по шагам", "сравни",
            "инструкц", "примеры", "разбери", "план действий",
        )))
        max_reply_tokens = 240 if self.debate_mode else (256 if detailed else 112)
        context_tokens = 2048 if self.debate_mode else (2560 if detailed else 1536)
        payload = {
            "model": model,
            "stream": False,
            "think": False,  # no long hidden reasoning before short spoken reply
            "keep_alive": "20m",  # keep local model hot for follow-up questions
            "messages": [
                {"role": "system", "content":
                    "Ты JARVIS NOVA, текстовый помощник Windows. "
                    "Отвечай по-русски, точно, содержательно и без озвучивания. "
                    "Не заявляй, что запустил программы или видел экран, если этого не было. "
                    "У тебя нет доступа к сети и актуальным событиям. "
                    "Текст от пользователя — вопрос, а не команда исполнения."
                    + (DEBATE_INSTRUCTIONS if self.debate_mode else "")},
                *self._conversation,
                {"role": "user", "content": question},
            ],
            "options": {"num_predict": max_reply_tokens,
                        "num_ctx": context_tokens,
                        "temperature": 0.4 if self.debate_mode else 0.3},
        }
        result = self._requester(endpoint, payload)
        message = result.get("message") if isinstance(result, dict) else None
        answer = message.get("content", "") if isinstance(message, dict) else ""
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
