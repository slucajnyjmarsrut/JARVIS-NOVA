# -*- coding: utf-8 -*-
"""Offline popular montage styles for user-provided clips.

All effects are predefined FFmpeg filter constants. Never execute model output,
download copyrighted content, overwrite user footage or publish videos.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone

from pro_montage import ProOptions, validate_options, color_filter, finish_video


class PopularEditError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditStyle:
    name: str
    label: str
    description: str
    size: tuple[int, int]
    seconds: float
    color: str
    transition: str
    transition_seconds: float
    speeds: tuple[float, ...] = (1.0,)


STYLES = (
    EditStyle("shorts", "YouTube Shorts", "9:16 · быстрые динамичные склейки", (720,1280), 1.9, "vibrant", "fade", .12),
    EditStyle("tiktok", "TikTok edit", "9:16 · яркие быстрые кадры", (720,1280), 1.15, "highcontrast", "slideleft", .12),
    EditStyle("reels", "Instagram Reels", "9:16 · чистая динамика", (720,1280), 2.1, "warm", "dissolve", .22),
    EditStyle("amv", "AMV / эдит", "9:16 · аниме/клипы · быстрые смены", (720,1280), 1.25, "vibrant", "fadeblack", .14),
    EditStyle("velocity", "Velocity", "9:16 · чередование slow и fast motion", (720,1280), 1.65, "highcontrast", "fade", .12, (.65, 1.8)),
    EditStyle("gaming", "Gaming highlights", "16:9 · игровые моменты", (1280,720), 2.1, "vibrant", "wipeleft", .14),
    EditStyle("cinematic", "Кино / Cinematic", "16:9 · плавные кино-переходы", (1280,720), 4.2, "cinematic", "dissolve", .38),
    EditStyle("vlog", "Vlog / YouTube", "16:9 · естественная цветокоррекция", (1280,720), 3.5, "natural", "fade", .20),
    EditStyle("travel", "Travel / Путешествия", "9:16 · атмосферные сцены", (720,1280), 3.0, "warm", "circleopen", .25),
    EditStyle("tutorial", "Обучение / обзоры", "16:9 · чёткие сцены без эффектов", (1280,720), 4.0, "natural", "fade", 0.0),
    EditStyle("podcast", "Подкаст / интервью", "1:1 · спокойный квадратный монтаж", (960,960), 5.0, "natural", "dissolve", .25),
    EditStyle("meme", "Meme / Funny", "9:16 · резкие смешные склейки", (720,1280), 1.05, "highcontrast", "fade", 0.0),
    EditStyle("retro", "Retro / VHS настроение", "4:5 · мягкий тёплый оттенок", (864,1080), 2.4, "retro", "fadewhite", .18),
    EditStyle("product", "Реклама продукта", "4:5 · стильная презентация", (864,1080), 2.8, "cool", "smoothleft", .25),
    EditStyle("dreamy", "Dreamy / эстетика", "9:16 · мягкие медленные переходы", (720,1280), 3.5, "dreamy", "dissolve", .3),
    EditStyle("noir", "Ч/б / Noir", "16:9 · контрастное чёрно-белое кино", (1280,720), 3.3, "noir", "fadeblack", .22),
)
STYLE_BY_NAME = {style.name: style for style in STYLES}
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})
from long_video_limits import (
    MAX_INPUT_BYTES, MAX_TIMELINE_CUTS, MAX_OUTPUT_SECONDS, encode_timeout)
MAX_CLIPS = MAX_TIMELINE_CUTS


def is_popular_edit_request(message: str) -> bool:
    """Route explicit Russian edit requests to the studio, never run edits silently."""
    if not isinstance(message,str) or not 3<=len(message)<=400:
        return False
    value=" ".join(message.casefold().replace("ё","е").split()).strip(" !.,")
    for prefix in ("джарвис, ", "джарвис ", "jarvis, ", "jarvis ", "nova "):
        if value.startswith(prefix):
            value=value[len(prefix):]
            break
    return value.startswith((
        "сделай эдит", "создай эдит", "собери эдит", "хочу эдит",
        "сделай монтаж", "собери монтаж",
        "сделай шортс", "сделай shorts",
        "создай рилс", "сделай рилс",
        "смонтируй видео", "эдит для тиктока",
    ))


def select_style(name: str) -> EditStyle:
    if not isinstance(name, str) or name not in STYLE_BY_NAME:
        raise PopularEditError("Неизвестный стиль монтажа.")
    return STYLE_BY_NAME[name]


def source_clips(folder: Path) -> list[Path]:
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise PopularEditError("Выбери существующую обычную папку с видео.")
    folder = folder.resolve()
    if not folder.is_dir():
        raise PopularEditError("Выбери существующую папку с собственными видео.")
    clips = sorted(
        (p for p in folder.iterdir()
         if p.is_file() and not p.is_symlink() and
         p.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda p: p.name.casefold())
    if not clips:
        raise PopularEditError("Нужен минимум один ролик MP4, MOV, MKV, WEBM или AVI.")
    if len(clips) > MAX_CLIPS:
        raise PopularEditError(f"Для одного эдита выбери не больше {MAX_CLIPS} исходников.")
    for clip in clips:
        if not 2_000 <= clip.stat().st_size <= MAX_INPUT_BYTES:
            raise PopularEditError("Некорректный или слишком большой клип: " + clip.name[:80])
    return clips


def speed_for(style: EditStyle, clip_index: int) -> float:
    speed = style.speeds[clip_index % len(style.speeds)]
    if not math.isfinite(speed) or not .5 <= speed <= 2.:
        raise PopularEditError("Недопустимая скорость монтажа.")
    return speed


def _segment_filter(style: EditStyle, *, speed: float, seconds: float,
                    has_audio: bool) -> str:
    width, height = style.size
    # Never interpolate user text into filter expressions.
    video = (
        f"[0:v:0]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,"
        f"setpts=(PTS-STARTPTS)/{speed:.3f},"
        f"{color_filter(style.color)}format=yuv420p[v]"
    )
    audio_source = "0:a:0" if has_audio else "1:a:0"
    audio = (
        f"[{audio_source}]aresample=48000,"
        f"atempo={speed:.3f},apad,atrim=duration={seconds:.3f},"
        "asetpts=PTS-STARTPTS[a]"
    ) if has_audio else (
        f"[{audio_source}]aresample=48000,"
        f"atrim=duration={seconds:.3f},asetpts=PTS-STARTPTS[a]"
    )
    return video + ";" + audio


def verify_edit_output_media(file: Path, ffprobe: str, *,
                             size: tuple[int,int], expected_seconds: float,
                             executor, cancel=None, max_duration=95.) -> dict:
    """Validate H264/AAC and exact dimensions across vertical, wide and square."""
    from viral_studio import ViralStudioError
    raw=executor([ffprobe,"-v","error","-show_format","-show_streams",
                  "-of","json",str(file)],timeout=30,cancel=cancel)
    try:
        data=json.loads(raw)
        video=next(s for s in data["streams"] if s.get("codec_type")=="video")
        audio=next(s for s in data["streams"] if s.get("codec_type")=="audio")
        duration=float(data["format"]["duration"])
        if (not math.isfinite(duration) or
                not isinstance(max_duration, (int, float)) or
                not math.isfinite(max_duration) or
                not .7 <= max_duration <= 8 * 3600 or
                not .7<=duration<=max_duration or
                abs(duration-expected_seconds)>max(.5,expected_seconds*.1) or
                video.get("codec_name")!="h264" or
                audio.get("codec_name")!="aac" or
                (int(video["width"]),int(video["height"]))!=size or
                not Path(file).is_file() or Path(file).stat().st_size<1000):
            raise ValueError("bad media")
    except (ValueError,TypeError,KeyError,StopIteration,OverflowError) as exc:
        raise PopularEditError(
            "Техническая проверка MP4 не прошла: кодеки, длительность "
            "или формат кадра неверны.") from exc
    return {
        "quality_checked":True, "video_codec":"h264",
        "audio_codec":"aac", "width":size[0],"height":size[1],
        "duration":duration,
    }


def _copy_export_with_cancel(source, destination, *, cancel=None,
                             chunk_bytes=1024*1024):
    """Copy a verified result in bounded chunks, honor cancellation promptly."""
    if not isinstance(chunk_bytes,int) or not 4096<=chunk_bytes<=8*1024*1024:
        raise PopularEditError("Недопустимый размер буфера экспорта.")
    while True:
        if cancel is not None and cancel.is_set():
            raise PopularEditError("Экспорт отменён, частичный результат удалён.")
        piece=source.read(chunk_bytes)
        if not piece:
            return
        destination.write(piece)


def render_popular_edit(
    footage_folder: Path, out_file: Path, *,
    style: str, music_path: Path | None = None,
    cancel: threading.Event | None = None, tools=None,
    executor=None,
) -> dict:
    """Make a verified MP4 and non-destructive JSON edit decisions.

    Always requires a pre-selected output file, distinct from footage.
    Output is committed only after FFmpeg, ffprobe and sanity checks pass.
    """
    from viral_studio import ffmpeg_tools, _execute, _probe
    preset = select_style(style)
    clips = source_clips(footage_folder)
    requested_output=Path(out_file).expanduser()
    if requested_output.is_symlink():
        raise PopularEditError("Недопустимая ссылка вместо выходного MP4.")
    out = requested_output.resolve()
    source = Path(footage_folder).resolve()
    if (out.suffix.casefold() != ".mp4" or out == source
            or source in out.parents or not out.parent.is_dir()
            or out.is_symlink() or out.exists()):
        raise PopularEditError("Выбери новый MP4 вне папки с оригиналами.")
    decisions_file = out.with_name(out.stem + "_EDL.json")
    if decisions_file.is_symlink() or decisions_file.exists():
        raise PopularEditError("Монтажный лист уже существует — перезапись запрещена.")
    if cancel is not None and cancel.is_set():
        raise PopularEditError("Монтаж отменён.")
    ffmpeg, ffprobe = tools if tools else ffmpeg_tools()
    runner = executor or _execute
    opts = validate_options(ProOptions(
        transition=preset.transition_seconds,
        color=preset.color, animated_titles=False,
        music_path=music_path,
        music_volume=.18, beat_sync=False,
        semantic=False, transition_style=preset.transition))
    decisions = []
    try:
        with tempfile.TemporaryDirectory(prefix=".nova-edit-", dir=str(out.parent)) as tmp:
            work = Path(tmp)
            parts, lengths = [], []
            for idx, clip in enumerate(clips):
                if cancel is not None and cancel.is_set():
                    raise PopularEditError("Монтаж отменён.")
                original_seconds, has_audio = _probe(clip, ffprobe, cancel=cancel)
                rate = speed_for(preset, idx)
                seconds = min(preset.seconds, max(0., (original_seconds - .10) / rate))
                seconds = round(seconds, 3)
                if seconds < .75:
                    raise PopularEditError(
                        "Клип слишком короткий для выбранного эффекта: " + clip.name[:80])
                raw_seconds = round(seconds * rate, 3)
                begin = max(0., (original_seconds - raw_seconds) / 2)
                part = work / f"part_{idx:02d}.mp4"
                cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
                       "-nostdin", "-y", "-ss", f"{begin:.3f}",
                       "-t", f"{raw_seconds:.3f}", "-i", str(clip)]
                if not has_audio:
                    cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
                cmd.extend([
                    "-filter_complex", _segment_filter(
                        preset, speed=rate, seconds=seconds, has_audio=has_audio),
                    "-map", "[v]", "-map", "[a]",
                    "-t", f"{seconds:.3f}", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-b:a", "128k", str(part),
                ])
                runner(cmd, timeout=encode_timeout(seconds), cancel=cancel)
                parts.append(part)
                lengths.append(seconds)
                decisions.append({
                    "source": clip.name, "start": round(begin, 3),
                    "duration": seconds, "speed": rate,
                    "audio": "source" if has_audio else "silence",
                })
            exported = work / "finished.mp4"
            finish = finish_video(
                parts, lengths, exported, ffmpeg,
                options=opts, executor=runner, cancel=cancel,
                max_clips=MAX_CLIPS, max_duration=MAX_OUTPUT_SECONDS)
            output_duration, _ = _probe(exported, ffprobe, cancel=cancel)
            technical = verify_edit_output_media(
                exported, ffprobe, size=preset.size,
                expected_seconds=finish["expected_seconds"],
                executor=runner, cancel=cancel,
                max_duration=MAX_OUTPUT_SECONDS)
            if output_duration < .7 or exported.stat().st_size < 1000:
                raise PopularEditError("Итоговый MP4 не прошёл техническую проверку.")
            metadata = {
                "output": str(out),
                "style": preset.name, "style_label": preset.label,
                "size": list(preset.size), "duration": output_duration,
                "segments": decisions, "professional": finish,
                # Enables FilmCraft to reconstruct honest editable cuts for
                # presets without time warps or unsupported transitions.
                "source_directory": str(source),
                "technical_quality": technical,
                "music": str(music_path) if music_path else None,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "rights": "Проверь авторские права на исходники и музыку перед публикацией.",
                "published": False,
            }
            staged_json = work / "edit_decisions.json"
            staged_json.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            committed = []
            try:
                for origin, destination in ((staged_json, decisions_file),
                                            (exported, out)):
                    with destination.open("xb") as target:
                        committed.append(destination)
                        with origin.open("rb") as src:
                            _copy_export_with_cancel(src,target,cancel=cancel)
                if cancel is not None and cancel.is_set():
                    raise PopularEditError("Экспорт отменён; файлы результата удалены.")
            except Exception:
                for file in reversed(committed):
                    file.unlink(missing_ok=True)
                raise
            return metadata
    except (OSError, ValueError) as exc:
        raise PopularEditError(str(exc)[:300]) from exc
