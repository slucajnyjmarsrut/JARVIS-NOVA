# -*- coding: utf-8 -*-
"""Open FilmCraft for manual editing after JARVIS NOVA auto montage.

FilmCraft is installed separately by the user. No downloading, shell commands,
remote APIs, overwriting source footage or modification of a FilmCraft project.
When its documented CLI is installed we convert JARVIS's EDL to an editable
OpenTimelineIO sequence, import it into a NEW native .fcproj and open that
project. If native project creation fails, open the rendered MP4 instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import shutil
import subprocess
import tempfile
import sys

FILMCRAFT_DOWNLOAD = "https://getfilmcraft.org/download"
RATE = 30.0
MAX_EDL_SIZE = 200_000


class FilmCraftError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilmCraftHandoff:
    mode: str
    opened: Path | None
    project: Path | None
    timeline: Path | None
    source_count: int
    detail: str


def _candidate(path, executable="filmcraft.exe"):
    if not path:
        return None
    try:
        item = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
        if (item.name.casefold() == executable.casefold()
                and item.is_file() and not item.is_symlink()):
            return item
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def find_filmcraft(preferred=None):
    """Prefer a user-selected installation, then known Windows install paths."""
    if preferred:
        exe = _candidate(preferred)
        if exe:
            return exe
        raise FilmCraftError("Выбранный файл — не установленный filmcraft.exe")
    local = os.environ.get("LOCALAPPDATA", "")
    from filmcraft_installer import installed_executable
    portable = installed_executable()
    locations = [str(portable) if portable else "",
                 os.environ.get("JARVIS_FILMCRAFT_EXE", ""),
                 shutil.which("filmcraft.exe") or ""]
    if local:
        locations.append(str(Path(local) / "Programs" / "ArtCraft" /
                             "FilmCraft" / "filmcraft.exe"))
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key, "")
        if base:
            locations.append(str(Path(base) / "ArtCraft" / "FilmCraft" /
                                 "filmcraft.exe"))
    for name in locations:
        hit = _candidate(name)
        if hit:
            return hit
    raise FilmCraftError(
        "FilmCraft не установлен. Скачай его с официального сайта "
        + FILMCRAFT_DOWNLOAD +
        " или выбери вручную файл filmcraft.exe.")


def _cli_for(exe):
    """Use only the FilmCraft CLI installed beside this desktop executable."""
    return _candidate(Path(exe).with_name("filmcraft-cli.exe"),
                      executable="filmcraft-cli.exe")


def _media(path):
    if path is None:
        return None
    video = Path(path).expanduser().resolve()
    if (video.suffix.casefold() != ".mp4" or not video.is_file()
            or video.is_symlink() or video.stat().st_size < 1000):
        raise FilmCraftError("Нужен существующий MP4 JARVIS NOVA")
    return video


def _rt(seconds):
    return {"OTIO_SCHEMA": "RationalTime.1",
            "value": round(float(seconds) * RATE, 5), "rate": RATE}


def _range(start, duration):
    return {"OTIO_SCHEMA": "TimeRange.1",
            "start_time": _rt(start), "duration": _rt(duration)}


def _clip(path, start, duration):
    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": Path(path).name,
        "source_range": _range(start, duration),
        "media_references": {
            "DEFAULT_MEDIA": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "target_url": Path(path).resolve().as_uri(),
                "available_range": None,
            }
        },
        "active_media_reference_key": "DEFAULT_MEDIA",
        "enabled": True,
        "effects": [],
        "markers": [],
    }


def _safe_edl(meta, movie):
    """Accept only existing local source clips matching JARVIS EDL names."""
    if not isinstance(meta, dict):
        return []
    if meta.get("schema") == "jarvis_timeline_v1":
        # Timeline uses exact local paths and may draw timed SRT or velocity.
        # FilmCraft's OTIO importer does not reconstruct burned captions,
        # time warps or advanced wipe effects. Keep the mastered MP4 instead.
        if meta.get("subtitles"):
            return []
        effect=meta.get("render_info", {})
        if not isinstance(effect,dict):
            return []
        if effect.get("transition") not in ("fade","dissolve","none"):
            return []
        cuts=meta.get("cuts")
        if not isinstance(cuts,list) or not 1<=len(cuts)<=10:
            return []
        result=[]
        try:
            for row in cuts:
                if not isinstance(row,dict):
                    return []
                raw=Path(row["path"]).expanduser()
                if raw.is_symlink() or not raw.is_file():
                    return []
                source=raw.resolve(strict=True)
                start=float(row["source_start"])
                seconds=float(row["duration"])
                speed=float(row["speed"])
                caption=row.get("caption","")
                if (not math.isfinite(start) or start<0 or
                        not math.isfinite(seconds) or not .7<=seconds<=15 or
                        not math.isfinite(speed) or abs(speed-1.)>.0001 or
                        not isinstance(caption,str)):
                    return []
                result.append((source,start,seconds,caption[:100]))
        except (KeyError,OSError,TypeError,ValueError,RuntimeError):
            return []
        return result
    directory = meta.get("source_directory")
    parts = meta.get("segments")
    popular = isinstance(meta.get("style"),str)
    if not isinstance(directory, str) or not isinstance(parts, list):
        return []
    if not 1 <= len(parts) <= 30:
        return []
    if popular:
        # Only reconstruct precise source cuts. FilmCraft's limited OTIO
        # importer cannot reproduce velocity changes or wipe/slide effects.
        # Such presets retain a single editable rendered-MP4 reference.
        professional = meta.get("professional", {})
        if not isinstance(professional,dict):
            return []
        if professional.get("transition") not in ("fade","dissolve","none"):
            return []
    try:
        root = Path(directory).expanduser().resolve(strict=True)
        if not root.is_dir():
            return []
        rows = []
        for item in parts:
            if not isinstance(item, dict):
                return []
            name = item.get("source") if popular else item.get("file")
            if (not isinstance(name, str) or not 1 <= len(name) <= 200
                    or name in (".", "..") or "/" in name or "\\" in name):
                return []
            if popular:
                speed=float(item.get("speed",1))
                if not math.isfinite(speed) or abs(speed-1.0)>.0001:
                    return []
            offset = float(item.get("start"))
            seconds = float(item.get("duration") if popular else item.get("seconds"))
            if (not math.isfinite(offset) or not math.isfinite(seconds)
                    or offset < 0 or not .7 <= seconds <= 15):
                return []
            source = root / name
            if (source.is_symlink() or not source.is_file()
                    or source.resolve().parent != root):
                return []
            caption = item.get("on_screen", "")
            if not isinstance(caption, str):
                caption = ""
            rows.append((source, offset, seconds, caption[:100]))
        return rows
    except (OSError, ValueError, TypeError, RuntimeError):
        return []


def _read_metadata(movie, metadata):
    if isinstance(metadata, dict):
        return metadata
    # Accept our reviewed sidecars; no arbitrary paths from an untrusted
    # movie or remote site. All files stay beside the user's rendered MP4.
    for suffix in ("_EDL.json","_TIMELINE.json","_MULTITRACK.json"):
        edl = movie.with_name(movie.stem + suffix)
        try:
            if (not edl.is_file() or edl.is_symlink() or
                    edl.stat().st_size > MAX_EDL_SIZE):
                continue
            data = json.loads(edl.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, UnicodeError, ValueError):
            continue
    return {}


def build_filmcraft_timeline(movie, metadata=None):
    """Return verified OTIO JSON with editable cuts and an aligned audio track.

    The audio track references the completed movie, preserving its music mix.
    Source color grades, overlays and other effects from FFmpeg are not
    reconstructed in OTIO; they remain visible in the completed reference MP4.
    """
    movie = _media(movie)
    meta = _read_metadata(movie, metadata)
    rows = _safe_edl(meta, movie)
    if not rows:
        # Even without sources the finalized clip is still manually trimmable.
        duration = meta.get("duration", 0)
        try:
            duration = float(duration)
        except (TypeError, ValueError, OverflowError):
            duration = 0
        if not math.isfinite(duration) or not .7 <= duration <= 95:
            duration = 5.0
        rows = [(movie, 0.0, duration, "Готовый монтаж JARVIS")]
        originals = 0
    else:
        originals = len(rows)
    pro = meta.get("professional") if isinstance(meta.get("professional"), dict) else {}
    if meta.get("schema") == "jarvis_timeline_v1":
        pro=meta.get("render_info") if isinstance(meta.get("render_info"),dict) else {}
    fade = pro.get("transition_seconds", 0)
    try:
        fade = float(fade)
    except (TypeError, ValueError):
        fade = 0
    if not math.isfinite(fade) or not 0 <= fade <= .45:
        fade = 0
    children, markers = [], []
    position = 0.0
    for index, (source, source_in, length, caption) in enumerate(rows):
        if index and fade:
            # FilmCraft supports OTIO Transition.1. Convert the edge
            # crossfade to editable native transition handles.
            half = fade / 2.0
            children.append({
                "OTIO_SCHEMA": "Transition.1",
                "name": "JARVIS crossfade",
                "transition_type": "SMPTE_Dissolve",
                "in_offset": _rt(half), "out_offset": _rt(half),
            })
        children.append(_clip(source, source_in, length))
        if caption:
            markers.append({
                "OTIO_SCHEMA": "Marker.2",
                "name": "Титр JARVIS",
                "comment": caption,
                "color": "BLUE",
                "marked_range": _range(position, 0),
            })
        position += length - (fade if index else 0.0)
    # Reuse the mastered sound bed as independent, editable audio.
    # Even if the video comes from original sources, its audio track has
    # the music/normalization of the finished JARVIS export.
    audio = _clip(movie, 0, max(.7, round(position, 3)))
    def track(name, kind, clips):
        return {"OTIO_SCHEMA": "Track.1",
                "name": name, "kind": kind, "children": clips,
                "source_range": None, "effects": [], "markers": [],
                "enabled": True}
    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": "JARVIS NOVA — editable cut",
        "global_start_time": _rt(0),
        "metadata": {},
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "JARVIS Tracks",
            "children": [track("V1", "Video", children),
                         track("A1", "Audio", [audio])],
            "markers": markers,
        },
    }
    return timeline, originals


def _unique_paths(movie):
    """Never overwrite an earlier FilmCraft handoff or user's edits."""
    for i in range(1, 101):
        suffix = "" if i == 1 else "_" + str(i)
        base = movie.parent / (movie.stem + "_FILMCRAFT" + suffix)
        otio, native = base.with_suffix(".otio"), base.with_suffix(".fcproj")
        if not otio.exists() and not native.exists():
            return otio, native
    raise FilmCraftError("В папке слишком много готовых проектов FilmCraft")


def _run_cli(cli, native, timeline, *, runner=None):
    runner = runner or subprocess.run
    # import recognizes .otio and makes a native editable project.
    command = [str(cli), "--save-as", str(native), "import", str(timeline)]
    outcome = runner(command, shell=False, capture_output=True,
                     text=True, errors="replace", timeout=120)
    if outcome.returncode != 0:
        return False
    try:
        if not native.is_file() or native.is_symlink() or not 20 < native.stat().st_size < 30_000_000:
            return False
        with native.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return isinstance(data, dict) and data.get("format") == "filmcraft.project"
    except (OSError, ValueError, UnicodeError, TypeError):
        return False


def open_in_filmcraft(exe, movie=None, *, metadata=None, runner=None, launcher=None):
    """Launch FilmCraft once, with native project when CLI conversion works.

    Must be called from a background worker if movie conversion is requested.
    This never runs a command from a model. No network or destructive flags.
    """
    executable = find_filmcraft(exe)
    launch = launcher or subprocess.Popen
    video = _media(movie) if movie is not None else None
    project = otio = None
    mode = "empty"
    originals = 0
    detail = "FilmCraft открыт. Теперь можешь монтировать вручную."
    open_target = None
    if video is not None:
        mode = "video"
        open_target = video
        detail = ("FilmCraft импортирует готовый MP4. "
                  "Для отдельного редактирования исходных склеек "
                  "используй сохранённый OTIO-проект.")
        try:
            timeline, originals = build_filmcraft_timeline(video, metadata)
            otio, candidate = _unique_paths(video)
            with otio.open("x", encoding="utf-8") as stream:
                json.dump(timeline, stream, ensure_ascii=False, indent=2)
            cli = _cli_for(executable)
            if cli is not None:
                try:
                    # FilmCraft may overwrite an existing --save-as file.
                    # Build in a PRIVATE temporary directory and publish the
                    # result with exclusive 'xb', never touching user's edits.
                    with tempfile.TemporaryDirectory(
                            prefix="jarvis_filmcraft_",
                            dir=str(video.parent)) as workspace:
                        staged = Path(workspace) / candidate.name
                        if _run_cli(cli, staged, otio, runner=runner):
                            with staged.open("rb") as source, candidate.open("xb") as dest:
                                shutil.copyfileobj(source, dest, length=1024 * 1024)
                            project = candidate
                            open_target = candidate
                            mode = "project"
                            detail = (
                                "Открыт редактируемый проект FilmCraft. "
                                "Исходные склейки — на V1, сведение звука — на A1. "
                                "Титры и некоторые эффекты из готового MP4 "
                                "можно настроить вручную.")
                except (OSError, ValueError, subprocess.SubprocessError):
                    # No generated project may replace an existing user file.
                    # A failed conversion leaves only the reusable OTIO file.
                    if mode != "project":
                        project = None
            if mode != "project":
                detail += " Для исходных кадров: FilmCraft → Файл → Импорт → " + str(otio)
        except (OSError, FilmCraftError, ValueError):
            # Failure to build sidecars must never block manual editing.
            project = None
            mode = "video"
            detail = "Открыт готовый MP4 без исходной монтажной шкалы."
    args = [str(executable)]
    if open_target is not None:
        args.append(str(open_target))
    try:
        launch(args, shell=False, cwd=str(executable.parent), close_fds=True)
    except (OSError, ValueError) as exc:
        raise FilmCraftError("Не удалось запустить FilmCraft: " +
                             type(exc).__name__) from exc
    return FilmCraftHandoff(mode, open_target, project, otio, originals, detail)
