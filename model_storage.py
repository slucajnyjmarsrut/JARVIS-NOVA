# -*- coding: utf-8 -*-
"""Separate the multi-GB Qwen weights from small JARVIS Lite installations.

The Lite app never downloads models silently. It asks for confirmation first.
Weights are shared between program upgrades in LocalAppData.
"""
from __future__ import annotations

import os
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
        return Path(user_store) if user_store is not None else user_model_store()


def local_model_available(assets: Path, *, user_store: Path | None=None) -> bool:
    from bundled_vision_runtime import validate_offline_model_store, BundledRuntimeError
    try:
        validate_offline_model_store(assets,
            model_store=active_model_store(assets,user_store=user_store))
        return True
    except (BundledRuntimeError,OSError,ValueError):
        return False
