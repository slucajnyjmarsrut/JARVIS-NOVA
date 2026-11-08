# -*- coding: utf-8 -*-
"""Persistent user control for stable, automatic JARVIS NOVA updates.

Settings are written atomically to LocalAppData, never the installation dir.
Malformed or link-swapped files are ignored/fail closed. Network checks are
disabled for source/dev runs by auto_update.installed_application().
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

MAX_SETTINGS_BYTES = 2048


@dataclass(frozen=True)
class UpdatePreferences:
    automatic_checks: bool = True
    automatic_restart: bool = True


def default_preferences_path() -> Path | None:
    root=os.environ.get("LOCALAPPDATA")
    if not root:
        return None
    return Path(root)/"JarvisNova"/"update_preferences.json"


def load_preferences(path: Path | None = None) -> UpdatePreferences:
    path=Path(path) if path is not None else default_preferences_path()
    if path is None:
        return UpdatePreferences()
    try:
        if path.is_symlink() or path.stat().st_size>MAX_SETTINGS_BYTES:
            return UpdatePreferences(False,False)
        raw=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw,dict):
            return UpdatePreferences(False,False)
        checks=raw.get("automatic_checks",True)
        restart=raw.get("automatic_restart",True)
        if type(checks) is not bool or type(restart) is not bool:
            return UpdatePreferences(False,False)
        return UpdatePreferences(checks,restart)
    except FileNotFoundError:
        return UpdatePreferences()
    except (OSError,ValueError,UnicodeError,TypeError):
        return UpdatePreferences(False,False)


def save_preferences(prefs: UpdatePreferences, path: Path | None = None) -> Path:
    if type(prefs) is not UpdatePreferences or type(prefs.automatic_checks) is not bool or type(prefs.automatic_restart) is not bool:
        raise ValueError("Invalid update preferences")
    path=Path(path) if path is not None else default_preferences_path()
    if path is None:
        raise OSError("LocalAppData is unavailable")
    folder=path.parent
    if folder.is_symlink() or path.is_symlink():
        raise OSError("Unsafe preferences path")
    folder.mkdir(parents=True,exist_ok=True)
    content=json.dumps({"automatic_checks":prefs.automatic_checks,
                        "automatic_restart":prefs.automatic_restart,
                        "schema":1},separators=(",",":"))
    if len(content.encode("utf-8"))>MAX_SETTINGS_BYTES:
        raise ValueError("Oversized preferences")
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
                                         dir=folder,prefix=".update-prefs-",
                                         suffix=".tmp",delete=False) as output:
            temp=Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.is_symlink():
            raise OSError("Unsafe preferences path")
        os.replace(temp,path)
        return path
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
