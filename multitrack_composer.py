# -*- coding: utf-8 -*-
"""Offline, non-destructive multi-track video compositor for JARVIS NOVA.

V1: base video, up to three image/video picture-in-picture tracks, an optional
title graphic, narration and a music bed. All filter arguments are constructed
from strictly typed/range-checked values, not text or model-supplied shell.
No network calls, publishing, mutable source media or credential access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import tempfile
import threading

from popular_edits import PopularEditError, _copy_export_with_cancel, verify_edit_output_media

MAX_DURATION = 90.0
MAX_LAYER_BYTES = 3_000_000_000
IMAGE_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
VIDEO_TYPES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
AUDIO_TYPES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"})
MOTIONS = ("static", "fade-in", "fade-out", "fade-in-out", "slide-left", "slide-right", "rise", "drop")
POSITIONS = {
    "top-left": ("W*0.03", "H*0.03"),
    "top-right": ("W-w-W*0.03", "H*0.03"),
    "bottom-left": ("W*0.03", "H-h-H*0.03"),
    "bottom-right": ("W-w-W*0.03", "H-h-H*0.03"),
    "center": ("(W-w)/2", "(H-h)/2"),
}


class MultitrackError(PopularEditError):
    pass


@dataclass(frozen=True)
class VisualLayer:
    """A small static graphic or video picture-in-picture layer."""
    path: Path
    start: float = 0.0
    duration: float = 3.0
    position: str = "bottom-right"
    width_percent: int = 26
    opacity: float = 1.0
    motion: str = "static"
    motion_seconds: float = .45


@dataclass(frozen=True)
class MultitrackProject:
    base_video: Path
    output_video: Path
    layers: tuple[VisualLayer, ...] = ()
    title: str = ""
    voiceover: Path | None = None
    music: Path | None = None
    music_volume: float = 0.22
    duck_music: bool = False


def is_multitrack_request(text: str) -> bool:
    if not isinstance(text,str) or not 4 <= len(text) <= 400:
        return False
    value=" ".join(text.casefold().replace("ё","е").split())
    return any(phrase in value for phrase in (
        "многодорожечный монтаж", "многослойный монтаж",
        "наложи логотип на видео", "добавь логотип на видео",
        "наложи видео на видео", "добавь озвучку к видео",
        "добавь картинку на видео",
    ))


def _safe_media(path: Path, allowed: frozenset[str]) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink() or not raw.is_file() or raw.suffix.casefold() not in allowed:
        raise MultitrackError("Недоступный медиафайл или неподдерживаемый формат.")
    if not 100 <= raw.stat().st_size <= MAX_LAYER_BYTES:
        raise MultitrackError("Файл слишком маленький или превышает лимит 3 ГБ.")
    return raw.resolve()


def validate_project(project: MultitrackProject, *, for_export=True) -> MultitrackProject:
    if not isinstance(project, MultitrackProject):
        raise MultitrackError("Некорректный проект многодорожечного монтажа.")
    base = _safe_media(project.base_video, VIDEO_TYPES)
    raw_output = Path(project.output_video).expanduser()
    if (raw_output.is_symlink() or raw_output.suffix.lower() != ".mp4"
            or (for_export and raw_output.exists())
            or not raw_output.parent.is_dir()):
        raise MultitrackError("Нужен новый MP4, который ещё не существует.")
    out = raw_output.resolve()
    if not isinstance(project.layers, tuple) or len(project.layers) > 3:
        raise MultitrackError("Допускается максимум три верхних видеодорожки.")
    used = {base}
    for layer in project.layers:
        if not isinstance(layer, VisualLayer):
            raise MultitrackError("Неверная видеодорожка.")
        p = _safe_media(layer.path, IMAGE_TYPES | VIDEO_TYPES)
        used.add(p)
        if (not isinstance(layer.position,str)
                or layer.position not in POSITIONS or
                type(layer.width_percent) is not int or
                not 10 <= layer.width_percent <= 70 or
                not all(type(x) in (int,float) and math.isfinite(x)
                        for x in (layer.start, layer.duration, layer.opacity,
                                  layer.motion_seconds)) or
                type(layer.motion) is not str or layer.motion not in MOTIONS or
                not .15 <= layer.motion_seconds <= min(1.2,layer.duration) or
                not 0 <= layer.start < MAX_DURATION or
                not .3 <= layer.duration <= MAX_DURATION or
                not .1 <= layer.opacity <= 1.0):
            raise MultitrackError("Неверная позиция, прозрачность или время слоя.")
    for path in (project.voiceover, project.music):
        if path is not None:
            used.add(_safe_media(path, AUDIO_TYPES))
    if not isinstance(project.title, str) or len(project.title) > 120:
        raise MultitrackError("Заголовок должен быть короче 120 символов.")
    if any(ord(ch) < 32 and ch not in "\t" for ch in project.title):
        raise MultitrackError("Заголовок содержит недопустимые символы.")
    if (not isinstance(project.music_volume, (float, int))
            or isinstance(project.music_volume, bool)
            or not math.isfinite(project.music_volume)
            or not 0 <= project.music_volume <= .7):
        raise MultitrackError("Громкость музыки должна быть от 0 до 70%.")
    if type(project.duck_music) is not bool:
        raise MultitrackError("Неверная настройка приглушения музыки.")
    if project.duck_music and (project.music is None or project.voiceover is None):
        raise MultitrackError(
            "Для автоматического приглушения выбери и музыку, и озвучку.")
    if out in used:
        raise MultitrackError("Выходной файл не должен совпадать с исходниками.")
    edl = out.with_name(out.stem + "_MULTITRACK.json")
    if for_export and (edl.is_symlink() or edl.exists()):
        raise MultitrackError("Монтажный лист уже существует — перезапись запрещена.")
    return project


def save_multitrack(project: MultitrackProject, destination: Path) -> Path:
    """Write a re-editable project JSON only under a new filename."""
    validate_project(project,for_export=False)
    raw=Path(destination).expanduser()
    if (raw.is_symlink() or raw.exists() or not raw.parent.is_dir()
            or raw.suffix.casefold() != ".json"):
        raise MultitrackError("Выбери новое имя JSON; перезапись запрещена.")
    payload={
        "format":"jarvis_multitrack_edit_v1",
        "base":str(_safe_media(project.base_video,VIDEO_TYPES)),
        "output":str(Path(project.output_video).expanduser().resolve()),
        "title":project.title,
        "music":str(_safe_media(project.music,AUDIO_TYPES))
                 if project.music else None,
        "narration":str(_safe_media(project.voiceover,AUDIO_TYPES))
                    if project.voiceover else None,
        "music_volume":project.music_volume,
        "duck_music":project.duck_music,
        "layers":[{
            "file":str(_safe_media(item.path,IMAGE_TYPES|VIDEO_TYPES)),
            "start":item.start,"duration":item.duration,
            "position":item.position,"width_percent":item.width_percent,
            "opacity":item.opacity,"motion":item.motion,
            "motion_seconds":item.motion_seconds,
        } for item in project.layers],
        "published":False,
    }
    encoded=json.dumps(payload,indent=2,ensure_ascii=False)
    if len(encoded.encode("utf-8"))>80_000:
        raise MultitrackError("Монтажный лист слишком большой.")
    with raw.open("x",encoding="utf-8") as output:
        output.write(encoded+"\n")
    return raw


def load_multitrack(path: Path) -> MultitrackProject:
    """Accept only vetted local project JSON or own rendered metadata."""
    raw=Path(path).expanduser()
    if (raw.is_symlink() or not raw.is_file()
            or raw.suffix.casefold() != ".json" or
            raw.stat().st_size>80_000):
        raise MultitrackError("Недопустимый JSON-проект.")
    try:
        data=json.loads(raw.read_text(encoding="utf-8"))
        if (not isinstance(data,dict) or
                data.get("format") not in (
                    "jarvis_multitrack_edit_v1","jarvis_multitrack_v1") or
                type(data.get("layers")) is not list or
                len(data["layers"])>3):
            raise ValueError("schema")
        layers=[]
        for item in data["layers"]:
            if not isinstance(item,dict):
                raise ValueError("invalid layer")
            layers.append(VisualLayer(
                path=Path(item["file"]),start=item["start"],
                duration=item["duration"],position=item["position"],
                width_percent=item["width_percent"],opacity=item["opacity"],
                motion=item.get("motion","static"),
                motion_seconds=item.get("motion_seconds",.45)))
        music=data.get("music")
        voice=data.get("narration")
        project=MultitrackProject(
            base_video=Path(data["base"]),
            output_video=Path(data["output"]),
            layers=tuple(layers),title=data["title"],
            music=Path(music) if music is not None else None,
            voiceover=Path(voice) if voice is not None else None,
            music_volume=data["music_volume"],
            duck_music=data.get("duck_music",False),
        )
    except (KeyError,TypeError,ValueError,UnicodeError,OSError) as exc:
        raise MultitrackError("Повреждённый или неподдерживаемый проект.") from exc
    try:
        return validate_project(project,for_export=False)
    except (TypeError,ValueError,OSError) as exc:
        raise MultitrackError("Неверные параметры в JSON-проекте.") from exc


def layer_motion_xy(layer: VisualLayer) -> tuple[str, str]:
    """Validated numeric keyframes expressed as per-frame FFmpeg overlay XY."""
    if (type(layer.motion) is not str or layer.motion not in MOTIONS or
            type(layer.motion_seconds) not in (int,float) or
            not math.isfinite(layer.motion_seconds) or
            not .15 <= layer.motion_seconds <= min(1.2,layer.duration)):
        raise MultitrackError("Недопустимая анимация наложения.")
    x, y = POSITIONS[layer.position]
    if layer.motion in ("static","fade-in","fade-out","fade-in-out"):
        return x,y
    # Two linear keyframes: fully off-screen at start, at requested location
    # after motion_seconds. Escaped commas survive FFmpeg filtergraph parsing.
    t = (f"min(1\\,max(0\\,"
         f"(t-{layer.start:.3f})/{layer.motion_seconds:.3f}))")
    if layer.motion=="slide-left":
        x=f"(-w)+(({x})+w)*({t})"
    elif layer.motion=="slide-right":
        x=f"W+(({x})-W)*({t})"
    elif layer.motion=="rise":
        y=f"H+(({y})-H)*({t})"
    elif layer.motion=="drop":
        y=f"(-h)+(({y})+h)*({t})"
    return x,y


def build_filter_graph(project: MultitrackProject, *, duration: float,
                       width: int, height: int, has_base_audio: bool,
                       title_index: int | None,
                       silent_index: int | None) -> tuple[str, str, str]:
    """Return validated FFmpeg filtergraph; caller supplies inputs in order.

    Input 0 is the base, 1..N visual layers, then optional title, music,
    voiceover, and finally anullsrc if the original has no audio.
    """
    if not .7 <= duration <= MAX_DURATION:
        raise MultitrackError("Многодорожечный монтаж поддерживает 0.7–90 секунд.")
    filters = ["[0:v:0]fps=30,format=yuv420p,setpts=PTS-STARTPTS[vbase]"]
    current = "vbase"
    for n, layer in enumerate(project.layers, start=1):
        if layer.start >= duration:
            raise MultitrackError("Слой начинается после окончания ролика.")
        stop = min(duration, layer.start + layer.duration)
        target_width = max(2, int(width * layer.width_percent / 100) // 2 * 2)
        # Fades use the layer-local timeline before setpts shifts it.
        # Paired fades must not overlap when a clip is short.
        fade_seconds = (min(layer.motion_seconds, (stop-layer.start)/2)
                        if layer.motion == "fade-in-out" else layer.motion_seconds)
        effect = ""
        if layer.motion in ("fade-in", "fade-in-out"):
            effect += f"fade=t=in:st=0:d={fade_seconds:.3f}:alpha=1,"
        if layer.motion in ("fade-out", "fade-in-out"):
            fade_start = max(0.0, stop-layer.start-fade_seconds)
            effect += (f"fade=t=out:st={fade_start:.3f}:"
                       f"d={fade_seconds:.3f}:alpha=1,")
        filters.append(
            f"[{n}:v:0]fps=30,scale={target_width}:-2:flags=lanczos,"
            f"format=rgba,colorchannelmixer=aa={layer.opacity:.3f},"
            f"{effect}setpts=PTS-STARTPTS+{layer.start:.3f}/TB[layer{n}]")
        x, y = layer_motion_xy(layer)
        filters.append(
            f"[{current}][layer{n}]overlay=x='{x}':y='{y}':eval=frame:"
            f"eof_action=pass:repeatlast=0:"
            f"enable='between(t,{layer.start:.3f},{stop:.3f})'[v{n}]")
        current = f"v{n}"
    next_index = len(project.layers) + 1
    if title_index is not None:
        assert title_index == next_index
        filters.append(
            f"[{title_index}:v:0]fps=30,format=rgba,"
            "setpts=PTS-STARTPTS[titleimage]")
        title_end = min(duration, 4.0)
        filters.append(
            f"[{current}][titleimage]overlay=0:0:"
            f"eof_action=pass:repeatlast=0:"
            f"enable='between(t,0,{title_end:.3f})'[vtitle]")
        current = "vtitle"
        next_index += 1
    music_index = next_index if project.music else None
    next_index += int(project.music is not None)
    voice_index = next_index if project.voiceover else None
    if has_base_audio:
        filters.append(
            f"[0:a:0]aresample=48000,atrim=duration={duration:.3f},"
            "asetpts=PTS-STARTPTS,volume=0.8[abase]")
    else:
        if silent_index is None:
            raise MultitrackError("Для видео без звука нужна дорожка тишины.")
        filters.append(
            f"[{silent_index}:a:0]aresample=48000,"
            f"atrim=duration={duration:.3f},"
            "asetpts=PTS-STARTPTS[abase]")
    audio_inputs = ["abase"]
    if music_index is not None:
        filters.append(
            f"[{music_index}:a:0]aresample=48000,"
            f"atrim=duration={duration:.3f},"
            "asetpts=PTS-STARTPTS,"
            f"volume={float(project.music_volume):.3f}[music]")
        audio_inputs.append("music")
    if voice_index is not None:
        filters.append(
            f"[{voice_index}:a:0]aresample=48000,"
            f"atrim=duration={duration:.3f},"
            "asetpts=PTS-STARTPTS,volume=1.0[voice]")
        audio_inputs.append("voice")
    if project.duck_music and music_index is not None and voice_index is not None:
        # The voice stream is explicitly split; a FFmpeg filter output
        # cannot feed both the sidechain and the final mix without asplit.
        filters.extend([
            "[voice]asplit=2[voice_detector][voice_for_mix]",
            "[music][voice_detector]sidechaincompress="
            "threshold=0.020:ratio=5:attack=50:release=400[ducked_music]",
        ])
        audio_inputs=["abase","ducked_music","voice_for_mix"]
    if len(audio_inputs) == 1:
        final_audio = "abase"
    else:
        labels = "".join(f"[{name}]" for name in audio_inputs)
        filters.append(
            f"{labels}amix=inputs={len(audio_inputs)}:"
            "duration=first:dropout_transition=0,"
            "alimiter=limit=0.93[finalaudio]")
        final_audio = "finalaudio"
    return ";".join(filters), current, final_audio


def render_multitrack(project: MultitrackProject, *,
                      cancel: threading.Event | None = None,
                      tools=None, executor=None) -> dict:
    """Render and verify a user-confirmed, non-destructive H264/AAC MP4."""
    from viral_studio import ffmpeg_tools, _execute, _probe, _make_caption_png

    validate_project(project)
    if cancel is not None and cancel.is_set():
        raise MultitrackError("Монтаж отменён до чтения видео.")
    ffmpeg, ffprobe = tools if tools else ffmpeg_tools()
    runner = executor or _execute
    base = _safe_media(project.base_video, VIDEO_TYPES)
    duration, has_audio = _probe(base, ffprobe, cancel=cancel)
    if not .7 <= duration <= MAX_DURATION:
        raise MultitrackError("Для монтажа выбери ролик длиной от 0,7 до 90 секунд.")
    probe_data = runner([ffprobe, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "json",
                         str(base)], timeout=30, cancel=cancel)
    try:
        stream = json.loads(probe_data)["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        if not (128 <= width <= 3840 and 128 <= height <= 3840
                and width % 2 == 0 and height % 2 == 0):
            raise ValueError("dimensions")
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise MultitrackError("Не удалось проверить размер исходного видео.") from exc
    for layer in project.layers:
        if layer.start >= duration:
            raise MultitrackError("Один из слоёв начинается позже конца MP4.")
        if Path(layer.path).suffix.lower() in VIDEO_TYPES:
            _probe(_safe_media(layer.path, VIDEO_TYPES), ffprobe, cancel=cancel)
    if cancel is not None and cancel.is_set():
        raise MultitrackError("Монтаж отменён.")
    out = Path(project.output_video).expanduser().resolve()
    sidecar = out.with_name(out.stem + "_MULTITRACK.json")
    with tempfile.TemporaryDirectory(prefix=".nova-multitrack-", dir=str(out.parent)) as tmp:
        work = Path(tmp)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error",
                   "-nostdin", "-y", "-i", str(base)]
        for layer in project.layers:
            source = _safe_media(layer.path, IMAGE_TYPES | VIDEO_TYPES)
            if source.suffix.lower() in IMAGE_TYPES:
                command += ["-loop", "1", "-framerate", "30",
                            "-t", f"{min(duration,layer.duration):.3f}",
                            "-i", str(source)]
            else:
                command += ["-i", str(source)]
        title_index = None
        if project.title.strip():
            title_index = len(project.layers) + 1
            picture = work / "title.png"
            _make_caption_png(project.title.strip(), picture, width, height)
            command += ["-loop", "1", "-framerate", "30",
                        "-t", f"{min(duration,4.0):.3f}", "-i", str(picture)]
        if project.music is not None:
            music = _safe_media(project.music, AUDIO_TYPES)
            command += ["-stream_loop", "-1", "-i", str(music)]
        if project.voiceover is not None:
            command += ["-i", str(_safe_media(project.voiceover, AUDIO_TYPES))]
        silent_index = None
        if not has_audio:
            silent_index = (1 + len(project.layers) +
                            int(title_index is not None) +
                            int(project.music is not None) +
                            int(project.voiceover is not None))
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph, vlabel, alabel = build_filter_graph(
            project, duration=duration, width=width, height=height,
            has_base_audio=has_audio, title_index=title_index,
            silent_index=silent_index)
        export = work / "composite.mp4"
        command += [
            "-filter_complex", graph, "-map", f"[{vlabel}]",
            "-map", f"[{alabel}]", "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(export),
        ]
        runner(command, timeout=900, cancel=cancel)
        technical = verify_edit_output_media(
            export, ffprobe, size=(width, height),
            expected_seconds=duration, executor=runner, cancel=cancel)
        metadata = {
            "format": "jarvis_multitrack_v1",
            "base": str(base),
            "output": str(out),
            "layers": [
                {"file": str(_safe_media(l.path, IMAGE_TYPES|VIDEO_TYPES)),
                 "start": l.start, "duration": l.duration,
                 "position": l.position, "width_percent": l.width_percent,
                 "opacity": l.opacity, "motion": l.motion,
                 "motion_seconds": l.motion_seconds} for l in project.layers
            ],
            "title": project.title,
            "music": str(project.music) if project.music is not None else None,
            "narration": str(project.voiceover) if project.voiceover is not None else None,
            "music_volume": float(project.music_volume),
            "duck_music": project.duck_music,
            "technical_quality": technical,
            "duration": duration,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "published": False,
            "rights": "Проверь права на видео, картинки и звук перед публикацией.",
        }
        plan = work / "multitrack.json"
        plan.write_text(json.dumps(metadata, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        committed = []
        try:
            # Exclusive output creation protects existing user work.
            for staged, destination in ((plan, sidecar), (export, out)):
                with destination.open("xb") as target:
                    committed.append(destination)
                    with staged.open("rb") as source:
                        _copy_export_with_cancel(source, target, cancel=cancel)
            if cancel is not None and cancel.is_set():
                raise MultitrackError("Монтаж отменён.")
        except Exception:
            for name in reversed(committed):
                name.unlink(missing_ok=True)
            raise
        return metadata
