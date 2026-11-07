# -*- coding: utf-8 -*-
"""Real native FilmCraft CLI handoff, no GUI/microphone; called by Windows CI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from filmcraft_bridge import open_in_filmcraft


def run(command, timeout=90):
    p = subprocess.run(list(map(str, command)), capture_output=True,
                       text=True, errors="replace", timeout=timeout, shell=False)
    if p.returncode:
        raise RuntimeError(
            "External tool failed (exit=" + str(p.returncode) + "): " +
            p.stderr[-1200:])
    return p.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filmcraft-exe", type=Path, required=True)
    args = parser.parse_args()
    exe = args.filmcraft_exe.resolve()
    cli = exe.with_name("filmcraft-cli.exe")
    if not exe.is_file() or not cli.is_file():
        raise RuntimeError("FilmCraft portable missing filmcraft.exe or filmcraft-cli.exe")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg needed only for synthetic CI media")
    with tempfile.TemporaryDirectory(prefix="jarvis-filmcraft-smoke-") as tmp:
        root = Path(tmp)
        clips = root / "raw"
        clips.mkdir()
        for index, color in enumerate(("red", "blue"), 1):
            run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                 f"color=c={color}:s=180x320:r=30:d=2.8",
                 "-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=2.8",
                 "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                 "-shortest", clips / f"{index:02}.mp4"])
        final = root / "JARVIS_NOVA_VERTICAL.mp4"
        shutil.copyfile(clips / "01.mp4", final)
        info = {
            "output": str(final), "duration": 2.8,
            "source_directory": str(clips),
            "segments": [
                {"file": "01.mp4", "start": 0.15, "seconds": 1.2,
                 "on_screen": "Scene 1"},
                {"file": "02.mp4", "start": 0.3, "seconds": 1.2,
                 "on_screen": "Scene 2"},
            ],
            "professional": {"transition_seconds": 0.15},
        }
        started = []
        result = open_in_filmcraft(
            exe, final, metadata=info,
            launcher=lambda cmd, **kwargs: started.append(cmd))
        if result.mode != "project" or not result.project or not result.project.exists():
            raise RuntimeError("FilmCraft failed to create an editable native project: "
                               + result.detail)
        if not result.timeline.is_file():
            raise RuntimeError("Missing OTIO interchange sidecar")
        timeline = json.loads(result.timeline.read_text(encoding="utf-8"))
        if timeline["OTIO_SCHEMA"] != "Timeline.1":
            raise RuntimeError("Invalid OTIO interchange file")
        native = json.loads(result.project.read_text(encoding="utf-8"))
        if native.get("format") != "filmcraft.project":
            raise RuntimeError("Invalid native FilmCraft document")
        inspected = run(
            [cli, "--project", str(result.project), "inspect", "sequence"],
            timeout=120)
        obj = json.loads(inspected)
        if not isinstance(obj, dict) or not obj:
            raise RuntimeError("FilmCraft CLI reported an empty native sequence")
        if started != [[str(exe), str(result.project)]]:
            raise RuntimeError("FilmCraft launch did not target the editable .fcproj")
        print("PASS: FilmCraft CLI imported original source cuts and saved",
              result.project.name, "with", result.source_count, "original clips.")


if __name__ == "__main__":
    main()
