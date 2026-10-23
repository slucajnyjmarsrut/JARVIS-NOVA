# -*- coding: utf-8 -*-
"""Persist ONLY window positions, never microphone audio, chat, or permissions."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_PATTERN = re.compile(r"^(\d{2,4})x(\d{2,4})\+(-?\d{1,5})\+(-?\d{1,5})$")
_MAX_BYTES = 2048


def config_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".jarvis-nova"))
    return root / "JARVIS-NOVA" / "ui-layout.json"


def load_layout(path: Path | None = None) -> dict:
    """Untrusted JSON never controls window geometry without later clamping."""
    path = path or config_path()
    try:
        if path.stat().st_size > _MAX_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {key: val for key, val in data.items()
                    if key in ("main", "mini") and isinstance(val, str)
                    and len(val) < 48}
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    return {}


def safe_window_geometry(value: str | None, fallback: str,
                         sw: int, sh: int, *, fixed: bool = False) -> str:
    """Clamp geometry to the available desktop; do not trust stored dimensions."""
    sw, sh = max(1, int(sw)), max(1, int(sh))
    default = _PATTERN.fullmatch(fallback)
    if default is None:
        raise ValueError("Invalid fallback geometry")
    match = _PATTERN.fullmatch(value or "")
    base = match or default
    bw, bh = int(default.group(1)), int(default.group(2))
    width = bw if fixed else max(320, min(900, int(base.group(1))))
    height = bh if fixed else max(380, min(1100, int(base.group(2))))
    width, height = min(sw, width), min(sh, height)
    x = max(0, min(int(base.group(3)), sw-width))
    y = max(0, min(int(base.group(4)), sh-height))
    return f"{width}x{height}+{x}+{y}"


def save_layout(main: str | None, mini: str | None,
                path: Path | None = None) -> bool:
    """Crash-safe replacement; failure cannot interrupt assistant shutdown."""
    path = path or config_path()
    data = {}
    for label, value in (("main", main), ("mini", mini)):
        if isinstance(value, str) and _PATTERN.fullmatch(value):
            data[label] = value
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
