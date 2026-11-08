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

from bundled_vision_runtime import validate_offline_model_store
from model_storage import MODEL_NAME, user_model_store


class ModelDownloadError(RuntimeError):
    pass


MIN_FREE_BYTES=3_000_000_000
MAX_WAIT_SECONDS=2400


def _loopback_tags(endpoint: str, timeout=2):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint+"/api/tags",timeout=timeout) as response:
        raw=response.read(65536)
    if not isinstance(json.loads(raw),dict):
        raise ModelDownloadError("Ollama returned an invalid response")


def download_qwen(assets: Path, *, target: Path | None=None,
                  confirm: bool=False, cancel: threading.Event | None=None,
                  progress=None, popen=None):
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
    if shutil.disk_usage(store).free<MIN_FREE_BYTES:
        raise ModelDownloadError("Для установки Qwen нужно минимум 3 ГБ свободного места")
    cancel=cancel or threading.Event()
    from model_storage import local_model_available
    if local_model_available(assets,user_store=store):
        if progress:
            progress(sum(p.stat().st_size for p in (store/"blobs").glob("*") if p.is_file()))
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
        pull=runner([str(exe),"pull",MODEL_NAME],
              cwd=str(exe.parent),env=env,stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
              creationflags=flags)
        deadline=time.monotonic()+MAX_WAIT_SECONDS
        last_report=0
        while True:
            if cancel.is_set():
                raise ModelDownloadError("Загрузка отменена")
            if time.monotonic()>deadline:
                raise ModelDownloadError("Превышено время загрузки Qwen")
            code=pull.poll()
            now=time.monotonic()
            if progress is not None and now-last_report>=1:
                size=sum(p.stat().st_size for p in (store/"blobs").glob("*")
                         if p.is_file())
                progress(size)
                last_report=now
            if code is not None:
                if code!=0:
                    raise ModelDownloadError(
                        "Ollama не скачала модель. Проверь интернет и свободное место")
                break
            time.sleep(.3)
        # The registry manifest specifies every blob SHA256. Do NOT accept
        # partially downloaded files or a model with mismatched checksums.
        validate_offline_model_store(assets,model_store=store,verify_hashes=True)
        if progress is not None:
            progress(sum(p.stat().st_size for p in (store/"blobs").glob("*") if p.is_file()))
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
