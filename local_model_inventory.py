# -*- coding: utf-8 -*-
"""Consent-gated, bounded, read-only inventory of local AI model files.

The full-PC option enumerates *fixed local volumes*, not network shares.
The scan reads directory metadata, never private documents, model weights,
or arbitrary JSON. Only the specific audited Qwen Ollama manifest is parsed
to determine runtime compatibility. No executable is launched, no files
are modified, and discovered unknown models are NEVER treated as usable.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import re
import stat
import threading
import time

MAX_DIRS = 180_000
MAX_FILES = 1_500_000
MAX_RESULTS = 120
MAX_SECONDS = 100
MIN_WEIGHTS = 8 * 1024 * 1024
SKIP_DIRS = frozenset({
    "$recycle.bin", "system volume information", "windows", "winsxs",
    "$windows.~bt", "$windows.~ws", ".git", ".svn", "node_modules",
    "__pycache__", ".venv", "venv", "tmp", "temp",
})
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
SHA_BLOB = re.compile(r"^sha256-[0-9a-f]{64}$", re.I)


@dataclass(frozen=True)
class LocalModel:
    name: str
    location: Path
    kind: str
    size_bytes: int
    jarvis_compatible: bool = False
    coding_candidate: bool = False  # Name-only hint, never a readiness claim.


@dataclass(frozen=True)
class ModelInventory:
    models: tuple[LocalModel, ...]
    drives: tuple[Path, ...]
    checked_dirs: int
    checked_files: int
    incomplete: bool
    cancelled: bool
    permission_errors: int


def fixed_local_drives():
    """Return available Windows local fixed disks, never mapped/network disks."""
    if os.name != "nt":
        return ()
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetLogicalDrives.restype = wintypes.DWORD
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    mask = int(api.GetLogicalDrives())
    roots = []
    for index in range(26):
        if mask & (1 << index):
            root = chr(65 + index) + ":\\"
            if api.GetDriveTypeW(root) == 3:  # DRIVE_FIXED, never remote 4
                roots.append(Path(root))
    return tuple(roots)


def _reparse(entry):
    try:
        return entry.is_symlink() or bool(
            entry.stat(follow_symlinks=False).st_file_attributes & REPARSE
        ) if os.name == "nt" else entry.is_symlink()
    except OSError:
        return True


def _ollama_name(path: Path):
    parts = tuple(part.casefold() for part in path.parts)
    # .../models/manifests/registry.ollama.ai/library/<name>/<tag>
    if (len(parts) >= 6 and parts[-5] == "manifests"
            and parts[-4] == "registry.ollama.ai" and parts[-3] == "library"):
        return path.parent.parent.parent.parent.parent, path.parent.name, path.name
    return None


def _describe(path: Path, size: int):
    name = path.name
    ext = path.suffix.casefold()
    if ext in (".gguf", ".safetensors", ".onnx") and size >= MIN_WEIGHTS:
        return LocalModel(name, path, ext.lstrip("."), size)
    if (ext in (".pt", ".pth") and size >= MIN_WEIGHTS
            and any(w in name.casefold() for w in
                    ("model", "checkpoint", "weights", "diffusion"))):
        return LocalModel(name, path, "pytorch-weights", size)
    if ext == ".bin" and size >= MIN_WEIGHTS and (
            name.casefold().startswith(("pytorch_model", "model-", "diffusion_pytorch"))):
        return LocalModel(name, path, "model-weights", size)
    return None


def scan_local_models(*, confirmed=False, roots=None, cancel=None,
                      progress=None, max_seconds=MAX_SECONDS,
                      max_dirs=MAX_DIRS, max_files=MAX_FILES,
                      max_results=MAX_RESULTS, clock=time.monotonic):
    """Inventory metadata across ALL fixed volumes only after explicit consent.

    Injected roots are for test/integration and selected folders. Real whole-PC
    discovery always uses fixed_local_drives(). All traversals are bounded and
    use lstat-style checks: no symlinks, Windows junctions, or network shares.
    """
    if confirmed is not True:
        raise PermissionError("Поиск моделей на всём ПК требует отдельного согласия.")
    if (type(max_seconds) not in (int,float) or
            not 1 <= max_seconds <= MAX_SECONDS or
            type(max_dirs) is not int or not 1 <= max_dirs <= MAX_DIRS or
            type(max_files) is not int or not 1 <= max_files <= MAX_FILES or
            type(max_results) is not int or not 1 <= max_results <= MAX_RESULTS):
        raise ValueError("Недопустимые пределы поиска.")
    chosen = tuple(Path(p) for p in
                   (fixed_local_drives() if roots is None else roots))
    start = clock()
    seen=set()
    found=[]
    files=dirs=errors=0
    incomplete=cancelled=False
    pending=list(reversed(chosen))
    while pending:
        if cancel is not None and cancel.is_set():
            incomplete=cancelled=True
            break
        if (clock()-start >= max_seconds or dirs>=max_dirs
                or files>=max_files or len(found)>=max_results):
            incomplete=True
            break
        directory=pending.pop()
        try:
            if directory.is_symlink() or directory.resolve() in seen:
                continue
            # This is only a de-duplication key, NOT an instruction to open content.
            seen.add(directory.resolve())
            if not directory.is_dir():
                continue
            dirs+=1
            with os.scandir(directory) as entries:
                for item in entries:
                    if (cancel is not None and cancel.is_set()):
                        cancelled=incomplete=True
                        break
                    if (clock()-start>=max_seconds or files>=max_files
                            or len(found)>=max_results):
                        incomplete=True
                        break
                    if _reparse(item):
                        continue
                    try:
                        if item.is_dir(follow_symlinks=False):
                            if item.name.casefold() not in SKIP_DIRS:
                                pending.append(Path(item.path))
                            continue
                        if not item.is_file(follow_symlinks=False):
                            continue
                        files+=1
                        name=item.name
                        low=name.casefold()
                        maybe=(low.endswith((".gguf",".safetensors",".onnx",
                                             ".pt",".pth",".bin"))
                               or low=="2b-instruct" or
                               ("manifests" in directory.parts and
                                "library" in directory.parts))
                        if not maybe:
                            continue
                        size=item.stat(follow_symlinks=False).st_size
                        path=Path(item.path)
                        manifest=_ollama_name(path)
                        if manifest:
                            store, model, tag=manifest
                            compatible=False
                            if model.casefold()=="qwen3-vl" and tag=="2b-instruct":
                                try:
                                    from bundled_vision_runtime import validate_offline_model_store
                                    validate_offline_model_store(Path("."),model_store=store)
                                    compatible=True
                                except (OSError,ValueError,RuntimeError):
                                    pass
                            # The name on disk is not proof that a coder can
                            # be loaded; that requires the separately consented
                            # loopback Ollama /api/tags check in CodeWindow.
                            from local_coder_models import CODE_NAME
                            candidate=bool(CODE_NAME.fullmatch(f"{model}:{tag}"))
                            found.append(LocalModel(
                                f"{model}:{tag}",store,"ollama-store",size,
                                jarvis_compatible=compatible,
                                coding_candidate=candidate))
                        else:
                            candidate=_describe(path,size)
                            if candidate:
                                found.append(candidate)
                    except (PermissionError,OSError):
                        errors+=1
                if cancelled or incomplete:
                    break
        except (PermissionError,OSError):
            errors+=1
        if progress is not None and dirs%500==0:
            progress(dirs,files,len(found))
    return ModelInventory(tuple(found),chosen,dirs,files,
                          incomplete,cancelled,errors)


def summarize_inventory(result: ModelInventory, *, max_visible=18):
    if not isinstance(result,ModelInventory):
        raise TypeError("Нужен результат поиска моделей.")
    lines=[f"Поиск моделей: локальных дисков {len(result.drives)}, "
           f"папок {result.checked_dirs}, файлов {result.checked_files}, "
           f"кандидатов {len(result.models)}."]
    if not result.drives:
        lines.append("Нет доступных локальных дисков; поиск не выполнялся.")
    if result.models:
        for item in result.models[:max_visible]:
            status=("совместимая Qwen3-VL для чата" if item.jarvis_compatible
                    else "кандидат для кода; запуск через Ollama не проверен"
                    if item.coding_candidate
                    else "найдена, совместимость не проверена")
            lines.append(f"• {item.name} ({item.kind}, {status}) — {item.location}")
        if len(result.models)>max_visible:
            lines.append(f"Показано {max_visible} из {len(result.models)}.")
    else:
        lines.append("Подходящие файлы моделей не обнаружены в обследованных папках.")
    if result.incomplete:
        lines.append("Поиск неполный: отменён или достигнут предел времени/файлов.")
    if result.permission_errors:
        lines.append(f"Недоступных папок/файлов: {result.permission_errors}.")
    if any(m.coding_candidate for m in result.models):
        lines.append(
            "Для Qwen Coder открой «Программирование» и разреши проверить "
            "запущенную локальную Ollama (127.0.0.1:11434). "
            "Для чата и картинок отдельно требуется Qwen3-VL.")
    lines.append("Неизвестные модели не подключаются и не запускаются автоматически.")
    return "\n".join(lines)
