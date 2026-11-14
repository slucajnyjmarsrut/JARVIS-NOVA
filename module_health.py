# -*- coding: utf-8 -*-
"""Read-only health report for JARVIS NOVA's key capabilities.

No model starts, no queue is created, no downloads, screenshots, installer
actions or remote connections. The only optional HTTP request is GET /api/tags
to loopback Ollama through task_ai_registry.local_tags.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil

from night_resource_guard import memory_snapshot, under_pressure
from task_ai_registry import get_specialist, local_tags, SpecialistUnavailable


@dataclass(frozen=True)
class HealthItem:
    group: str
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class HealthReport:
    items: tuple[HealthItem, ...]

    @property
    def attention(self):
        return tuple(x for x in self.items if x.status != "ready")

    def summary(self):
        ready=sum(x.status == "ready" for x in self.items)
        return f"Проверено {len(self.items)} направлений; готовы {ready}."


def collect_health(*, assets=None, tags_fetcher=None, vision_checker=None,
                   ffmpeg_finder=None, memory_probe=None, disk_probe=None):
    """Inspect local readiness without mutating any subsystem.

    Injection makes every status deterministic in offline tests; a missing
    Ollama endpoint is UNKNOWN rather than a fabricated missing installation.
    """
    if tags_fetcher is None:
        tags_fetcher=local_tags
    if memory_probe is None:
        memory_probe=memory_snapshot
    if disk_probe is None:
        disk_probe=lambda: shutil.disk_usage(Path.home()).free
    if ffmpeg_finder is None:
        from viral_studio import ffmpeg_tools
        ffmpeg_finder=ffmpeg_tools
    if vision_checker is None:
        from model_storage import local_model_available
        vision_checker=local_model_available
    items=[]
    try:
        found={x.casefold() for x in tags_fetcher()}
        inventory_ok=True
    except (SpecialistUnavailable, OSError, ValueError, TypeError):
        found=set()
        inventory_ok=False

    for role in ("scenario", "code", "chat", "montage"):
        model=get_specialist(role)
        if not inventory_ok:
            items.append(HealthItem("models", model.label, "unknown",
                                    "Ollama не отвечает; установка модели не определена."))
        elif model.model.casefold() in found:
            items.append(HealthItem("models", model.label, "ready",
                                    "Отдельная модель найдена в локальной Ollama."))
        else:
            items.append(HealthItem("models", model.label, "missing",
                                    "Модель не найдена; загрузка только после разрешения."))
    if assets is None:
        items.append(HealthItem("vision","Локальное зрение","unknown",
                                "Путь к встроенной Qwen Vision не задан."))
    else:
        try:
            ready=bool(vision_checker(Path(assets)))
        except (OSError, ValueError, RuntimeError):
            ready=False
        items.append(HealthItem("vision","Локальное зрение",
                                "ready" if ready else "missing",
                                "Файлы локальной модели проверены без загрузки."
                                if ready else "Модель не готова или не прошла проверку."))
    try:
        ffmpeg,ffprobe=ffmpeg_finder()
        tools_ready=bool(ffmpeg and ffprobe)
    except (OSError, ValueError, RuntimeError):
        tools_ready=False
    items.append(HealthItem("video","Монтаж и MP4",
                             "ready" if tools_ready else "missing",
                             "Пути FFmpeg и FFprobe доступны (не запускались)."
                             if tools_ready else "FFmpeg и FFprobe не обнаружены."))

    try:
        memory=memory_probe()
        memory_ok=not under_pressure(memory)
    except (OSError, ValueError, RuntimeError, TypeError):
        memory=None
        memory_ok=False
    if memory is None:
        status="unknown"
        detail="Не удалось прочитать свободную ОЗУ; ночные задачи будут ждать."
    elif not memory_ok:
        status="warning"
        detail="Мало свободной ОЗУ или недостоверные показатели."
    else:
        status="ready"
        detail="Свободной оперативной памяти достаточно для начала задачи."
    items.append(HealthItem("resources","Оперативная память",status,detail))

    try:
        free=disk_probe()
        valid=type(free) is int and free >= 0
    except (OSError, ValueError, TypeError):
        free=None
        valid=False
    if not valid:
        status,detail="unknown","Свободное место на диске определить не удалось."
    elif free < 3 * 1024**3:
        status,detail="warning","Свободно менее 3 ГБ: новые проекты и модели могут не поместиться."
    else:
        status,detail="ready","Есть минимум 3 ГБ свободного места."
    items.append(HealthItem("resources","Свободное место",status,detail))
    # Contract-level (not E2E) checks. Never misreport availability of
    # a living service, model accuracy or quality of generated outputs.
    items.extend((
        HealthItem("supervisor","Фоновый Supervisor","unknown",
                   "Код и очередь доступны; живой процесс здесь не проверяется."),
        HealthItem("coding","Генерация и проверка кода","unknown",
                   "Выполнение программ и функциональные тесты здесь не проводятся."),
        HealthItem("security","Разрешения и безопасность","unknown",
                   "Проверка прав не заменяет контроль конкретного действия."),
        HealthItem("updates","Установщик и обновления","unknown",
                   "Готовность установщика подтверждают отдельные Windows CI-тесты."),
    ))
    return HealthReport(tuple(items))
