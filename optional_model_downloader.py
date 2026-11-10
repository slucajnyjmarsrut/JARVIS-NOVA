# -*- coding: utf-8 -*-
"""Consent-gated local Qwen model installation for Windows JARVIS Lite.

Downloads go ONLY through the official bundled Ollama CLI to the per-user
model store. No shell, pip, PowerShell, elevated rights or untrusted links.
Final blob contents are checked against the Ollama manifest SHA256 digests.
This is an optional network operation, never called during startup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from collections import deque

from bundled_vision_runtime import validate_offline_model_store
from model_storage import MODEL_NAME, user_model_store


class ModelDownloadError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ModelDownloadError("Недопустимая переадресация локальной Ollama.")


MIN_FREE_BYTES=3_000_000_000
# Slow internet can require several hours; a separate no-progress guard detects stalls.
MAX_WAIT_SECONDS=4*60*60
MAX_STALL_SECONDS=5*60
MAX_PULL_ATTEMPTS=3
MIN_REMAINING_BYTES=800_000_000
ERROR_TAIL_BYTES=8192


def required_free_bytes(downloaded: int) -> int:
    """A resumed download should not demand the ORIGINAL 3 GB again."""
    return max(MIN_REMAINING_BYTES, MIN_FREE_BYTES-max(0,int(downloaded)))


def _pull_error_hint(tail: bytes) -> str:
    """Translate Ollama's diagnostics into safe, bounded user-facing hints.

    Never print raw log lines: they can contain local paths or proxy credentials.
    """
    text=tail.decode("utf-8",errors="replace").casefold()
    if any(marker in text for marker in ("no space left", "disk full", "not enough space")):
        return "Недостаточно места на диске с моделью."
    if any(marker in text for marker in ("tls", "certificate", "x509")):
        return "Ошибка TLS/сертификата: проверь системную дату, VPN и антивирус."
    if any(marker in text for marker in ("401", "403", "unauthorized", "forbidden")):
        return "Реестр Ollama отклонил запрос: проверь доступ к registry.ollama.ai."
    if any(marker in text for marker in ("timeout", "connection", "proxy", "network",
                                           "no such host", "eof", "broken pipe")):
        return "Сбой сети или VPN: проверь подключение и настройки прокси."
    if any(marker in text for marker in ("404", "manifest unknown", "not found")):
        return "Модель не найдена в реестре Ollama или реестр недоступен."
    return "Ollama прервала загрузку. Проверь интернет, VPN и свободное место."


class _ErrorTail:
    """Drain a PIPE continuously to avoid a blocked CLI and bound RAM usage."""

    def __init__(self, stream):
        self.parts=deque()
        self.size=0
        self._thread=threading.Thread(
            target=self._read, args=(stream,), daemon=True,
            name="jarvis-ollama-error-drain")
        self._thread.start()

    def _read(self, stream):
        if stream is None:
            return
        try:
            while True:
                chunk=stream.read(4096)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    chunk=chunk.encode("utf-8",errors="replace")
                self.parts.append(chunk)
                self.size+=len(chunk)
                while self.size>ERROR_TAIL_BYTES and self.parts:
                    first=self.parts.popleft()
                    self.size-=len(first)
        except (OSError,ValueError):
            pass

    def finish(self):
        self._thread.join(timeout=2)
        return b"".join(self.parts)[-ERROR_TAIL_BYTES:]


def downloaded_blob_bytes(store: Path) -> int:
    """Count existing complete and partial Ollama blobs without deleting them."""
    total=0
    for file in (Path(store)/"blobs").glob("*"):
        try:
            if file.is_file() and not file.is_symlink():
                total+=file.stat().st_size
        except (FileNotFoundError, PermissionError):
            # Ollama may atomically rename a completed partial file.
            continue
    return total


def wait_for_pull(pull, store: Path, cancel: threading.Event, *,
                  progress=None, clock=None, sleep=None,
                  max_wait=MAX_WAIT_SECONDS, stall_wait=MAX_STALL_SECONDS) -> None:
    """Fail after sustained lack of downloaded bytes, without removing cache.

    A clean pull exit succeeds. The caller separately verifies all model
    digests; neither stalled nor cancelled downloads are treated as ready.
    """
    clock=clock or time.monotonic
    sleep=sleep or time.sleep
    started=clock()
    last_growth=started
    last_size=downloaded_blob_bytes(store)
    last_report=-1.0
    while True:
        if cancel.is_set():
            raise ModelDownloadError(
                "Загрузка отменена. Скачанные части сохранены для повторной попытки.")
        code=pull.poll()
        if code is not None:
            if code!=0:
                raise ModelDownloadError(
                    "Ollama не скачала модель. Проверь подключение к интернету "
                    "и свободное место. Уже скачанные части не удаляются.")
            return
        now=clock()
        if now-started>max_wait:
            raise ModelDownloadError(
                "Достигнут общий предел ожидания загрузки Qwen. "
                "Скачанные части сохранены.")
        size=downloaded_blob_bytes(store)
        if size!=last_size:
            last_growth=now
            last_size=size
        if progress is not None and now-last_report>=1:
            progress(size)
            last_report=now
        if now-last_growth>stall_wait:
            raise ModelDownloadError(
                "Загрузка Qwen остановилась: несколько минут нет новых данных. "
                "Проверь интернет, VPN и защиту Windows. "
                "Открой ⚙ → «Проверить локальную модель» для повтора: "
                "частично скачанные файлы сохранены.")
        sleep(.3)


def _loopback_tags(endpoint: str, timeout=2):
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(endpoint+"/api/tags",timeout=timeout) as response:
        raw=response.read(65536)
    if not isinstance(json.loads(raw),dict):
        raise ModelDownloadError("Ollama returned an invalid response")


def download_qwen(assets: Path, *, target: Path | None=None,
                  confirm: bool=False, cancel: threading.Event | None=None,
                  progress=None, popen=None, stage=None):
    """Explicitly approved local model install, with progress(bytes) callback.

    On success the per-user cache can be used by BundledVisionRuntime.
    """
    if confirm is not True:
        raise PermissionError("Подтверди загрузку локальной модели Qwen (~2 ГБ)")
    if os.name!="nt":
        raise ModelDownloadError("Автоматическая загрузка модели доступна на Windows")
    assets=Path(assets).resolve()
    exe=assets/"ollama"/"ollama.exe"
    if not exe.is_file():
        raise ModelDownloadError("Встроенный компонент Ollama отсутствует")
    store=Path(target) if target is not None else user_model_store()
    if store.is_symlink() or store.parent.is_symlink():
        raise ModelDownloadError("Недопустимая папка модели")
    store.mkdir(parents=True,exist_ok=True)
    existing=downloaded_blob_bytes(store)
    free=shutil.disk_usage(store).free
    needed=required_free_bytes(existing)
    if free<needed:
        raise ModelDownloadError(
            f"Недостаточно места для Qwen: свободно {free/1e9:.1f} ГБ, "
            f"нужно ещё примерно {needed/1e9:.1f} ГБ. "
            "Уже скачанные части сохранены.")
    cancel=cancel or threading.Event()
    if cancel.is_set():
        raise ModelDownloadError("Загрузка отменена. Частичные файлы сохранены.")
    from model_storage import local_model_available
    if local_model_available(assets,user_store=store):
        if progress:
            progress(downloaded_blob_bytes(store))
        return store
    # The Ollama server is exclusively owned by this operation on a random
    # 127.0.0.1 port. Never connect to a system-wide Ollama daemon.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    env=dict(os.environ)
    env.update({
        "OLLAMA_HOST":f"127.0.0.1:{port}",
        "OLLAMA_MODELS":str(store),
        "OLLAMA_NO_CLOUD":"1",
        "OLLAMA_MAX_LOADED_MODELS":"1",
        # Less concurrent range traffic is gentler on constrained VPN links.
        "OLLAMA_DOWNLOAD_PARTS":"4",
    })
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    runner=popen or subprocess.Popen
    server=None
    pull=None
    try:
        server=runner([str(exe),"serve"],cwd=str(exe.parent),env=env,
              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
              stdin=subprocess.DEVNULL,creationflags=flags)
        endpoint=f"http://127.0.0.1:{port}"
        deadline=time.monotonic()+65
        while time.monotonic()<deadline:
            if cancel.is_set():
                raise ModelDownloadError("Загрузка отменена")
            if server.poll() is not None:
                raise ModelDownloadError("Ollama не удалось запустить")
            try:
                _loopback_tags(endpoint)
                break
            except (OSError,TimeoutError,ValueError,ModelDownloadError):
                time.sleep(.3)
        else:
            raise ModelDownloadError("Ollama не ответила в течение 65 секунд")
        for attempt in range(1,MAX_PULL_ATTEMPTS+1):
            if cancel.is_set():
                raise ModelDownloadError("Загрузка отменена. Частичные файлы сохранены.")
            if server.poll() is not None:
                raise ModelDownloadError("Локальная Ollama неожиданно завершилась.")
            needed=required_free_bytes(downloaded_blob_bytes(store))
            if shutil.disk_usage(store).free<needed:
                raise ModelDownloadError(
                    "На диске закончилось место для Qwen. Частичные файлы сохранены.")
            if stage:
                stage(f"Qwen: попытка {attempt} из {MAX_PULL_ATTEMPTS}. "
                      "Продолжаю с уже скачанных частей.")
            pull=runner([str(exe),"pull",MODEL_NAME],
                  cwd=str(exe.parent),env=env,stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                  creationflags=flags)
            diagnostics=_ErrorTail(getattr(pull,"stderr",None))
            failure=None
            try:
                wait_for_pull(pull,store,cancel,progress=progress)
            except ModelDownloadError as exc:
                failure=exc
            finally:
                if pull.poll() is None:
                    try:
                        pull.terminate()
                        pull.wait(timeout=5)
                    except (OSError,subprocess.TimeoutExpired):
                        try:
                            pull.kill()
                            pull.wait(timeout=3)
                        except (OSError,subprocess.TimeoutExpired):
                            pass
                hint=_pull_error_hint(diagnostics.finish())
                pull=None
            if failure is None:
                break
            if cancel.is_set() or "отменена" in str(failure).casefold():
                raise failure
            if "общий предел" in str(failure):
                raise failure
            if attempt==MAX_PULL_ATTEMPTS:
                raise ModelDownloadError(
                    f"Qwen не удалось скачать после {MAX_PULL_ATTEMPTS} попыток. "
                    +hint+" Скачанные части сохранены.") from failure
            if stage:
                stage(f"Соединение прервалось ({hint}) "
                      f"Повторяю загрузку: {attempt+1}/{MAX_PULL_ATTEMPTS}.")
            if cancel.wait(3*attempt):
                raise ModelDownloadError("Загрузка отменена. Частичные файлы сохранены.")
        # The registry manifest specifies every blob SHA256. Do NOT accept
        # partially downloaded files or a model with mismatched checksums.
        validate_offline_model_store(assets,model_store=store,verify_hashes=True)
        if progress is not None:
            progress(downloaded_blob_bytes(store))
        return store
    finally:
        for proc in (pull,server):
            if proc is None:
                continue
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=3)
                except (OSError,subprocess.TimeoutExpired):
                    pass
