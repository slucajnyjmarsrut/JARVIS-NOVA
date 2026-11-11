# -*- coding: utf-8 -*-
"""Open only a verified local rendered MP4 in the user's default Windows player.

No shell, browser URL, account connection or automatic execution on render.
"""
from __future__ import annotations

import os
from pathlib import Path


class PreviewError(ValueError):
    pass


def open_local_mp4(path: Path, *, confirmed: bool = False, opener=None) -> Path:
    if confirmed is not True:
        raise PermissionError("Просмотр запускается только по нажатию пользователя.")
    raw = Path(path).expanduser()
    if (str(raw).startswith("\\\\") or raw.is_symlink()
            or not raw.is_file() or raw.suffix.casefold() != ".mp4"
            or not 1024 <= raw.stat().st_size <= 10_000_000_000):
        raise PreviewError("Выбери готовый локальный MP4 без сетевых путей.")
    video = raw.resolve(strict=True)
    if opener is None:
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise PreviewError("Просмотр через системный плеер доступен в Windows.")
        opener = os.startfile
    opener(str(video))
    return video
