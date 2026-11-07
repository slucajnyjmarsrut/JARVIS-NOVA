# -*- coding: utf-8 -*-
"""FreeLLM (freelm / FreeLLMAPI) loopback gateway client for text-only NOVA.

The service, not JARVIS, holds third-party provider keys. GitHub is ONLY a code
host; never fetch provider secrets from repository files, GitHub APIs or Actions.
All network requests are opt-in and restricted to a loopback OpenAI-compatible
gateway. This uses Python's standard library, so the Windows bundle needs no
download of untrusted code or an additional Python package.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:4000/v1"
SYSTEM_CHAT = (
    "Ты JARVIS NOVA — текстовый помощник. Отвечай по-русски, точно, "
    "понятно и содержательно. Уточняй неопределённость. "
    "Не утверждай, что выполнил действие, открыл приложение, "
    "проверил файл или увидел экран, если этого не произошло. "
    "Предложения кода можно обсуждать, но нельзя выполнять автоматически. "
    "Не проси передавать секретные ключи в чат."
)


class FreeLLMError(RuntimeError):
    """Safe, non-secret error that may be displayed to the user."""


def validated_base_url(value: str) -> str:
    """Allow only explicit local API endpoints; no remote key exfiltration."""
    if not isinstance(value, str) or len(value) > 180:
        raise FreeLLMError("Неверный адрес FreeLLM")
    try:
        parsed = urllib.parse.urlsplit(value.strip().rstrip("/"))
        port = parsed.port
    except ValueError as exc:
        raise FreeLLMError("Неверный порт FreeLLM") from exc
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1"} or
            not port or not 1 <= port <= 65535 or
            parsed.path != "/v1" or parsed.query or parsed.fragment or
            parsed.username is not None or parsed.password is not None):
        raise FreeLLMError(
            "FreeLLM должен работать локально: http://127.0.0.1:4000/v1")
    return value.strip().rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FreeLLMError("FreeLLM перенаправил запрос — это запрещено")


class FreeLLMChat:
    """A text and coding client; secret values are never logged or persisted."""

    def __init__(self, *, base_url: str | None = None,
                 model: str | None = None, transport=None):
        raw_url = base_url if base_url is not None else os.environ.get(
            "FREELLM_BASE_URL", DEFAULT_BASE_URL)
        self.base_url = validated_base_url(raw_url)
        self.model = model or os.environ.get("FREELLM_MODEL", "auto")
        if not isinstance(self.model, str) or not 1 <= len(self.model) <= 128:
            raise FreeLLMError("Неверное имя модели FreeLLM")
        self._transport = transport or self._request
        self._lock = threading.Lock()
        self._history = []
        self._closed = False

    @staticmethod
    def _request(url, payload, headers, timeout=90):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with opener.open(req, timeout=timeout) as response:
                body = response.read(500_001)
        except urllib.error.HTTPError as exc:
            # Do NOT show the server's response body. It may contain secrets.
            raise FreeLLMError("FreeLLM вернул HTTP " + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise FreeLLMError(
                "Шлюз FreeLLM не отвечает. Запусти 'freelm serve' и проверь адрес.") from None
        if len(body) > 500_000:
            raise FreeLLMError("Слишком большой ответ FreeLLM")
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise FreeLLMError("FreeLLM вернул не JSON") from None
        return result

    def _complete(self, messages, *, model, max_tokens=1600) -> str:
        if self._closed:
            raise FreeLLMError("JARVIS закрывается")
        if not isinstance(model, str) or not 1 <= len(model) <= 128:
            raise FreeLLMError("Неверная модель FreeLLM")
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json",
                   "User-Agent": "JARVIS-NOVA-FreeLLM"}
        # A gateway may have its own unified key; upstream provider keys are
        # managed by FreeLLM, not obtained via GitHub or embedded in the EXE.
        key = os.environ.get("FREELLM_API_KEY", "")
        if key:
            if "\n" in key or "\r" in key or len(key) > 1024:
                raise FreeLLMError("Неверный локальный FREELLM_API_KEY")
            headers["Authorization"] = "Bearer " + key
        result = self._transport(
            self.base_url + "/chat/completions", payload, headers, 90)
        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise FreeLLMError("FreeLLM не вернул текст ответа") from None
        if isinstance(answer, list):
            answer = "".join(p.get("text", "") for p in answer
                             if isinstance(p, dict) and p.get("type") == "text")
        if not isinstance(answer, str) or not answer.strip():
            raise FreeLLMError("FreeLLM вернул пустой ответ — проверь модели")
        return answer.strip()[:35000]

    def ask(self, question: str) -> str:
        question = str(question or "").strip()
        if not 1 <= len(question) <= 12000:
            raise FreeLLMError("Длина сообщения: 1–12000 символов")
        if not self._lock.acquire(blocking=False):
            raise FreeLLMError("Предыдущий ответ FreeLLM ещё обрабатывается")
        try:
            messages = [{"role": "system", "content": SYSTEM_CHAT},
                        *self._history, {"role": "user", "content": question}]
            answer = self._complete(messages, model=self.model)
            if self._closed:
                raise FreeLLMError("JARVIS закрывается")
            self._history = (
                self._history +
                [{"role": "user", "content": question},
                 {"role": "assistant", "content": answer[:5000]}])[-8:]
            return answer[:12000]
        finally:
            self._lock.release()

    def generate_code(self, task: str, language: str) -> str:
        """Isolated code request; never leaks previous chat turns to the model."""
        from code_agent import SYSTEM
        if language not in ("java", "luau") or not isinstance(task, str) or not 1 <= len(task.strip()) <= 20000:
            raise FreeLLMError("Недопустимый запрос к генератору кода")
        code_model = os.environ.get("FREELLM_CODE_MODEL", self.model)
        if not self._lock.acquire(blocking=False):
            raise FreeLLMError("Подожди завершения предыдущего запроса FreeLLM")
        try:
            return self._complete([
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Language: " + language +
                 "\nTask: " + task}
            ], model=code_model, max_tokens=4096)
        finally:
            self._lock.release()

    def close(self):
        self._closed = True
        self._history.clear()
