# -*- coding: utf-8 -*-
"""Bounded scene-activity scoring of local footage, no cloud or face recognition.

Selects source windows using miniature luminance frames sampled via FFmpeg.
This is a deterministic proxy for *visual activity*, not semantic relevance:
a quiet interview can be important and a busy scene can be irrelevant.
The reviewable timeline and final export remain user-controlled.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import math
import threading

FRAME_W, FRAME_H, FRAMES = 48, 27, 3
FRAME_BYTES = FRAME_W * FRAME_H
MAX_SAMPLE_WINDOWS = 192


@dataclass(frozen=True)
class ActivityReport:
    examined: int
    usable: int
    fallback: int
    method: str = "local-grayscale-motion"


def frame_activity(raw: bytes) -> float:
    """Score a bounded 3-frame raw grayscale sample, from 0 to 1."""
    if not isinstance(raw, bytes) or not 1 <= len(raw)//FRAME_BYTES <= FRAMES:
        raise ValueError("Нет кадров для анализа")
    if len(raw) % FRAME_BYTES:
        raise ValueError("Размер выборки FFmpeg неверен")
    frames = [memoryview(raw)[i:i+FRAME_BYTES]
              for i in range(0,len(raw),FRAME_BYTES)]
    means = [sum(frame)/FRAME_BYTES for frame in frames]
    mean = sum(means)/len(means)
    if mean < 14 or mean > 244:
        return 0.01
    # Both within-frame detail and between-frame motion are important.
    details = sum(sum(abs(pixel - avg) for pixel in frame)/FRAME_BYTES
                  for frame,avg in zip(frames,means))/len(frames)
    motion = (sum(sum(abs(x-y) for x,y in zip(left,right))/FRAME_BYTES
                  for left,right in zip(frames,frames[1:]))
              /max(1,len(frames)-1))
    visible = max(.0, 1.0-abs(mean-125)/130.)
    return round(min(1., .08+.37*min(1.,details/48)
                     +.50*min(1.,motion/65)+.05*visible),5)


def _sample(path, seconds, *, ffmpeg, executor, cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Анализ видео отменён")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{seconds:.3f}", "-i", str(path),
            "-t", "2", "-vf", f"fps=1.5,scale={FRAME_W}:{FRAME_H}:flags=fast_bilinear",
            "-frames:v", str(FRAMES), "-an", "-sn", "-dn",
            "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    raw = executor(args, timeout=25, cancel=cancel)
    return frame_activity(raw)


def select_active_cuts(sources, *, target_seconds=900., ffmpeg,
                       executor, cancel: threading.Event | None = None,
                       progress=None, max_windows=MAX_SAMPLE_WINDOWS):
    """Replace uniform draft offsets with locally sampled active periods.

    Each draft segment stays in its chronological source interval, so the
    selection cannot skip all quiet sections or put later scenes first.
    Failed decoding falls back to the uniform position for that segment.
    No footage is copied, written or uploaded, and the source is not decoded
    wholesale. A caller must still review and explicitly export the draft.
    """
    from video_timeline import draft_longform_cuts, TimelineError
    if type(max_windows) is not int or not 1 <= max_windows <= MAX_SAMPLE_WINDOWS:
        raise ValueError("Недопустимое число окон анализа")
    cuts = list(draft_longform_cuts(sources,target_seconds=target_seconds))
    lengths = {Path(path).resolve():float(seconds) for path,seconds in sources}
    by_source: dict[Path,list[int]] = {}
    for index, cut in enumerate(cuts):
        by_source.setdefault(cut.path,[]).append(index)
    candidate_sets = []
    for path,indices in by_source.items():
        source_duration=lengths[path]
        for rank,i in enumerate(indices):
            cut=cuts[i]
            region_start=rank*source_duration/len(indices)
            region_end=(rank+1)*source_duration/len(indices)
            latest=max(region_start,region_end-cut.duration)
            starts=(region_start,(region_start+latest)/2,latest)
            starts=tuple(sorted(set(round(max(0., min(
                source_duration-cut.duration,start)),3) for start in starts)))
            candidate_sets.append((i,path,cut,starts))
    # Cap all decoder invocations, including caller-selected small budgets.
    sampled=usable=fallback=0
    slots=max(1,max_windows//len(candidate_sets))
    for processed,(i,path,cut,starts) in enumerate(candidate_sets,1):
        if sampled >= max_windows:
            fallback+=1
            if progress:
                progress(processed,len(cuts),"Сравниваю сцены")
            continue
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Анализ видео отменён")
        slots_left=min(slots,max_windows-sampled)
        selected=starts if len(starts)<=slots_left else tuple(
            starts[round(k*(len(starts)-1)/(slots_left-1))]
            for k in range(slots_left)) if slots_left>1 else (starts[len(starts)//2],)
        best=(float("-inf"),cut.source_start)
        success=False
        for start in selected:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Анализ видео отменён")
            sampled+=1
            # Probe a couple of seconds near each candidate's beginning.
            at=min(lengths[path]-.1,start+min(5.,cut.duration/2))
            try:
                score=_sample(path,at,ffmpeg=ffmpeg,
                              executor=executor,cancel=cancel)
            except InterruptedError:
                raise
            except Exception:
                score=float("-inf")
            if math.isfinite(score):
                usable+=1
                success=True
                # Small preference for the baseline when scores are equal.
                rank_score=score-abs(start-cut.source_start)*1.e-7
                if rank_score>best[0]:
                    best=(rank_score,start)
        if success:
            cuts[i]=replace(cut,source_start=best[1])
        else:
            fallback+=1
        if progress:
            progress(processed,len(cuts),"Сравниваю сцены")
    # All paths, boundaries and durations must remain checked on export.
    return tuple(cuts), ActivityReport(sampled,usable,fallback)
