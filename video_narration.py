# -*- coding: utf-8 -*-
"""Optional LOCAL Russian voiceover for automatic video edits.

All narration comes from the user's local script, is synthesized by bundled
Silero and is mixed into the already rendered video with bundled FFmpeg.
No third-party music or API; original footage and previous render are preserved
on failure. This is a speech track, not falsely timed word-level subtitles.
"""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import wave

import numpy as np


class NarrationError(RuntimeError):
    pass


def narration_text(brief) -> str:
    """Keep a short intelligible intro/outro instead of truncating an AI monologue."""
    hook=" ".join(str(getattr(brief,"hook","") or "").split())
    cta=" ".join(str(getattr(brief,"call_to_action","") or "").split())
    script=" ".join(str(getattr(brief,"script","") or "").split())
    if 20<=len(script)<=175:
        return script
    return (hook+" "+cta).strip()[:340]


def synthesize_narration(text: str, target: Path, max_seconds: float, *,
                         synthesizer=None, sample_rate: int = 48000) -> float:
    """Write a bounded PCM WAV. Reject overly long TTS; never trim spoken words."""
    if not isinstance(text,str) or not 1<=len(text.strip())<=700:
        raise NarrationError("Слишком длинный или пустой текст озвучки")
    if not 1.<=max_seconds<=95. or sample_rate!=48000:
        raise NarrationError("Недопустимая длительность/частота озвучки")
    if synthesizer is None:
        from silero_engine import SileroConfig, SileroSynthesizer
        from speaker import assets
        synthesizer=SileroSynthesizer(SileroConfig(assets()/"v5_ru.pt"))
        synthesizer.initialize()
    from speech_output import split_for_tts
    parts=split_for_tts(text,max_chars=180,max_total=700)
    if not parts:
        raise NarrationError("Нет текста для озвучки")
    pcm_parts=[]
    total=0
    gap=np.zeros(round(sample_rate*.08),dtype=np.float32)
    for part in parts:
        clip=np.asarray(synthesizer.synthesize(part),dtype=np.float32).ravel()
        if not clip.size or not np.all(np.isfinite(clip)):
            raise NarrationError("Silero вернул некорректный звук")
        total+=clip.size + (gap.size if pcm_parts else 0)
        if total>int((max_seconds-.15)*sample_rate):
            raise NarrationError("Текст длиннее ролика; сохранил исходный звук")
        if pcm_parts:
            pcm_parts.append(gap)
        pcm_parts.append(clip)
    sound=np.clip(np.concatenate(pcm_parts),-1.,1.)
    peak=float(np.max(np.abs(sound)))
    if peak<.004:
        raise NarrationError("Синтезированная речь слишком тихая")
    if Path(target).exists():
        raise NarrationError("Не перезаписываю существующую озвучку")
    with Path(target).open("xb") as raw:
        with wave.open(raw,"wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes((sound*32767).astype("<i2").tobytes())
    return sound.size/sample_rate


def mix_local_narration(video: Path, text: str, *, synthesizer=None,
                        tools=None, executor=None, cancel=None) -> dict:
    """Only replace video after new H264/AAC version passes independent probe."""
    from viral_studio import _execute, ffmpeg_tools
    from smart_montage import verify_output_media
    video=Path(video)
    if not video.is_file() or video.is_symlink():
        raise NarrationError("Итоговое видео для озвучки не найдено")
    ffmpeg,ffprobe=tools if tools is not None else ffmpeg_tools()
    executor=executor or _execute
    if cancel is not None and cancel.is_set():
        raise NarrationError("Озвучка отменена")
    # Existing original is checked using ffprobe, not an untrusted filename.
    source_info=executor([ffprobe,"-v","error","-show_format","-show_streams",
                          "-of","json",str(video)],timeout=30,cancel=cancel)
    import json
    try:
        metadata=json.loads(source_info)
        duration=float(metadata["format"]["duration"])
        has_audio=any(t.get("codec_type")=="audio" for t in metadata["streams"])
        if not has_audio or duration<1 or duration>95:
            raise ValueError("missing audio/invalid duration")
    except (ValueError,TypeError,KeyError) as exc:
        raise NarrationError("Исходный MP4 не прошёл проверку звука") from exc
    with tempfile.TemporaryDirectory(prefix="jarvis_narration_",dir=video.parent) as td:
        root=Path(td)
        wav=root/"voice.wav"
        seconds=synthesize_narration(text,wav,duration,synthesizer=synthesizer)
        temp_video=root/"narrated.mp4"
        args=[ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y",
              "-i",str(video),"-i",str(wav),
              "-filter_complex",
              "[0:a:0]volume=0.18[bed];[1:a:0]volume=1.0[voice];"
              "[bed][voice]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]",
              "-map","0:v:0","-map","[mixed]","-c:v","copy",
              "-c:a","aac","-b:a","160k","-movflags","+faststart",str(temp_video)]
        executor(args,timeout=180,cancel=cancel)
        verify_output_media(temp_video,ffprobe,duration,executor=executor,cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise NarrationError("Озвучка отменена")
        os.replace(temp_video,video)
    return {"narrated":True,"voice_seconds":round(seconds,2),
            "source":"bundled Silero v5 Russian; offline","audio":"voice + quiet original"}


def try_narrate_video(video: Path, brief, *, cancel=None,
                      synth=None, tools=None, executor=None) -> dict:
    """Best-effort enhancement: always report why original audio was retained."""
    narration=narration_text(brief)
    try:
        return mix_local_narration(video,narration,synthesizer=synth,
                                   tools=tools,executor=executor,cancel=cancel)
    except Exception as exc:
        return {"narrated":False,"reason":f"{type(exc).__name__}: {str(exc)[:130]}",
                "audio":"original footage preserved"}
