# -*- coding: utf-8 -*-
"""Operational safety bounds for long-form *local* media editing.

These bounds replace old short-form-only 90 second/10 clip restrictions. They
limit resource exhaustion, not the length of any particular editing preset.
"""
import math

MAX_SOURCE_SECONDS = 24 * 3600
MAX_OUTPUT_SECONDS = 8 * 3600
MAX_INPUT_BYTES = 120 * 1024**3
MAX_TIMELINE_CUTS = 64


def encode_timeout(seconds: float) -> int:
    """Provide long FFmpeg renders enough wall time on slower CPUs."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        raise ValueError("Некорректная длительность видео")
    if seconds <= 0 or seconds > MAX_OUTPUT_SECONDS:
        raise ValueError("Недопустимая длительность монтажа")
    return max(900, min(24 * 3600, math.ceil(seconds * 16)))
