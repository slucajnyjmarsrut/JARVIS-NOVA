# -*- coding: utf-8 -*-
"""Accurate, cancellable Qwen download progress from Ollama's loopback API.

Never estimate downloaded bytes from blob file sizes: Ollama may reserve disk
space for partially downloaded blobs. Only Ollama's streamed completed bytes
are reported. The official Ollama server handles TLS, registry authentication
and resumable layers; this client does not download arbitrary URLs.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODEL = "qwen3-vl:2b-instruct"
MAX_PULL_ATTEMPTS = 3
MAX_LINE = 16384
MAX_MODEL_BYTES = 12_000_000_000
MAX_BLOBS = 128
MAX_IDLE_SECONDS = 300
MAX_TOTAL_SECONDS = 14400
READ_TIMEOUT = 55


class PullAPIError(RuntimeError):
    def __init__(self, message, *, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PullAPIError(
            "Локальная Ollama попыталась перенаправить запрос.", retryable=False)


def _safe_hint(value):
    """No raw HTTP, filesystem, proxy or model-server error text in UI."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").casefold()
    else:
        text = str(value).casefold()
    if any(p in text for p in ("no space left", "disk full", "not enough space")):
        return "Недостаточно места на диске."
    if any(p in text for p in ("x509", "certificate", "tls", "ssl")):
        return "Проблема с сертификатом TLS: проверь системную дату, VPN и защиту Windows."
    if any(p in text for p in ("401", "403", "unauthorized", "forbidden")):
        return "Доступ к официальному реестру моделей отклонён."
    if any(p in text for p in ("404", "manifest unknown", "not found")):
        return "Модель не найдена в реестре Ollama."
    if any(p in text for p in ("timeout", "connection", "proxy", "network",
                               "no such host", "eof", "broken pipe", "reset")):
        return "Ошибка сети или VPN при скачивании Qwen."
    return "Ollama прервала получение модели."


def _local_endpoint(endpoint):
    parsed = urllib.parse.urlsplit(str(endpoint))
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.path or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None):
        raise PullAPIError("Для загрузки разрешён только локальный сервер Ollama.",
                           retryable=False)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None or not 1 <= port <= 65535:
        raise PullAPIError("Недопустимый порт Ollama.", retryable=False)
    return f"http://127.0.0.1:{port}"


def _request(endpoint):
    return urllib.request.Request(
        endpoint + "/api/pull",
        data=json.dumps(
            {"model": MODEL, "stream": True, "insecure": False},
            separators=(",", ":")).encode("ascii"),
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST")


class ProgressLedger:
    """Aggregate bytes actually completed per digest (not allocated disk)."""
    def __init__(self):
        self.completed = {}
        self.last_status = ""
        self.last_bytes = 0

    def update(self, event, *, progress=None, stage=None):
        if not isinstance(event, dict):
            raise PullAPIError("Некорректный ответ Ollama.", retryable=False)
        error = event.get("error")
        if error:
            hint = _safe_hint(error)
            fatal = any(s in str(error).casefold() for s in (
                "401", "403", "404", "unauthorized", "manifest unknown"))
            raise PullAPIError(hint, retryable=not fatal)
        status = event.get("status", "")
        if not isinstance(status, str) or len(status) > 200:
            raise PullAPIError("Некорректный статус Ollama.", retryable=False)
        normalized = status.casefold().strip()
        digest = event.get("digest")
        current = event.get("completed")
        total = event.get("total")
        if current is not None:
            if (isinstance(current, bool) or not isinstance(current, int)
                    or current < 0 or current > MAX_MODEL_BYTES):
                raise PullAPIError("Недостоверный счётчик Qwen.", retryable=False)
            if (not isinstance(digest, str) or
                    not re.fullmatch(r"[a-zA-Z0-9:._-]{1,128}", digest)):
                raise PullAPIError("Недостоверный идентификатор части модели.",
                                   retryable=False)
            if total is not None and (
                    isinstance(total, bool) or not isinstance(total, int)
                    or total < 0 or total > MAX_MODEL_BYTES or current > total):
                raise PullAPIError("Недостоверный объём части Qwen.",
                                   retryable=False)
            if digest not in self.completed and len(self.completed) >= MAX_BLOBS:
                raise PullAPIError("Слишком много частей в ответе Ollama.",
                                   retryable=False)
            self.completed[digest] = max(self.completed.get(digest, 0), current)
            size = sum(self.completed.values())
            if size > MAX_MODEL_BYTES:
                raise PullAPIError("Неожиданный объём Qwen.", retryable=False)
            if size > self.last_bytes:
                self.last_bytes = size
                if progress is not None:
                    progress(size)
        if normalized != self.last_status:
            self.last_status = normalized
            if stage is not None:
                if normalized == "success":
                    stage("Ollama подтвердила завершение загрузки Qwen.")
                elif "verif" in normalized or "sha256" in normalized:
                    stage("Проверяю контрольные суммы скачанных частей Qwen.")
                elif "writ" in normalized or "manifest" in normalized and "pull" not in normalized:
                    stage("Сохраняю манифест локальной Qwen.")
                elif "pulling manifest" in normalized:
                    stage("Запрашиваю официальный манифест Qwen.")
                elif "pull" in normalized or "download" in normalized:
                    stage("Получаю Qwen: учитываются фактически загруженные байты.")
        return normalized == "success"


def _read_frames(response, events, closing):
    """Read network stream on daemon thread; main downloader stays cancellable."""
    try:
        while not closing.is_set():
            raw = response.readline(MAX_LINE + 1)
            if not raw:
                events.put(("end", None))
                return
            if len(raw) > MAX_LINE:
                events.put(("bad", None))
                return
            events.put(("line", raw))
    except (OSError, ValueError, TimeoutError) as exc:
        events.put(("error", _safe_hint(exc)))


def _one_pull(endpoint, opener, cancel, ledger, *, progress=None, stage=None,
              clock=None, max_idle=MAX_IDLE_SECONDS,
              max_total=MAX_TOTAL_SECONDS):
    clock = clock or time.monotonic
    start = clock()
    last_activity = start
    last_progress = ledger.last_bytes
    closing = threading.Event()
    try:
        with opener.open(_request(endpoint), timeout=READ_TIMEOUT) as response:
            if getattr(response, "status", 200) != 200:
                raise PullAPIError("Локальная Ollama вернула ошибку HTTP.")
            events = queue.Queue()
            worker = threading.Thread(
                target=_read_frames, args=(response, events, closing),
                daemon=True, name="jarvis-ollama-pull-stream")
            worker.start()
            while True:
                if cancel.is_set():
                    raise PullAPIError("Загрузка отменена. Части Qwen сохранены.",
                                       retryable=False)
                now = clock()
                if now - start > max_total:
                    raise PullAPIError("Превышено время скачивания Qwen.")
                if now - last_activity > max_idle:
                    raise PullAPIError("Ollama не передаёт новых данных Qwen.")
                try:
                    kind, value = events.get(timeout=0.3)
                except queue.Empty:
                    continue
                if kind == "end":
                    raise PullAPIError("Ollama закрыла соединение без подтверждения готовности.")
                if kind == "bad":
                    raise PullAPIError("Слишком длинный ответ Ollama.", retryable=False)
                if kind == "error":
                    raise PullAPIError(value)
                try:
                    item = json.loads(value)
                except (UnicodeError, ValueError) as exc:
                    raise PullAPIError("Некорректный поток Ollama.", retryable=False) from exc
                last_activity = clock()
                previous = ledger.last_bytes
                if ledger.update(item, progress=progress, stage=stage):
                    return
                if ledger.last_bytes > previous:
                    last_progress = ledger.last_bytes
                # Status frames are valid liveness (checksum verification
                # can take time); no-activity timeout covers silent hangs.
    except urllib.error.HTTPError as exc:
        raise PullAPIError(
            _safe_hint(f"HTTP {exc.code}"), retryable=exc.code in
            (408, 429, 500, 502, 503, 504)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PullAPIError(_safe_hint(exc)) from exc
    finally:
        closing.set()


def pull_via_api(endpoint, cancel, *, progress=None, stage=None, opener=None,
                 attempts=MAX_PULL_ATTEMPTS, pause=None, clock=None,
                 max_idle=MAX_IDLE_SECONDS):
    """Pull fixed official Qwen model, retry only while explicitly consented.

    A streamed success frame is REQUIRED; a disconnected socket never means
    a complete model. The caller still verifies manifest and all SHA256 blobs.
    """
    endpoint = _local_endpoint(endpoint)
    if not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ValueError("Недопустимое число повторов.")
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    pause = pause or cancel.wait
    ledger = ProgressLedger()
    for attempt in range(1, attempts + 1):
        if cancel.is_set():
            raise PullAPIError("Загрузка отменена. Части Qwen сохранены.",
                               retryable=False)
        if stage:
            stage(f"Qwen: подключение {attempt}/{attempts} (продолжение скачивания).")
        try:
            _one_pull(endpoint, opener, cancel, ledger, progress=progress,
                      stage=stage, clock=clock, max_idle=max_idle)
            return ledger.last_bytes
        except PullAPIError as exc:
            if cancel.is_set() or not exc.retryable or attempt == attempts:
                raise
            if stage:
                stage("Связь с Ollama прервана. Повторяю скачивание без удаления данных.")
            if pause(3 * attempt):
                raise PullAPIError("Загрузка отменена. Части Qwen сохранены.",
                                   retryable=False)
    raise PullAPIError("Ollama не завершила скачивание Qwen.")
