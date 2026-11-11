# -*- coding: utf-8 -*-
"""Separate the multi-GB Qwen weights from small JARVIS Lite installations.

The Lite app never downloads models silently. It asks for confirmation first.
Weights are shared between program upgrades in LocalAppData.
"""
from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path


MODEL_NAME="qwen3-vl:2b-instruct"


def model_store_in_assets(assets: Path) -> Path:
    return Path(assets)/"models"/"ollama"


def user_model_store(*, localappdata: str | None = None) -> Path:
    base=localappdata if localappdata is not None else os.environ.get("LOCALAPPDATA")
    if not base:
        # Developer/Linux tests need a stable, non-system app-data location.
        base=str(Path.home()/"AppData"/"Local")
    return Path(base)/"JarvisNova"/"Models"/"ollama"


def installed_edition(assets: Path) -> str:
    marker=Path(assets)/"EDITION.txt"
    try:
        value=marker.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "offline"
    return value if value in ("lite","offline") else "offline"


def active_model_store(assets: Path, *, user_store: Path | None=None) -> Path:
    assets=Path(assets)
    bundled=model_store_in_assets(assets)
    from bundled_vision_runtime import validate_offline_model_store, BundledRuntimeError
    # An incomplete bundled download must not mask a usable per-user cache.
    # Validation checks manifest structure and blob sizes, without hashing
    # multi-GB weights on every app launch.
    try:
        validate_offline_model_store(assets,model_store=bundled)
        return bundled
    except (BundledRuntimeError,OSError,ValueError):
        if user_store is not None:
            return Path(user_store)
        # A previously consented external Qwen store is reused in place;
        # no copied weights, no drive scan on startup, no auto-download.
        preferred=preferred_model_store()
        if preferred is not None:
            return preferred
        return user_model_store()


def local_model_available(assets: Path, *, user_store: Path | None=None) -> bool:
    from bundled_vision_runtime import validate_offline_model_store, BundledRuntimeError
    try:
        validate_offline_model_store(assets,
            model_store=active_model_store(assets,user_store=user_store))
        return True
    except (BundledRuntimeError,OSError,ValueError):
        return False



def _model_choice_file(*, localappdata: str | None = None) -> Path:
    return user_model_store(localappdata=localappdata).parent / "preferred-store.json"


def preferred_model_store(*, localappdata: str | None = None) -> Path | None:
    """Read only an explicitly saved model-store path, not drive inventory."""
    pref=_model_choice_file(localappdata=localappdata)
    try:
        if pref.is_symlink() or not pref.is_file() or pref.stat().st_size>2048:
            return None
        value=json.loads(pref.read_text(encoding="utf-8"))
        if (not isinstance(value,dict) or value.get("version")!=1
                or not isinstance(value.get("store"),str)):
            return None
        raw=value["store"]
        if not raw or raw.startswith("\\\\") or not Path(raw).is_absolute():
            return None
        store=Path(raw)
        if store.is_symlink():
            return None
        from bundled_vision_runtime import validate_offline_model_store
        validate_offline_model_store(Path("."),model_store=store)
        return store
    except (OSError,ValueError,RuntimeError,TypeError):
        return None


def remember_existing_model_store(store: Path, *, confirmed=False,
                                  localappdata: str | None = None,
                                  validate_hashes=True, cancel=None) -> Path:
    """Adopt an already-downloaded audited Qwen store after explicit consent.

    Hashing large blobs happens off the UI thread; no copying or executing.
    Saves ONLY a small preference file in JARVIS's own LocalAppData folder.
    """
    if confirmed is not True:
        raise PermissionError("Нужно разрешение на подключение найденной модели.")
    store=Path(store).expanduser()
    if (not store.is_absolute() or store.is_symlink() or not store.is_dir()
            or str(store).startswith("\\\\")):
        raise ValueError("Разрешена только существующая локальная папка модели.")
    from bundled_vision_runtime import validate_offline_model_store
    validate_offline_model_store(Path("."),model_store=store,
                                 verify_hashes=validate_hashes)
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Подключение модели отменено до сохранения настроек.")
    folder=_model_choice_file(localappdata=localappdata).parent
    if folder.is_symlink():
        raise ValueError("Папка настроек является ссылкой.")
    folder.mkdir(parents=True,exist_ok=True)
    pref=folder/"preferred-store.json"
    if pref.is_symlink():
        raise ValueError("Файл настроек является ссылкой.")
    target=store.resolve()
    # Atomic replace: cannot leave half-written path after interruption.
    staged=None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",encoding="utf-8",dir=folder,prefix=".nova-model-",
            suffix=".json",delete=False
        ) as stream:
            staged=Path(stream.name)
            json.dump({"version":1,"store":str(target)},stream,ensure_ascii=False)
        os.replace(staged,pref)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return target
