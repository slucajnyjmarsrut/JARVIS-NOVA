# -*- coding: utf-8 -*-
"""Offline editable video timeline: trim, reorder, speed, color, titles, audio.

This is a project format and a real FFmpeg renderer, not AI-generated shell.
Files are never overwritten, uploaded or modified. Export is consent-gated by UI.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import tempfile
import threading

from popular_edits import (
    _copy_export_with_cancel, _segment_filter, select_style,
    verify_edit_output_media, VIDEO_EXTENSIONS, PopularEditError,
)
from pro_montage import (
    ProOptions, SAFE_TRANSITIONS, color_filter, finish_video, validate_options,
)

from long_video_limits import (
    MAX_SOURCE_SECONDS, MAX_OUTPUT_SECONDS, MAX_INPUT_BYTES,
    MAX_TIMELINE_CUTS, encode_timeout,
)

MAX_CUTS = MAX_TIMELINE_CUTS
MAX_TOTAL = float(MAX_OUTPUT_SECONDS)
MAX_PROJECT_BYTES = 1_000_000
ASPECTS = {
    "Shorts / Reels / TikTok 9:16": (720, 1280),
    "YouTube / Gaming 16:9": (1280, 720),
    "Square 1:1": (960, 960),
    "Feed 4:5": (864, 1080),
}
COLORS = (
    "natural", "none", "cinematic", "vibrant", "noir", "warm",
    "cool", "retro", "dreamy", "highcontrast",
)


class TimelineError(PopularEditError):
    pass


@dataclass(frozen=True)
class TimelineCut:
    path: Path
    source_start: float = 0.0
    duration: float = 2.0  # seconds in finished film (not source seconds)
    speed: float = 1.0
    caption: str = ""


@dataclass(frozen=True)
class TimelineProject:
    cuts: tuple[TimelineCut, ...]
    output: Path
    aspect: str = "Shorts / Reels / TikTok 9:16"
    color: str = "natural"
    transition: str = "fade"
    transition_seconds: float = .17
    music: Path | None = None
    music_volume: float = .18
    subtitles: Path | None = None


def _finite(value, low, high):
    return (type(value) in (float, int) and math.isfinite(value)
            and low <= value <= high)


def is_timeline_request(text: str) -> bool:
    """Only explicit montage intent opens the editor; it never renders."""
    if not isinstance(text, str) or not 4 <= len(text) <= 400:
        return False
    value=" ".join(text.casefold().replace("ё","е").split())
    return any(phrase in value for phrase in (
        "открой таймлайн", "покажи таймлайн", "монтаж по таймлайну",
        "редактор таймлайна", "обрежь и склей видео", "разрежь видео",
        "соедини клипы в видео", "редактируй видео по кадрам",
    ))


def _input_video(path):
    file = Path(path).expanduser()
    if (file.is_symlink() or not file.is_file() or
            file.suffix.casefold() not in VIDEO_EXTENSIONS or
            not 2_000 <= file.stat().st_size <= MAX_INPUT_BYTES):
        raise TimelineError("Нужен локальный видеофайл; проверь формат и доступный объём диска.")
    return file.resolve()


def validate_timeline(project: TimelineProject, *, for_export=True):
    if not isinstance(project, TimelineProject):
        raise TimelineError("Неверный формат таймлайна.")
    if (type(project.cuts) is not tuple or
            not 1 <= len(project.cuts) <= MAX_CUTS):
        raise TimelineError(f"На таймлайне должно быть от 1 до {MAX_CUTS} фрагментов.")
    if (not isinstance(project.aspect,str)
            or not isinstance(project.color,str)
            or project.aspect not in ASPECTS or project.color not in COLORS):
        raise TimelineError("Недопустимый формат кадра или цвет.")
    if not isinstance(project.transition,str) or project.transition not in SAFE_TRANSITIONS:
        raise TimelineError("Неизвестный переход между клипами.")
    if not _finite(project.transition_seconds, 0, .45):
        raise TimelineError("Длительность перехода должна быть 0–0,45 секунды.")
    total = 0.
    inputs = set()
    for cut in project.cuts:
        if not isinstance(cut, TimelineCut):
            raise TimelineError("Неверный элемент таймлайна.")
        inputs.add(_input_video(cut.path))
        if not (_finite(cut.source_start, 0, MAX_SOURCE_SECONDS)
                and _finite(cut.duration, .75, MAX_TOTAL)
                and _finite(cut.speed, .5, 2.)):
            raise TimelineError("Проверь начало и длительность фрагмента, скорость 0.5–2.0.")
        if (not isinstance(cut.caption, str) or len(cut.caption) > 110
                or any(ord(x) < 32 for x in cut.caption)):
            raise TimelineError("Титр не должен содержать управляющие символы.")
        total += cut.duration
    if total > MAX_TOTAL:
        raise TimelineError("Монтаж превышает предел ресурсоёмкой обработки (8 часов).")
    overlap = (min(project.transition_seconds,
                   max(0.,min(c.duration for c in project.cuts)-.705))
               if len(project.cuts)>1 else 0.)
    predicted_duration = total - overlap*(len(project.cuts)-1)
    try:
        validate_options(ProOptions(
            transition=project.transition_seconds,
            color=project.color, animated_titles=False,
            beat_sync=False, semantic=False,
            music_path=project.music, music_volume=project.music_volume,
            transition_style=project.transition))
    except (ValueError, TypeError, OSError) as exc:
        raise TimelineError("Недопустимые параметры музыки или переходов.") from exc
    if project.music is not None:
        inputs.add(Path(project.music).expanduser().resolve())
    if project.subtitles is not None:
        from subtitle_tracks import load_srt, SubtitleError
        try:
            # Reject captions past the actual cut *before* rendering
            # every clip. A tiny tolerance covers FFmpeg frame rounding.
            load_srt(project.subtitles,
                     max_time=predicted_duration+.04)
        except (SubtitleError,ValueError,OSError,TypeError) as exc:
            raise TimelineError("Недопустимый SRT: проверь время и текст субтитров.") from exc
        inputs.add(Path(project.subtitles).expanduser().resolve())
    raw = Path(project.output).expanduser()
    if raw.suffix.casefold() != ".mp4" or raw.is_symlink():
        raise TimelineError("Выходной файл должен быть обычным MP4.")
    out = raw.resolve()
    if out in inputs:
        raise TimelineError("Нельзя сохранить видео вместо исходного файла.")
    if not out.parent.is_dir():
        raise TimelineError("Выходная папка не существует.")
    sidecar = out.with_name(out.stem + "_TIMELINE.json")
    if for_export and (raw.exists() or out.exists() or
                       sidecar.exists() or sidecar.is_symlink()):
        raise TimelineError("MP4 или монтажный лист уже существует: перезапись запрещена.")
    return project


def estimate_seconds(project: TimelineProject):
    validate_timeline(project, for_export=False)
    overlapping = min(
        project.transition_seconds,
        max(0., min(c.duration for c in project.cuts)-.705),
    ) if len(project.cuts) > 1 else 0.
    return round(sum(c.duration for c in project.cuts) -
                 overlapping*(len(project.cuts)-1), 3)


def _format_snapshot(project: TimelineProject):
    return {
        "schema": "jarvis_timeline_v1",
        "aspect": project.aspect, "color": project.color,
        "transition": project.transition,
        "transition_seconds": project.transition_seconds,
        "output": str(Path(project.output).expanduser().resolve()),
        "music": str(Path(project.music).expanduser().resolve()) if project.music else None,
        "music_volume": project.music_volume,
        "subtitles": str(Path(project.subtitles).expanduser().resolve())
                     if project.subtitles else None,
        "cuts": [
            {"path": str(_input_video(c.path)), "source_start": c.source_start,
             "duration": c.duration, "speed": c.speed, "caption": c.caption}
            for c in project.cuts],
    }


def save_timeline(project: TimelineProject, destination: Path):
    """Save an editable, strictly typed JSON project; never overwrite another."""
    validate_timeline(project, for_export=False)
    raw = Path(destination).expanduser()
    if (raw.suffix.casefold() != ".json" or raw.is_symlink()
            or raw.exists() or not raw.parent.is_dir()):
        raise TimelineError("Выбери новое имя JSON без перезаписи.")
    payload = json.dumps(_format_snapshot(project), indent=2, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise TimelineError("Проект слишком большой.")
    with raw.open("x", encoding="utf-8") as output:
        output.write(payload + "\n")
    return raw


def load_timeline(path: Path):
    """Open only small, locally stored, strict v1 projects. Never run JSON."""
    raw = Path(path).expanduser()
    if (raw.is_symlink() or not raw.is_file() or
            raw.suffix.lower() != ".json" or
            raw.stat().st_size > MAX_PROJECT_BYTES):
        raise TimelineError("Недопустимый файл таймлайна.")
    try:
        data = json.loads(raw.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or
                data.get("schema") != "jarvis_timeline_v1" or
                not isinstance(data.get("cuts"), list) or
                len(data["cuts"]) > MAX_CUTS):
            raise ValueError("schema")
        cuts=[]
        for row in data["cuts"]:
            if not isinstance(row, dict):
                raise ValueError("cut")
            cuts.append(TimelineCut(
                Path(row["path"]), row["source_start"],
                row["duration"], row["speed"], row["caption"]))
        music = data.get("music")
        subtitles = data.get("subtitles")
        project = TimelineProject(
            cuts=tuple(cuts), output=Path(data["output"]),
            aspect=data["aspect"], color=data["color"],
            transition=data["transition"],
            transition_seconds=data["transition_seconds"],
            music=Path(music) if music is not None else None,
            music_volume=data["music_volume"],
            subtitles=Path(subtitles) if subtitles is not None else None)
    except (KeyError, TypeError, ValueError, UnicodeError, OSError) as exc:
        raise TimelineError("Некорректный или неподдерживаемый файл таймлайна.") from exc
    return validate_timeline(project, for_export=False)


class TimelineHistory:
    """Bounded, immutable undo/redo for edits. Does not write to disk."""
    def __init__(self, *, limit=30):
        self.limit = max(2, min(int(limit), 50))
        self._past = []
        self._future = []

    def push(self, state: tuple[TimelineCut, ...]):
        if type(state) is not tuple:
            raise TimelineError("История принимает только снимок списка клипов.")
        self._past.append(state)
        self._past = self._past[-self.limit:]
        self._future.clear()

    def undo(self, current):
        if not self._past:
            return current
        self._future.append(current)
        return self._past.pop()

    def redo(self, current):
        if not self._future:
            return current
        self._past.append(current)
        return self._future.pop()


def _segment_graph(aspect, color, speed, seconds, has_audio, *, caption_index=None):
    style = replace(select_style("shorts"), size=ASPECTS[aspect], color=color)
    graph = _segment_filter(
        style, speed=speed, seconds=seconds, has_audio=has_audio)
    if caption_index is None:
        return graph
    # _segment_filter is a local constant (never untrusted text).
    old = "format=yuv420p[v];"
    if old not in graph:
        raise TimelineError("Не удалось наложить титр на клип.")
    graph = graph.replace(old, "format=yuv420p[vsource];", 1)
    alpha = min(.2, seconds / 6)
    tail = (
        f";[{caption_index}:v:0]format=rgba,"
        f"fade=t=in:st=0:d={alpha:.3f}:alpha=1,"
        f"fade=t=out:st={max(0.,seconds-alpha):.3f}:d={alpha:.3f}:alpha=1[cap];"
        f"[vsource][cap]overlay=0:0:eof_action=pass:repeatlast=0,"
        f"format=yuv420p[v]"
    )
    return graph + tail


def render_timeline(project: TimelineProject, *, cancel: threading.Event | None = None,
                    tools=None, executor=None, progress=None):
    """Render and independently verify MP4 before exclusive final write."""
    from viral_studio import ffmpeg_tools, _execute, _probe, _make_caption_png
    validate_timeline(project)
    if cancel is not None and cancel.is_set():
        raise TimelineError("Монтаж отменён до чтения видео.")
    ffmpeg, ffprobe = tools if tools else ffmpeg_tools()
    runner = executor or _execute
    out = Path(project.output).expanduser().resolve()
    sidecar = out.with_name(out.stem+"_TIMELINE.json")
    with tempfile.TemporaryDirectory(prefix=".nova-timeline-", dir=str(out.parent)) as tmp:
        work = Path(tmp)
        parts, lengths, decisions = [], [], []
        width, height = ASPECTS[project.aspect]
        for idx, cut in enumerate(project.cuts):
            if cancel is not None and cancel.is_set():
                raise TimelineError("Монтаж отменён.")
            source = _input_video(cut.path)
            source_length, has_audio = _probe(source, ffprobe, cancel=cancel)
            needed = cut.duration * cut.speed
            if cut.source_start + needed > source_length + .025:
                raise TimelineError(
                    "Клип слишком короткий для указанного начала, длины и скорости: "
                    + source.name[:80])
            caption_index = None
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
                   "-nostdin", "-y", "-ss", f"{cut.source_start:.3f}",
                   "-t", f"{needed:.3f}", "-i", str(source)]
            if not has_audio:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            if cut.caption.strip():
                picture = work / f"title_{idx:02d}.png"
                _make_caption_png(cut.caption, picture, width, height)
                caption_index = 1 + int(not has_audio)
                cmd += ["-loop", "1", "-framerate", "30",
                        "-t", f"{cut.duration:.3f}", "-i", str(picture)]
            part = work / f"part_{idx:02d}.mp4"
            graph = _segment_graph(
                project.aspect, project.color, cut.speed,
                cut.duration, has_audio, caption_index=caption_index)
            cmd += [
                "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                "-t", f"{cut.duration:.3f}", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-b:a", "128k", str(part),
            ]
            runner(cmd, timeout=encode_timeout(cut.duration), cancel=cancel)
            parts.append(part)
            lengths.append(cut.duration)
            decisions.append({
                "source": str(source), "start": cut.source_start,
                "duration": cut.duration, "speed": cut.speed,
                "caption": cut.caption, "audio": "original" if has_audio else "silence",
            })
            if progress:
                progress(idx+1, len(project.cuts), "Монтирую исходные фрагменты")
        if cancel is not None and cancel.is_set():
            raise TimelineError("Монтаж отменён.")
        options = validate_options(ProOptions(
            transition=project.transition_seconds, color=project.color,
            animated_titles=False, music_path=project.music,
            music_volume=project.music_volume, beat_sync=False,
            semantic=False, transition_style=project.transition))
        staged = work / "finished.mp4"
        finish = finish_video(parts, lengths, staged, ffmpeg, options=options,
                              executor=runner, cancel=cancel,
                              max_clips=MAX_CUTS, max_duration=MAX_TOTAL)
        cues = ()
        if project.subtitles is not None:
            from subtitle_tracks import load_srt, burn_subtitles
            cues = load_srt(
                project.subtitles, max_time=finish["expected_seconds"]+.03)
            captioned = work / "subtitled.mp4"
            burn_subtitles(
                staged, captioned, cues,
                ffmpeg=ffmpeg, width=width, height=height,
                seconds=finish["expected_seconds"], executor=runner,
                cancel=cancel, max_duration=MAX_TOTAL)
            staged = captioned
        if progress:
            progress(len(parts), len(parts), "Проверяю готовое MP4")
        technical = verify_edit_output_media(
            staged, ffprobe, size=(width, height),
            expected_seconds=finish["expected_seconds"],
            executor=runner, cancel=cancel, max_duration=MAX_TOTAL)
        metadata = _format_snapshot(project)
        metadata.update({
            "output": str(out), "duration": technical["duration"],
            "technical_quality": technical, "render_info": finish,
            "render_decisions": decisions,
            "subtitle_cues": len(cues),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "published": False,
        })
        temp_json = work / "timeline.json"
        temp_json.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        committed = []
        try:
            for staged_file, destination in (
                    (temp_json, sidecar), (staged, out)):
                with destination.open("xb") as dest:
                    committed.append(destination)
                    with staged_file.open("rb") as src:
                        _copy_export_with_cancel(src, dest, cancel=cancel)
            if cancel is not None and cancel.is_set():
                raise TimelineError("Монтаж отменён. Частичные файлы удалены.")
        except Exception:
            for path in reversed(committed):
                path.unlink(missing_ok=True)
            raise
        if progress:
            progress(len(parts), len(parts), "Готово")
        return metadata


def draft_longform_cuts(sources, *, target_seconds=900.0):
    """Create a reviewable 15-minute-first timeline from hour-long footage.

    The drafts sample the entire duration evenly rather than pretending to
    identify semantic highlights. Each FFmpeg render seeks straight into the
    source file: full two-hour files are not decoded into RAM.
    """
    if not isinstance(sources,(tuple,list)) or not 1 <= len(sources) <= MAX_CUTS:
        raise TimelineError("Выбери от одного до 64 длинных исходников.")
    if not _finite(target_seconds, .75, MAX_TOTAL):
        raise TimelineError("Длина итогового ролика должна быть положительной.")
    checked=[]
    for item in sources:
        if not isinstance(item,(tuple,list)) or len(item)!=2:
            raise TimelineError("Неверное описание исходника.")
        path,length=item
        if not _finite(length,.75,MAX_SOURCE_SECONDS):
            raise TimelineError("Не удалось определить длительность исходника.")
        checked.append((_input_video(path),float(length)))
    duration_total=sum(x[1] for x in checked)
    if duration_total+.01 < target_seconds:
        raise TimelineError("Общая длительность исходников меньше запрошенного ролика.")
    # The number of pieces depends on the final video, not source length.
    count=max(len(checked),min(MAX_CUTS,max(12,math.ceil(target_seconds/38))))
    counts=[1]*len(checked)
    for _ in range(count-len(checked)):
        j=max(range(len(checked)),key=lambda k:checked[k][1]/counts[k])
        counts[j]+=1
    plans=[]
    for (path,source_seconds),n in zip(checked,counts):
        budget=target_seconds*source_seconds/duration_total
        chunk=budget/n
        if chunk<.75:
            raise TimelineError("Фрагменты слишком короткие; уменьши число исходников.")
        spacing=source_seconds/n
        for pos in range(n):
            start=max(0.,min(source_seconds-chunk,
                             (pos+.5)*spacing-chunk/2))
            plans.append(TimelineCut(
                path,source_start=round(start,3),
                duration=round(chunk,3),speed=1.0))
    # Minimize rounding drift so 900 seconds means 900 seconds.
    drift=round(target_seconds-sum(c.duration for c in plans),3)
    if abs(drift)>.001:
        last=plans[-1]
        plans[-1]=replace(last,duration=round(last.duration+drift,3))
    return tuple(plans)
