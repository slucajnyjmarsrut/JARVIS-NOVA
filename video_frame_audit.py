# -*- coding: utf-8 -*-
"""Offline visual quality probe of a finished clip.

Only raw 64x36 grayscale samples pass through RAM; no images saved, no web,
face identification or arbitrary instructions. Static shots may be intentional:
frozen-frame signals are informational, not automatic proof of bad editing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path

WIDTH, HEIGHT, FPS = 64, 36, 3
FRAME_BYTES = WIDTH * HEIGHT
MAX_SECONDS = 75
MAX_FRAMES = MAX_SECONDS * FPS + 3


class FrameAuditError(ValueError):
    pass


@dataclass(frozen=True)
class FrameAudit:
    sampled_frames: int
    sample_seconds: float
    black_fraction: float
    white_fraction: float
    longest_static_seconds: float
    warnings: tuple[str, ...]


def analyze_gray_frames(payload: bytes) -> FrameAudit:
    """Detect blank frames and long unchanging stretches using bounded data."""
    if not isinstance(payload, bytes) or not payload or len(payload) % FRAME_BYTES:
        raise FrameAuditError("Нет корректных видеокадров для контроля качества")
    count = len(payload) // FRAME_BYTES
    if count > MAX_FRAMES:
        raise FrameAuditError("Слишком много кадров для проверки")
    black = white = static = longest = 0
    prev = None
    for start in range(0, len(payload), FRAME_BYTES):
        frame = payload[start:start + FRAME_BYTES]
        mean = sum(frame) / FRAME_BYTES
        black += mean < 13
        white += mean > 244
        if prev is not None:
            change = sum(abs(a-b) for a,b in zip(prev, frame)) / FRAME_BYTES
            static = static + 1 if change < 0.7 else 0
            longest = max(longest,static)
        prev = frame
    black_share = round(black/count,4)
    white_share = round(white/count,4)
    static_sec = round(longest/FPS,2)
    warnings = []
    if black_share > 0.12:
        warnings.append("Много очень тёмных или чёрных кадров")
    if white_share > 0.12:
        warnings.append("Много засвеченных или белых кадров")
    if static_sec >= 4:
        warnings.append("Есть длительный статичный фрагмент: возможное зависание изображения")
    return FrameAudit(count,round(count/FPS,2),black_share,white_share,
                      static_sec,tuple(warnings))


def inspect_video_frames(file: Path, ffmpeg: str, *, cancel=None, executor=None) -> FrameAudit:
    """Bounded FFmpeg decode; existing MP4 is read-only and never uploaded."""
    if cancel is not None and cancel.is_set():
        raise FrameAuditError("Проверка видео отменена")
    if executor is None:
        from viral_studio import _execute
        executor = _execute
    argv = [ffmpeg,"-v","error","-nostdin","-t",str(MAX_SECONDS),
            "-i",str(Path(file)),"-an","-vf",f"fps={FPS},scale={WIDTH}:{HEIGHT},format=gray",
            "-f","rawvideo","-pix_fmt","gray","-"]
    raw = executor(argv,timeout=45,cancel=cancel)
    if cancel is not None and cancel.is_set():
        raise FrameAuditError("Проверка видео отменена")
    return analyze_gray_frames(raw)


def frame_report(result: FrameAudit) -> dict:
    return asdict(result)
