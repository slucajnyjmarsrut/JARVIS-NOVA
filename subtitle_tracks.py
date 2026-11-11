# -*- coding: utf-8 -*-
"""User-written SRT captions burned locally without FFmpeg libass dependency.

No transcription, external fonts, shell commands, URL fetch, or video upload.
Only bounded UTF-8 SRT files are accepted; text becomes a Pillow bitmap.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
import tempfile
import threading

MAX_SRT_BYTES = 80_000
MAX_CUES = 24
TIMECODE = re.compile(
    r"^(\d{2}):([0-5]\d):([0-5]\d)[,.](\d{3})\s*-->\s*"
    r"(\d{2}):([0-5]\d):([0-5]\d)[,.](\d{3})$")


class SubtitleError(ValueError):
    pass


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def _timestamp(h, m, s, ms):
    return int(h)*3600+int(m)*60+int(s)+int(ms)/1000.


def parse_srt(text: str, *, max_time=90.):
    if not isinstance(text,str) or len(text.encode("utf-8")) > MAX_SRT_BYTES:
        raise SubtitleError("Субтитры должны быть UTF-8 и короче 80 КБ.")
    blocks=re.split(r"\n\s*\n",text.replace("\r\n","\n").replace("\r","\n").strip())
    if not blocks or len(blocks)>MAX_CUES:
        raise SubtitleError("Допустимо от 1 до 24 блоков SRT.")
    cues=[]
    for i,block in enumerate(blocks):
        lines=block.strip().split("\n")
        if len(lines)<3 or lines[0].strip()!=str(i+1):
            raise SubtitleError("SRT: ожидаются последовательные номера кадров.")
        match=TIMECODE.fullmatch(lines[1].strip())
        if not match:
            raise SubtitleError("SRT: формат времени 00:00:01,000 --> 00:00:03,000.")
        start=_timestamp(*match.groups()[:4])
        end=_timestamp(*match.groups()[4:])
        caption=" ".join(line.strip() for line in lines[2:]).strip()
        if (not .0 <= start < end <= max_time or end-start<.15 or
                len(caption)>110 or not caption or
                any(ord(ch)<32 for ch in caption)):
            raise SubtitleError("SRT: недопустимое время или текст субтитра.")
        if cues and start < cues[-1].end:
            raise SubtitleError("Субтитры не должны накладываться друг на друга.")
        cues.append(SubtitleCue(round(start,3),round(end,3),caption))
    return tuple(cues)


def load_srt(path: Path, *, max_time=90.):
    raw=Path(path).expanduser()
    if (raw.is_symlink() or not raw.is_file()
            or raw.suffix.casefold() != ".srt" or
            not 10 <= raw.stat().st_size <= MAX_SRT_BYTES):
        raise SubtitleError("Выбери обычный локальный .srt до 80 КБ.")
    try:
        text=raw.read_text(encoding="utf-8-sig")
    except (UnicodeError,OSError) as exc:
        raise SubtitleError("Не удалось прочитать SRT как UTF-8.") from exc
    return parse_srt(text,max_time=max_time)


def burn_subtitles(
    movie: Path, output: Path, cues: tuple[SubtitleCue,...], *,
    ffmpeg: str, width: int, height: int, seconds: float,
    executor, cancel: threading.Event | None = None,
):
    """Burn caption bitmaps into an intermediate MP4 with original AAC copy."""
    from viral_studio import _make_caption_png

    if (not 128 <= width <= 3840 or not 128 <= height <= 3840
            or not math.isfinite(seconds) or not .7<=seconds<=95
            or not 1<=len(cues)<=MAX_CUES):
        raise SubtitleError("Недопустимая длительность или размер фильма.")
    if cancel is not None and cancel.is_set():
        raise SubtitleError("Операция прервана до обработки субтитров.")
    for cue in cues:
        if not isinstance(cue,SubtitleCue) or cue.start >= seconds or cue.end > seconds+.04:
            raise SubtitleError("Время субтитра выходит за пределы фильма.")
    with tempfile.TemporaryDirectory(prefix=".nova-subtitle-",dir=str(Path(output).parent)) as tmp:
        work=Path(tmp)
        inputs=[ffmpeg,"-hide_banner","-loglevel","error",
                "-nostdin","-y","-i",str(movie)]
        filters=["[0:v:0]fps=30,format=yuv420p[base]"]
        previous="base"
        for idx,cue in enumerate(cues,1):
            if cancel is not None and cancel.is_set():
                raise SubtitleError("Монтаж субтитров отменён.")
            picture=work/f"subtitle_{idx:02d}.png"
            _make_caption_png(cue.text,picture,width,height)
            inputs += ["-loop","1","-framerate","30","-i",str(picture)]
            filters.append(f"[{idx}:v:0]fps=30,format=rgba[caption{idx}]")
            filters.append(
                f"[{previous}][caption{idx}]overlay=0:0:"
                f"eof_action=pass:repeatlast=0:"
                f"enable='between(t,{cue.start:.3f},{cue.end:.3f})'[v{idx}]")
            previous=f"v{idx}"
        filters.append(f"[{previous}]format=yuv420p[outv]")
        inputs += [
            "-filter_complex",";".join(filters),"-map","[outv]",
            "-map","0:a:0",
            "-t",f"{seconds:.3f}",
            "-c:v","libx264","-preset","veryfast","-crf","23",
            "-pix_fmt","yuv420p","-r","30","-c:a","copy",
            "-movflags","+faststart",str(output),
        ]
        executor(inputs,timeout=900,cancel=cancel)
    return Path(output)
