# -*- coding: utf-8 -*-
"""Bounded technical quality checks from beginning, middle AND end of long MP4.

Existing audits inspect only the first 75 seconds. This sampler deliberately
seeks across the full timeline, reading at most 5 x 3 seconds of miniature
frames and PCM. A quiet or static scene may be intentional: warnings are
DIAGNOSTIC, not claims of boring footage or professional editing quality.
"""
from __future__ import annotations

import math
from pathlib import Path
import threading

from video_frame_audit import analyze_gray_frames, FRAME_BYTES
from video_audio_audit import analyze_pcm16
from viral_studio import _execute

MAX_WINDOWS=5
WINDOW_SECONDS=3


def audit_coverage(file: Path, duration: float, *, ffmpeg: str,
                   executor=None, cancel: threading.Event | None = None,
                   windows=MAX_WINDOWS):
    if type(windows) is not int or not 2 <= windows <= MAX_WINDOWS:
        raise ValueError("Нужно 2–5 областей проверки.")
    if (not isinstance(duration,(int,float)) or not math.isfinite(duration)
            or duration <= 1):
        raise ValueError("Недопустимая длина готового MP4.")
    path=Path(file)
    if not path.is_file() or path.stat().st_size<1000:
        raise ValueError("Для проверки нужен реальный MP4.")
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Проверка итогового видео отменена.")
    runner=executor if executor is not None else _execute
    window=min(float(WINDOW_SECONDS),float(duration))
    latest=max(0.,duration-window)
    starts=tuple(round(latest*i/(windows-1),3) for i in range(windows))
    results=[]
    warnings=[]
    for ix,start in enumerate(starts,1):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Проверка итогового видео отменена.")
        video_args=[
            ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
            "-ss",f"{start:.3f}","-i",str(path),"-t",f"{window:.3f}",
            "-an","-sn","-dn",
            "-vf","fps=3,scale=64:36:flags=fast_bilinear,format=gray",
            "-pix_fmt","gray","-f","rawvideo","-",
        ]
        visual=analyze_gray_frames(
            runner(video_args,timeout=35,cancel=cancel))
        audio_args=[
            ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
            "-ss",f"{start:.3f}","-i",str(path),"-t",f"{window:.3f}",
            "-vn","-sn","-dn","-map","0:a:0",
            "-ac","1","-ar","8000","-c:a","pcm_s16le",
            "-f","s16le","-",
        ]
        sound=analyze_pcm16(
            runner(audio_args,timeout=35,cancel=cancel))
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Проверка итогового видео отменена.")
        black=round(visual.black_fraction,4)
        quiet=round(sound.quiet_fraction,4)
        if black>=.90:
            warnings.append(
                f"Почти чёрный кадр около {round(start)} с; проверь вручную.")
        if sound.clipped_fraction>=.01:
            warnings.append(
                f"Возможная перегрузка звука около {round(start)} с.")
        results.append({
            "at_seconds":start,
            "sample_seconds":round(window,3),
            "video_frames":visual.sampled_frames,
            "black_fraction":black,
            "white_fraction":round(visual.white_fraction,4),
            "quiet_fraction":quiet,
            "clipped_fraction":round(sound.clipped_fraction,4),
            "rms_dbfs":round(sound.rms_dbfs,2),
        })
    return {
        "checked":True,
        "method":"distributed-mini-frame-and-PCM",
        "duration":round(duration,3),
        "regions":results,
        "warnings":warnings,
        "limitations":"Tiny samples only; cannot evaluate narrative quality.",
    }
