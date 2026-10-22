# -*- coding: utf-8 -*-
"""Offline PCM-level diagnostics on a finished MP4's audio stream.

Checks only silence, clipping, peak and average energy. Quiet footage and
intentional silence are NOT automatically errors. Never downloads music or
makes claims about speech intelligibility or subjective audio quality.
"""
from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import sys

SAMPLE_RATE = 8000
MAX_SECONDS = 75
MAX_BYTES = (MAX_SECONDS + 1) * SAMPLE_RATE * 2


class AudioAuditError(ValueError):
    pass


@dataclass(frozen=True)
class AudioAudit:
    sampled_seconds: float
    rms_dbfs: float
    peak_dbfs: float
    quiet_fraction: float
    clipped_fraction: float
    warnings: tuple[str, ...]


def analyze_pcm16(raw: bytes) -> AudioAudit:
    if not isinstance(raw,bytes) or not raw or len(raw)%2 or len(raw)>MAX_BYTES:
        raise AudioAuditError("Нет корректного ограниченного PCM для анализа")
    pcm = array("h")
    pcm.frombytes(raw)
    if sys.byteorder != "little":
        pcm.byteswap()
    if not pcm:
        raise AudioAuditError("Пустая звуковая дорожка")
    total = len(pcm)
    peak = max(abs(x) for x in pcm) / 32768
    rms = math.sqrt(sum((x/32768)**2 for x in pcm) / total)
    quiet = sum(abs(x) < 328 for x in pcm) / total
    clipped = sum(abs(x) >= 32600 for x in pcm) / total
    warnings = []
    if quiet >= .92:
        warnings.append("Почти вся аудиодорожка тихая или без звука")
    if clipped >= .002:
        warnings.append("Возможная перегрузка звука: много отсечённых пиков")
    if rms > .4:
        warnings.append("Очень высокий средний уровень громкости")
    # Avoid -inf in JSON and report as a bounded floor.
    def decibels(level):
        return round(max(-96.,20*math.log10(max(level,10**(-96/20)))),2)
    return AudioAudit(round(total/SAMPLE_RATE,2),decibels(rms),decibels(peak),
                      round(quiet,4),round(clipped,4),tuple(warnings))


def inspect_audio(file: Path, ffmpeg: str, *, ffprobe=None,
                  executor=None, cancel=None) -> AudioAudit:
    """Measure audio, with an explicit warning for genuine video-only exports.

    FFmpeg does not produce PCM for a file without an audio stream, even when
    '-map 0:a:0?' is used. Detect that condition with FFprobe instead of
    masking real decoder errors or losing the entire visual audit.
    """
    if cancel is not None and cancel.is_set():
        raise AudioAuditError("Проверка звука отменена")
    if executor is None:
        from viral_studio import _execute
        executor = _execute
    if ffprobe is not None:
        probe=[str(ffprobe),"-v","error","-select_streams","a:0",
               "-show_entries","stream=index","-of","csv=p=0",str(Path(file))]
        streams=executor(probe,timeout=20,cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise AudioAuditError("Проверка звука отменена")
        if not isinstance(streams,bytes):
            raise AudioAuditError("FFprobe вернул некорректные данные")
        if not streams.strip():
            return AudioAudit(0.,-96.,-96.,1.,0.,
                              ("В готовом MP4 отсутствует звуковая дорожка",))
    cmd=[ffmpeg,"-v","error","-nostdin","-t",str(MAX_SECONDS),"-i",str(Path(file)),
         "-vn","-map","0:a:0","-ac","1","-ar",str(SAMPLE_RATE),
         "-f","s16le","-acodec","pcm_s16le","-"]
    raw=executor(cmd,timeout=45,cancel=cancel)
    if cancel is not None and cancel.is_set():
        raise AudioAuditError("Проверка звука отменена")
    return analyze_pcm16(raw)


def audio_report(result: AudioAudit) -> dict:
    return asdict(result)
