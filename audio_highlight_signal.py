# -*- coding: utf-8 -*-
"""Local, short-window audio activity metric for long-form montage.

Does not transcribe speech, recognize speakers, use microphones, or upload
sound. Detects audible (non-silent) portions, which can help preserve
interviews or commentary even if the image itself hardly moves.
Loud noise and music also score highly: this is NOT semantic editing.
"""
from __future__ import annotations

from array import array
import math
import sys

MAX_AUDIO_BYTES=4 * 2 * 4000


def audio_activity(raw: bytes) -> float:
    """Decode <=4s mono PCM16 and score measurable volume [0..1]."""
    if not isinstance(raw,bytes):
        raise ValueError("Audio response is not PCM bytes")
    if not raw:
        return 0.
    if len(raw)%2 or len(raw)>MAX_AUDIO_BYTES:
        raise ValueError("Invalid bounded audio sample size")
    pcm=array("h")
    pcm.frombytes(raw)
    if sys.byteorder!="little":
        pcm.byteswap()
    count=len(pcm)
    if count<100:
        return 0.
    # RMS is sensitive to real voiced passages, but cannot tell speech
    # from music, noise, or important quiet moments.
    rms=math.sqrt(sum(float(n)*n for n in pcm)/count)
    if rms<90:
        return 0.
    loud=min(1.,max(0.,math.log1p(rms/90)/math.log1p(9000/90)))
    clipped=sum(abs(n)>=32000 for n in pcm)/count
    return round(max(0.,min(1.,loud*(1-min(1.,clipped*2)))),5)


def sample_audio_activity(path,seconds,*,ffmpeg,executor,cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Анализ звука отменён")
    cmd=[ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
         "-ss",f"{seconds:.3f}","-i",str(path),"-t","2",
         "-map","0:a:0?","-vn","-ac","1","-ar","4000",
         "-c:a","pcm_s16le","-f","s16le","-"]
    return audio_activity(executor(cmd,timeout=25,cancel=cancel))
