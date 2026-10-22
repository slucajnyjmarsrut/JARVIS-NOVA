# -*- coding: utf-8 -*-
"""Final MP4 quality gate coordinating visual and audio inspections.

Never labels uncertain detections as objective artistic failure. In particular
static footage and silence can be intentional. Scores here are diagnostic
penalties, NOT predicted popularity, watch time or publishing readiness.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from video_frame_audit import inspect_video_frames, FrameAudit
from video_audio_audit import inspect_audio, AudioAudit


@dataclass(frozen=True)
class MediaQuality:
    checked: bool
    penalty: int
    warnings: tuple[str, ...]
    video: dict
    audio: dict


def combine_quality(video: FrameAudit, audio: AudioAudit) -> MediaQuality:
    penalty=0
    if video.black_fraction>.12:
        penalty+=15
    if video.white_fraction>.12:
        penalty+=10
    if video.longest_static_seconds>=4:
        penalty+=3
    if audio.quiet_fraction>=.92:
        penalty+=5
    if audio.clipped_fraction>=.002:
        penalty+=10
    penalty=min(30,penalty)
    return MediaQuality(True,penalty,video.warnings+audio.warnings,
                        asdict(video),asdict(audio))


def audit_finished_media(file: Path, *, ffmpeg=None, tools=None,
                         cancel=None, executor=None) -> MediaQuality:
    """Inspect a finished MP4 with bundled FFmpeg; read only, bounded memory."""
    file=Path(file)
    if not file.is_file() or file.stat().st_size<1000:
        raise ValueError("Для контроля нужен настоящий MP4")
    ffprobe=None
    if tools is not None:
        ffmpeg,ffprobe=tools
    elif ffmpeg is None:
        from viral_studio import ffmpeg_tools
        ffmpeg,ffprobe=ffmpeg_tools()
    video=inspect_video_frames(file,ffmpeg,cancel=cancel,executor=executor)
    audio=inspect_audio(file,ffmpeg,ffprobe=ffprobe,cancel=cancel,executor=executor)
    return combine_quality(video,audio)
