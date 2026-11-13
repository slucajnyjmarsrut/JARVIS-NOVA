# -*- coding: utf-8 -*-
"""Create an actual local vertical MP4 from just a checked topic/storyboard.

NO user footage, internet, external image model, unlicensed footage or invented
photorealistic frames. Makes animated *motion graphics*, original synthesized
sound, burned-in captions and SRT with the existing validated FFmpeg engine.

This is not diffusion video generation or spoken narration. Source frames are
Pillow vector illustrations. Nothing in the prompt is used as a shell command,
filename, URL or FFmpeg filter expression.
"""
from __future__ import annotations

from array import array
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import math
import random
import re
import wave

from viral_studio import Brief, ViralStudioError, validate_brief

# 360x640: low-memory-first vertical format, upscalable in a later release.
DEFAULT_SIZE = (360, 640)
SCENE_COLORS = (
    ((13, 22, 43), (22, 82, 123), (82, 219, 233)),
    ((21, 25, 49), (85, 42, 116), (233, 133, 246)),
    ((15, 41, 54), (17, 109, 117), (91, 244, 184)),
    ((43, 23, 46), (123, 58, 97), (255, 189, 134)),
    ((18, 31, 56), (45, 70, 139), (251, 216, 115)),
)
MAX_TOTAL_SECONDS = 55


class TopicVideoError(ViralStudioError):
    pass


def _font(size):
    from PIL import ImageFont
    for face in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(face, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _wrapped(draw, text, font, limit, *, max_lines=3):
    words = re.sub(r"[\x00-\x1f\x7f]", " ", text).split()
    lines, part = [], ""
    for word in words:
        proposal = (part + " " + word).strip()
        if part and draw.textbbox((0, 0), proposal, font=font)[2] > limit:
            lines.append(part)
            part = word
        else:
            part = proposal
    if part:
        lines.append(part)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:36].rstrip() + "…"
    return "\n".join(lines)


def _motif(draw, theme, index, width, height, accent, rng):
    """Distinct, deterministic original graphics; not a claim of actual footage."""
    if theme == "pixel":
        step = max(18, width // 13)
        for row in range(6):
            for col in range(11):
                if rng.random() < .53:
                    x = col * step + (index % 3) * 8
                    y = int(height * .20) + row * step
                    color = tuple(min(255, n + rng.randint(-22, 22))
                                  for n in accent)
                    draw.rectangle((x, y, x + step - 4, y + step - 4), fill=color)
    elif theme == "nature":
        for row in range(3):
            y = int(height * (.60 + row * .09))
            color = (20 + row * 12, 89 + row * 25, 95 + row * 12)
            draw.ellipse((-width // 3, y, width + width // 3, y + height),
                         fill=color)
        for col in range(4):
            x = int(width * (.13 + col * .24)) + (index * 7) % 18
            y = int(height * (.37 + col * .03))
            draw.rectangle((x - 4, y, x + 4, y + 80), fill=(72, 62, 56))
            draw.polygon((x - 35, y + 15, x, y - 65,
                          x + 35, y + 15), fill=accent)
    elif theme == "space":
        for _ in range(75):
            x, y = rng.randrange(width), rng.randrange(int(height * .70))
            draw.ellipse((x, y, x + 2, y + 2), fill=(232, 236, 250))
        x, y = width // 2 + index * 10 - 24, height // 2 - 70
        draw.ellipse((x - 77, y - 77, x + 77, y + 77), fill=accent,
                     outline=(230, 235, 240), width=3)
        draw.arc((x - 130, y - 35, x + 130, y + 37),
                 start=5, end=175, fill=(225, 240, 250), width=5)
    elif theme == "tech":
        for _ in range(24):
            x, y = rng.randrange(width), rng.randrange(int(height * .72))
            dx, dy = rng.randrange(20, 90), rng.randrange(10, 60)
            draw.line((x, y, min(width, x + dx), y,
                       min(width, x + dx), min(height, y + dy)),
                      fill=accent, width=3)
            draw.ellipse((x - 3, y - 3, x + 3, y + 3),
                         fill=(248, 248, 250))
    else:
        for item in range(10):
            x = rng.randint(-70, width)
            y = rng.randint(int(height * .20), int(height * .73))
            radius = rng.randint(10, 85)
            if (item + index) % 2:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                             outline=accent, width=4)
            else:
                draw.rounded_rectangle(
                    (x-radius, y-radius//2, x+radius, y+radius//2),
                    radius=12, outline=accent, width=4)


def _theme(topic):
    t = topic.casefold()
    if any(x in t for x in ("minecraft", "майнкрафт", "roblox", "роблокс",
                             "игр", "pixel", "пиксел")):
        return "pixel"
    if any(x in t for x in ("космос", "space", "звезд", "планет", "марс")):
        return "space"
    if any(x in t for x in ("лес", "природ", "растен", "живот", "океан", "nature")):
        return "nature"
    if any(x in t for x in ("ai", "ии", "нейросет", "интеллект", "компьютер", "технолог", "код", "robot")):
        return "tech"
    return "abstract"


def _draw_card(brief, shot, index, target, size):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise TopicVideoError("Для генерации кадров нужен Pillow.") from exc
    width, height = size
    dark, bright, accent = SCENE_COLORS[(index - 1) % len(SCENE_COLORS)]
    image = Image.new("RGB", size, dark)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height-1)
        bg = tuple(int(a * (1-ratio) + b * ratio) for a, b in zip(dark, bright))
        draw.line((0, y, width, y), fill=bg)
    # Use each AI-written shot description to give successive scenes
    # different imagery, rather than recoloring the same generic topic card.
    seed = int.from_bytes(sha256(
        (brief.topic + "|" + str(shot.film) + "|" + str(index))
        .encode("utf-8")).digest()[:8], "big")
    _motif(draw, _theme(brief.topic), index, width, height, accent,
           random.Random(seed))
    pad = int(width * .055)
    draw.rounded_rectangle((pad, int(height*.035), width-pad, int(height*.16)),
                           radius=15, fill=(15, 23, 40), outline=accent, width=2)
    draw.text((pad + 12, int(height*.055)), "JARVIS NOVA  /  VIDEO",
              fill=accent, font=_font(max(12, width//30)))
    label = f"СЦЕНА {index:02d} / 05"
    draw.text((pad + 12, int(height*.11)), label,
              fill=(246, 246, 249), font=_font(max(13, width//25)))
    draw.rounded_rectangle((pad, int(height*.60), width-pad, int(height*.69)),
                           radius=14, fill=(14, 23, 37))
    title = _wrapped(draw, brief.topic, _font(max(14, width//17)),
                     width - 3*pad, max_lines=2)
    draw.multiline_text((pad+12, int(height*.612)), title,
                        font=_font(max(14, width//17)),
                        spacing=6, fill=(250, 250, 251))
    # The image itself shows an AI-written, scene-specific visual direction.
    # All text is rendered as pixels by Pillow, never as an FFmpeg expression.
    instruction = _wrapped(
        draw, shot.film[:260], _font(max(12, width//25)),
        width - 3 * pad, max_lines=3)
    draw.rounded_rectangle(
        (pad, int(height*.73), width-pad, int(height*.92)),
        radius=14, fill=(15, 23, 40), outline=accent, width=2)
    draw.multiline_text(
        (pad+12, int(height*.75)), instruction,
        font=_font(max(12, width//25)), spacing=5, fill=(240, 244, 248))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as file:
        image.save(file, format="PNG")


def _music(original_file, index, seconds):
    """Original simple ambient synthesizer; no copyrighted audio or TTS."""
    samples = int(48000 * seconds)
    if samples > 48000 * 16:
        raise TopicVideoError("Кадр слишком длинный для синтезатора.")
    base = (164.81, 196.0, 220.0, 246.94, 164.81)[(index-1) % 5]
    audio = array("h")
    for n in range(samples):
        t = n / 48000.0
        fade = min(1., t * 5, max(0., (seconds - t) * 4))
        pulse = .55 + .45 * math.sin(2 * math.pi * 1.2 * t)**2
        amp = (math.sin(2 * math.pi * base*t)
               + .55*math.sin(2*math.pi*base*1.5*t)
               + .15*math.sin(2*math.pi*base*2*t))
        audio.append(int(2300 * fade * pulse * amp))
    with original_file.open("xb") as raw:
        with wave.open(raw, "wb") as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(48000)
            wave_file.writeframes(audio.tobytes())


def render_topic_video(brief: Brief, output_dir: Path, *, size=DEFAULT_SIZE,
                       tools=None, cancel=None, executor=None, renderer=None):
    """Generate five animated, originally illustrated clips and a verified MP4.

    The target directory must already exist and be empty. All inputs are
    generated in a new temporary directory. Production uses the project's
    FFmpeg renderer, which also does the independent ffprobe quality gate.
    """
    from viral_studio import _execute, ffmpeg_tools, render_video
    validate_brief(brief)
    if len(brief.shots) != 5 or sum(s.seconds for s in brief.shots)>MAX_TOTAL_SECONDS:
        raise TopicVideoError("Ролик из темы должен содержать ровно пять коротких сцен.")
    if (type(size) not in (tuple, list) or len(size)!=2 or
            type(size[0]) is not int or type(size[1]) is not int or
            not 180 <= size[0] <= 720 or not 320 <= size[1] <= 1280 or
            size[0] >= size[1]):
        raise TopicVideoError("Некорректный вертикальный размер.")
    output_dir = Path(output_dir).absolute()
    if (not output_dir.is_dir() or output_dir.is_symlink() or
            any(output_dir.iterdir())):
        raise TopicVideoError("Нужна новая пустая папка, ничего не перезаписываю.")
    ffmpeg, ffprobe = tools or ffmpeg_tools()
    execute = executor or _execute
    publish = renderer or render_video
    result_path = output_dir / "JARVIS_NOVA_FROM_TOPIC.mp4"
    with TemporaryDirectory(prefix="jarvis-topic-") as temporary:
        clips = Path(temporary) / "generated_clips"
        clips.mkdir()
        for i, shot in enumerate(brief.shots, 1):
            if cancel is not None and cancel.is_set():
                raise TopicVideoError("Автономная генерация видео отменена.")
            card = Path(temporary) / f"card-{i:02}.png"
            audio = Path(temporary) / f"original-audio-{i:02}.wav"
            _draw_card(brief, shot, i, card, size)
            duration = round(float(shot.seconds) + .9, 2)
            _music(audio, i, duration)
            # Fixed internal filter: no model/user text can become a command.
            zoom = ("zoompan=z='min(zoom+0.0008,1.07)':d=1:"
                    f"s={size[0]}x{size[1]}:fps=24,format=yuv420p")
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
                   "-nostdin", "-y", "-loop", "1", "-framerate", "24",
                   "-i", str(card), "-i", str(audio), "-t", str(duration),
                   "-vf", zoom, "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "25", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "96k", "-shortest",
                   str(clips / f"{i:02}.mp4")]
            execute(cmd, timeout=180, cancel=cancel)
        result = publish(brief, clips, result_path, size=size,
                         tools=(ffmpeg, ffprobe), cancel=cancel)
        if (not isinstance(result, dict) or
                not result.get("technical_quality", {}).get("quality_checked") or
                not result_path.is_file() or result_path.stat().st_size < 1000):
            raise TopicVideoError("MP4 не прошёл проверку FFprobe; ролик не готов.")
    # Provenance summary is explicit about limits: this is motion graphics,
    # not hallucinated footage of a game, person or real-world event.
    manifest = {
        "mode": "original_offline_motion_graphics",
        "real_video_generation_model": False,
        "external_footage": False,
        "spoken_narration": False,
        "audio": "original synthesized instrumental tones",
        "topic": brief.topic,
        "scenario_generator": brief.generator,
        "scenes": len(brief.shots),
        "technical_quality": result["technical_quality"],
    }
    with (output_dir / "ORIGIN_AND_QUALITY.json").open(
            "x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    with (output_dir / "README_RU.md").open("x", encoding="utf-8") as stream:
        stream.write(
            "# Видеоролик из темы\n\n"
            "JARVIS создал анимированные графические сцены, собственные "
            "синтезированные тона, титры и MP4 без твоих материалов и без "
            "интернета. Сценарий: " + brief.generator + ".\n\n"
            "Это **моушн-графика**, а не реалистичные кадры Minecraft/фильма "
            "и не генерация видео diffusion-моделью. "
            "Звуковое сопровождение не содержит дикторской речи. "
            "Проверь факты, художественное качество и титры вручную "
            "перед публикацией.\n"
        )
    return result
