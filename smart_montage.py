# -*- coding: utf-8 -*-
"""Bounded, entirely local selection and validation for automatic vertical edits.

FFmpeg analyzes low-resolution grayscale frames in RAM. No internet, image
export, face tracking or arbitrary filter execution. The scorer is deterministic.
"""
from __future__ import annotations
import json
import math
from pathlib import Path


class MontageQualityError(RuntimeError):
    pass


FRAME_W = 32
FRAME_H = 32
FPS = 2
FRAME_BYTES = FRAME_W * FRAME_H
MAX_ANALYSIS_SECONDS = 75


def _frame_scores(pcm: bytes) -> list[float]:
    """Prefer well-exposed, detailed, moderately active frames over blank/shaky cuts."""
    if not isinstance(pcm, bytes) or len(pcm) % FRAME_BYTES:
        raise MontageQualityError("Некорректные видеокадры для анализа")
    if len(pcm) > FRAME_BYTES * FPS * (MAX_ANALYSIS_SECONDS + 2):
        raise MontageQualityError("Слишком длинный анализ видео")
    scores = []
    previous = None
    for start in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[start:start+FRAME_BYTES]
        if not frame:
            continue
        level = sum(frame) / FRAME_BYTES
        # Black, white and severely underexposed frames are unsuitable.
        exposure = max(0., 1. - abs(level-123.)/110.)
        detail = sum(abs(frame[i]-frame[i-1]) for i in range(1,len(frame))) / (len(frame)-1)
        motion = (sum(abs(a-b) for a,b in zip(frame,previous)) / FRAME_BYTES
                  if previous is not None else 0.)
        previous = frame
        moderate_motion = max(0., 1. - abs(motion-19.)/55.)
        score = .48*exposure + .30*min(1.,detail/34.) + .22*moderate_motion
        if level < 16 or level > 242:
            score *= .12
        scores.append(round(score,6))
    return scores


def best_start(scores: list[float], duration: float, segment_seconds: float, fps: int = FPS) -> float:
    """Sliding-window highlight selection. Never seek past valid playable seconds."""
    if not math.isfinite(duration) or not math.isfinite(segment_seconds) or duration < .8:
        return 0.
    if fps < 1 or fps > 30:
        raise ValueError("Недопустимая частота кадров")
    max_start = max(0., duration-segment_seconds-.07)
    if max_start <= .3 or len(scores) < 4:
        return 0.
    frames = max(2, math.ceil(segment_seconds*fps))
    max_index = min(len(scores)-frames, int(max_start*fps))
    if max_index <= 0:
        return 0.
    summed = sum(scores[:frames])
    winner = (summed, 0)
    for i in range(1,max_index+1):
        summed += scores[i+frames-1]-scores[i-1]
        if summed > winner[0] + .005:
            winner = (summed,i)
    return round(min(max_start,winner[1]/fps),2)


def choose_highlight_start(clip: Path, duration: float, seconds: float,
                           ffmpeg: str, *, cancel=None, executor=None) -> float:
    """Sample up to 75 seconds only; revert to conventional trimmed start on failure."""
    if duration <= seconds+.4:
        return 0.
    if cancel is not None and cancel.is_set():
        raise MontageQualityError("Монтаж отменён")
    if executor is None:
        from viral_studio import _execute
        executor = _execute
    sampled = min(MAX_ANALYSIS_SECONDS,duration-.05)
    args = [ffmpeg,"-v","error","-nostdin","-ss","0","-t",str(sampled),
            "-i",str(clip),"-vf",f"fps={FPS},scale={FRAME_W}:{FRAME_H},format=gray",
            "-f","rawvideo","-pix_fmt","gray","-"]
    try:
        raw = executor(args,timeout=45,cancel=cancel)
        score = _frame_scores(raw)
        start = best_start(score,min(sampled,duration),seconds)
        return min(start,max(0.,duration-seconds-.07))
    except (OSError,ValueError,MontageQualityError,RuntimeError) as exc:
        # A canceled FFmpeg scan is not an optional quality failure: it must
        # abort the montage rather than silently start rendering anyway.
        if cancel is not None and cancel.is_set():
            raise MontageQualityError("Монтаж отменён") from exc
        # Unreadable preview frames may fall back; real clip validation
        # still happens through the strict probe during rendering.
        return .15 if duration>seconds+.3 else 0.


def verify_output_media(file: Path, ffprobe: str, expected_seconds: float,
                        *, executor=None, cancel=None) -> dict:
    """Independent FFprobe pass: actual vertical H264 video and audio, sane duration."""
    if executor is None:
        from viral_studio import _execute
        executor = _execute
    raw = executor([ffprobe,"-v","error","-show_format","-show_streams",
                    "-of","json",str(file)],timeout=30,cancel=cancel)
    try:
        obj = json.loads(raw)
        tracks = obj["streams"]
        videos = [s for s in tracks if s.get("codec_type")=="video"]
        audios = [s for s in tracks if s.get("codec_type")=="audio"]
        video=videos[0]
        width=int(video.get("width",0))
        height=int(video.get("height",0))
        length=float(obj["format"]["duration"])
        if (not math.isfinite(length) or length<.7 or length>95
                or not math.isfinite(expected_seconds)
                or abs(length-expected_seconds)>max(.45,expected_seconds*.08)):
            raise ValueError("unexpected duration")
        if video.get("codec_name")!="h264" or width<144 or height<256 or width>=height:
            raise ValueError("video codec/geometry")
        if not audios or audios[0].get("codec_name")!="aac":
            raise ValueError("missing AAC sound")
        if not Path(file).is_file() or Path(file).stat().st_size<1000:
            raise ValueError("missing output")
    except (TypeError,KeyError,IndexError,ValueError,OverflowError) as exc:
        raise MontageQualityError("Итоговый ролик не прошёл техническую проверку") from exc
    return {"duration":length,"video_codec":"h264","audio_codec":"aac",
            "width":width,"height":height,"quality_checked":True}


def caption_subtitles(segments: list[dict]) -> str:
    """Write a synchronized SRT of screen captions, NOT fake ASR subtitles.

    Each title is timed to the rendered clip duration. Captions are already
    burned into the MP4; SRT is an accessible sidecar for manual corrections.
    """
    def clock(milliseconds: int) -> str:
        hours,remain=divmod(milliseconds,3_600_000)
        mins,remain=divmod(remain,60_000)
        sec,ms=divmod(remain,1000)
        return f"{hours:02d}:{mins:02d}:{sec:02d},{ms:03d}"
    current=0
    entries=[]
    if len(segments)>10:
        raise MontageQualityError("Слишком много титров")
    for item in segments:
        try:
            seconds=float(item["seconds"])
            caption=" ".join(str(item["on_screen"]).split())[:100]
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            raise MontageQualityError("Некорректная разметка титров") from exc
        if not math.isfinite(seconds) or not .7<=seconds<=15. or not caption:
            raise MontageQualityError("Недопустимая длина титра")
        start=current
        current+=round(seconds*1000)
        entries.append(f"{len(entries)+1}\n{clock(start)} --> {clock(current)}\n{caption}\n")
    return "\n".join(entries)+"\n" if entries else ""
