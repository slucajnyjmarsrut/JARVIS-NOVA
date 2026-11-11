# -*- coding: utf-8 -*-
"""Optional, bounded OFFLINE Qwen-Vision review of long-form timeline offsets.

Only AFTER the user explicitly approves an automatic edit and the real local
Qwen Vision runtime is available. The model sees paired miniature frames in
RAM, never original files or unbounded film. Its answer can ONLY select one
of two existing validated clip positions; it cannot issue commands, edit
the user footage, publish or change the requested duration.

This is heuristic visual preference, not reliable story understanding.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import math
from pathlib import Path
import re
import threading

from PIL import Image, ImageDraw

MAX_PAIRS=6
MAX_THUMB_BYTES=250_000
FRAME_WIDTH=240
FRAME_HEIGHT=136


@dataclass(frozen=True)
class SemanticReport:
    compared: int
    chosen_alternative: int
    failed: int
    method: str = "local-qwen-frame-comparison"
    limitations: str = "Two thumbnails do not reveal plot, dialogue or causality."


def _jpeg_at(path, at, *, ffmpeg, executor, cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Визуальная проверка отменена.")
    cmd=[
        ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
        "-ss",f"{at:.3f}","-i",str(path),"-frames:v","1",
        "-vf",f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:flags=fast_bilinear",
        "-an","-sn","-dn","-f","image2pipe","-vcodec","mjpeg","-",
    ]
    raw=executor(cmd,timeout=22,cancel=cancel)
    if (not isinstance(raw,bytes) or not 100<=len(raw)<=MAX_THUMB_BYTES
            or not raw.startswith(b"\xff\xd8\xff")
            or not raw.endswith(b"\xff\xd9")):
        raise ValueError("Некорректный мини-кадр для Vision.")
    with Image.open(BytesIO(raw)) as image:
        if image.size != (FRAME_WIDTH,FRAME_HEIGHT):
            raise ValueError("FFmpeg вернул кадр неверного размера.")
        return image.convert("RGB")


def _paired_jpeg(first,second):
    canvas=Image.new("RGB",(FRAME_WIDTH*2,FRAME_HEIGHT+28),
                     color=(16,24,33))
    canvas.paste(first,(0,28))
    canvas.paste(second,(FRAME_WIDTH,28))
    draw=ImageDraw.Draw(canvas)
    draw.text((8,8),"A: motion/audio",fill="white")
    draw.text((FRAME_WIDTH+8,8),"B: timeline",fill="white")
    buf=BytesIO()
    canvas.save(buf,format="JPEG",quality=78,optimize=True)
    result=buf.getvalue()
    if len(result)>MAX_THUMB_BYTES:
        raise ValueError("Слишком большая составная картинка.")
    return result


def _chosen_label(text):
    if not isinstance(text,str) or len(text)>400:
        return None
    # Do not parse prose as commands. Accept only a deliberately constrained
    # answer, and default to the already activity-selected position otherwise.
    answer=text.strip().upper().rstrip(" .!")
    return answer if answer in ("A","B") else None


def review_longform_offsets(
        cuts, sources, *, target_seconds, ffmpeg, executor, vision,
        confirmed=False, cancel: threading.Event | None = None,
        max_pairs=MAX_PAIRS, progress=None):
    """Compare max six pairs across whole timeline without changing clip order.

    Only reverts a movement/volume-selected candidate to its safe uniform
    offset if a real Qwen Vision model chooses B. Never invents a position.
    """
    from video_timeline import draft_longform_cuts
    if confirmed is not True:
        raise PermissionError("Нужно разрешение на локальный Vision-анализ видео.")
    if type(max_pairs) is not int or not 1<=max_pairs<=MAX_PAIRS:
        raise ValueError("Недопустимый лимит анализа Vision.")
    if vision is None or not callable(getattr(vision,"describe",None)):
        raise ValueError("Нет запущенной локальной модели Vision.")
    cuts=tuple(cuts)
    baseline=draft_longform_cuts(
        sources,target_seconds=target_seconds)
    if len(cuts)!=len(baseline):
        raise ValueError("Таймлайн изменился после локального анализа.")
    for a,b in zip(cuts,baseline):
        if (a.path!=b.path or
                abs(a.duration-b.duration)>.02 or
                abs(a.speed-b.speed)>.0001):
            raise ValueError("Неверные исходные позиции или длины таймлайна.")
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Визуальный анализ отменён.")
    if not cuts:
        return cuts,SemanticReport(0,0,0)
    count=min(max_pairs,len(cuts))
    indices=tuple(sorted(set(
        round(i*(len(cuts)-1)/(count-1))
        for i in range(count)))) if count>1 else (0,)
    updated=list(cuts)
    compared=alternative=failed=0
    question=(
        "Здесь рядом два кадра одного видео: A слева и B справа. "
        "Выбери ОДИН кадр, который информативнее для короткого "
        "монтажного ролика. Только видимая картинка, не угадывай сюжет "
        "вне кадра. Если нет уверенности, выбери A. "
        "Ответ ровно ОДНОЙ латинской буквой: A или B."
    )
    for done,i in enumerate(indices,1):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Визуальный анализ отменён.")
        current,even=cuts[i],baseline[i]
        if abs(current.source_start-even.source_start)<2:
            if progress:progress(done,len(indices),"Сравниваю мини-кадры")
            continue
        try:
            at_a=current.source_start+min(3.,current.duration/2)
            at_b=even.source_start+min(3.,even.duration/2)
            first=_jpeg_at(current.path,at_a,ffmpeg=ffmpeg,
                           executor=executor,cancel=cancel)
            second=_jpeg_at(even.path,at_b,ffmpeg=ffmpeg,
                            executor=executor,cancel=cancel)
            text=vision.describe(question,_paired_jpeg(first,second))
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Визуальный анализ отменён.")
            result=_chosen_label(text)
            if result is None:
                failed+=1
            else:
                compared+=1
                if result=="B":
                    updated[i]=replace(current,
                                       source_start=even.source_start)
                    alternative+=1
        except InterruptedError:
            raise
        except Exception:
            # Model is optional. A failed Vision call MUST NOT destroy
            # the deterministic motion+audio montage or use network fallback.
            failed+=1
        if progress:progress(done,len(indices),"Сравниваю мини-кадры")
    return tuple(updated),SemanticReport(compared,alternative,failed)
