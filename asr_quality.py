# -*- coding: utf-8 -*-
"""Confidence-guided Russian Whisper decoding, with no extra I/O.

Second pass is reserved for user-activated commands with unreliable first-pass
decoding; ordinary background audio never causes expensive repeated inference.
These heuristics do NOT authorize commands: that remains voice_engine's job.
"""
from __future__ import annotations
import math


def _segments(result):
    if not isinstance(result,dict):
        return []
    return [s for s in result.get("segments",()) if isinstance(s,dict)]


def _number(value,default):
    try:
        number=float(value)
        return number if math.isfinite(number) else default
    except (TypeError,ValueError,OverflowError):
        return default


def transcript_confidence(result):
    """Return estimated score from Whisper's own per-segment metadata.

    Whisper numbers are not calibrated probabilities. Low score means *try a
    second decode*, not that the text is safe to execute.
    """
    chunks=_segments(result)
    if not chunks:
        return None
    avg=sum(_number(s.get("avg_logprob"),-2.0) for s in chunks)/len(chunks)
    compression=max(_number(s.get("compression_ratio"),1.0) for s in chunks)
    silence=max(_number(s.get("no_speech_prob"),0.0) for s in chunks)
    return avg-max(0.0,compression-2.2)*0.5-max(0.0,silence-0.5)*.35


def should_refine(result, authorized=False):
    """Refine only if F9/Vosk wake or first-pass wake actually authorized it."""
    if not authorized:
        return False
    content=str(result.get("text","") or "").strip() if isinstance(result,dict) else ""
    if not content or len(content)<4:
        return True
    confidence=transcript_confidence(result)
    return confidence is not None and confidence < -.76


def prefer_refined(first,second):
    """Pick the more credible result; avoid executing weak hallucinations."""
    a=str(first.get("text","") or "").strip() if isinstance(first,dict) else ""
    b=str(second.get("text","") or "").strip() if isinstance(second,dict) else ""
    if not a:
        return second if b else first
    if not b:
        # A low-quality original that disappears with a stronger search
        # should not be executed as a command.
        confidence=transcript_confidence(first)
        return second if confidence is not None and confidence < -1.1 else first
    ac=transcript_confidence(first)
    bc=transcript_confidence(second)
    if ac is not None and bc is not None:
        return second if bc>ac+.03 else first
    # Fake models and some adapters omit per-segment metadata. Their second
    # pass still helps blank transcription, but cannot validate disagreements.
    return first
