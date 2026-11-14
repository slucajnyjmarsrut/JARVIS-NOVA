# -*- coding: utf-8 -*-
"""One explicit, isolated model identity per JARVIS task.

No invisible download; no uploaded chats/files; no arbitrary model or host
names from an LLM. All optional task models run through local Ollama only.
The existing bundled vision/chat model remains available for legacy chat.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import urllib.request
from urllib.parse import urlsplit

LOOPBACK = "http://127.0.0.1:11434"
MAX_TAG_BYTES = 200_000


class SpecialistUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskAI:
    kind: str
    label: str
    model: str
    backend: str
    description: str


# Distinct independent model weights for *optional* task specialists. The two
# existing bundled Qwen-VL pathways are retained for backward compatibility,
# and must not be misrepresented as two different sets of model weights.
SPECIALISTS = {
    "scenario": TaskAI(
        "scenario", "ИИ-сценарист", "gemma3:4b", "ollama",
        "Сюжеты, пять разных сцен, реплики и план съёмки"),
    "code": TaskAI(
        "code", "ИИ-программист", "qwen2.5-coder:7b", "ollama",
        "Архитектура, код, исправления и тесты"),
    "vision": TaskAI(
        "vision", "ИИ-зрение", "qwen3-vl:2b-instruct", "bundled",
        "Анализ выбранного изображения с отдельным разрешением"),
    "chat": TaskAI(
        "chat", "ИИ-диалог", "qwen3:4b", "ollama",
        "Самостоятельная локальная разговорная модель; "
        "без неё используется явно обозначенная встроенная Qwen Vision"),
    "montage": TaskAI(
        "montage", "ИИ-монтажный планировщик", "llama3.2:3b", "ollama",
        "Отдельные рекомендации для монтажа; MP4 собирает FFmpeg"),
}
ROLE_ORDER = ("scenario", "code", "vision", "chat", "montage")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpecialistUnavailable("Перенаправление локальной Ollama запрещено.")


def _local_endpoint(endpoint: str) -> str:
    # Invalid port syntax should never crash the model manager or UI.
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except (ValueError, TypeError) as exc:
        raise SpecialistUnavailable("Некорректный адрес локального ИИ.") from exc
    if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or
            not 1 <= (port or 0) <= 65535 or
            parts.path or parts.query or parts.fragment or
            parts.username is not None or parts.password is not None):
        raise SpecialistUnavailable("Для ИИ разрешена только 127.0.0.1.")
    return endpoint


def get_specialist(kind: str) -> TaskAI:
    if kind not in SPECIALISTS:
        raise ValueError("Неизвестная задача JARVIS.")
    return SPECIALISTS[kind]


def local_tags(*, transport=None) -> tuple[str, ...]:
    """Read-only inventory of a RUNNING loopback Ollama; no download/start."""
    if transport is None:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        req = urllib.request.Request(
            _local_endpoint(LOOPBACK)+"/api/tags",method="GET",
            headers={"Accept":"application/json"})
        try:
            with opener.open(req,timeout=4) as response:
                raw=response.read(MAX_TAG_BYTES+1)
        except (OSError,ValueError) as exc:
            raise SpecialistUnavailable(
                "Локальная Ollama не отвечает. Запусти Ollama на компьютере.") from exc
        if len(raw)>MAX_TAG_BYTES:
            raise SpecialistUnavailable("Слишком длинный ответ Ollama.")
        try:
            data=json.loads(raw)
        except (ValueError,UnicodeError) as exc:
            raise SpecialistUnavailable("Некорректный список моделей.") from exc
    else:
        data=transport()
    if not isinstance(data,dict) or not isinstance(data.get("models"),list):
        raise SpecialistUnavailable("Локальная Ollama вернула неверный список.")
    return tuple(
        item["name"].casefold()
        for item in data["models"][:150]
        if isinstance(item,dict) and isinstance(item.get("name"),str)
        and 0<len(item["name"])<130
    )


def specialist_available(kind: str, *, transport=None) -> bool:
    specialist=get_specialist(kind)
    if specialist.backend=="bundled":
        # The bundled model is checked by the existing vision runtime.
        return False
    return specialist.model.casefold() in local_tags(transport=transport)


def specialist_help(kind: str) -> str:
    task=get_specialist(kind)
    if task.backend=="bundled":
        return "Эта задача использует встроенную Qwen3-VL."
    return (f"{task.label} работает отдельно: {task.model}. "
            "Модель не входит в Lite и скачивается только с разрешения. "
            "Для ручной установки при запущенной Ollama: "
            f"ollama pull {task.model}.")


def pull_specialist(kind: str, *, confirmed=False, cancel=None,
                    launcher=None, executable=None, transport=None,
                    progress=None) -> str:
    """Explicit install into user's local Ollama. Never delete weights.

    The CLI contacts the normal Ollama registry as requested by the user.
    The launch uses a fixed model name and a fixed loopback Ollama address.
    """
    if confirmed is not True:
        raise PermissionError("Скачивание модели требует подтверждения.")
    task=get_specialist(kind)
    if task.backend!="ollama":
        raise SpecialistUnavailable("Встроенную Qwen подключают отдельно.")
    if specialist_available(kind,transport=transport):
        if progress:
            progress("Модель уже найдена в локальной Ollama.")
        return task.model
    exe=executable or shutil.which("ollama")
    if not exe or not Path(exe).is_file():
        raise SpecialistUnavailable(
            "Сначала установи и запусти Ollama. Затем повтори скачивание.")
    if cancel is not None and cancel.is_set():
        raise SpecialistUnavailable("Скачивание отменено до начала.")
    env=os.environ.copy()
    env["OLLAMA_HOST"]="127.0.0.1:11434"
    for key in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY",
                "http_proxy","https_proxy","all_proxy"):
        env.pop(key,None)
    env["NO_PROXY"]="127.0.0.1,localhost"
    if progress:
        progress("Скачиваю отдельную модель "+task.model+
                 ". Частично скачанные файлы не удаляются.")
    cmd=[str(Path(exe).absolute()),"pull",task.model]
    proc=(launcher or subprocess.Popen)(
        cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,shell=False,env=env)
    # The caller runs this in a background worker, never on the Tk thread.
    # Do not run or terminate models not started by this exact operation.
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.wait(0.2):
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                raise SpecialistUnavailable(
                    "Загрузка отменена. Уже скачанные файлы сохранены.")
            if cancel is None:
                threading.Event().wait(0.2)
        if proc.returncode:
            raise SpecialistUnavailable(
                "Не удалось скачать отдельную модель. Проверь Ollama и "
                "подключение к интернету; частичные файлы сохранены.")
    finally:
        # There is deliberately no cleanup of model files.
        pass
    if not specialist_available(kind,transport=transport):
        raise SpecialistUnavailable(
            "Ollama завершила установку, но модель не появилась в /api/tags.")
    if progress:
        progress("Отдельный "+task.label+" подключён: "+task.model)
    return task.model
