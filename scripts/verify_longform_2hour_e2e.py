# -*- coding: utf-8 -*-
"""Real 2-hour source -> 15-minute FFmpeg montage acceptance.

CI uses synthetic 160x90 footage solely to make a 900-second *real* MP4
quickly. The production timeline renderer, selector, audio, metadata and
FFprobe verification are used unchanged; ONLY the output frame resolution
is reduced during this synthetic benchmark. It does NOT prove editing
quality on real-world footage or speed at 720p/1080p.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from viral_studio import _probe, ffmpeg_tools
from smart_highlight_selection import select_active_cuts
from video_timeline import (
    ASPECTS, TimelineProject, estimate_seconds, render_timeline,
)
from long_video_limits import MAX_OUTPUT_SECONDS


def _digest(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(2_000_000),b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    for output in (sys.stdout,sys.stderr):
        if output and hasattr(output,"reconfigure"):
            output.reconfigure(encoding="utf-8",errors="backslashreplace")
    try:
        ffmpeg,ffprobe=ffmpeg_tools()
        with tempfile.TemporaryDirectory(prefix="nova-real-longform-") as td:
            root=Path(td)
            original=root/"original_2h.mp4"
            command=[
                ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y",
                "-f","lavfi","-i","testsrc2=size=160x90:rate=2:duration=7200",
                "-an","-c:v","libx264","-preset","ultrafast",
                "-crf","35","-pix_fmt","yuv420p","-g","24",
                "-movflags","+faststart",str(original),
            ]
            subprocess.run(command,check=True,timeout=100,
                           stdin=subprocess.DEVNULL,capture_output=True)
            source_duration,has_audio=_probe(original,ffprobe)
            if abs(source_duration-7200)>1 or has_audio:
                raise RuntimeError("Synthetic input is not a real silent 2h MP4.")
            source_hash=_digest(original)
            sampled,quality=select_active_cuts(
                ((original,source_duration),),target_seconds=900,
                ffmpeg=ffmpeg,
                executor=__import__("viral_studio")._execute,
                max_windows=48)
            if (not 16<=len(sampled)<=64 or quality.usable<16
                    or quality.fallback):
                raise RuntimeError("Autonomous scene selection failed: "
                                   +repr(quality))
            if not any(x.source_start>3600 for x in sampled):
                raise RuntimeError("Second hour of the original was not selected.")
            project=TimelineProject(
                cuts=sampled,output=root/"montage_15min.mp4",
                aspect="YouTube / Gaming 16:9",color="none",
                transition="fade",transition_seconds=0,
            )
            if abs(estimate_seconds(project)-900)>.1:
                raise RuntimeError("Draft timeline is not fifteen minutes.")
            # Real production engine, but test output is low-res on purpose:
            # avoid a 20-minute high-res benchmark on GitHub shared CI.
            with patch.dict(ASPECTS,{"YouTube / Gaming 16:9":(160,90)}):
                result=render_timeline(
                    project,tools=(ffmpeg,ffprobe),audit_coverage=True)
            if abs(result.get("duration",0)-900)>2:
                raise RuntimeError("Exported MP4 duration is incorrect: "
                                   +str(result.get("duration")))
            if not result.get("technical_quality",{}).get("quality_checked"):
                raise RuntimeError("Finished MP4 did not pass FFprobe gate.")
            coverage=result.get("quality_coverage") or {}
            regions=coverage.get("regions",[])
            if not coverage.get("checked") or len(regions)!=5:
                raise RuntimeError("Distributed output audit did not run.")
            if not (regions[0]["at_seconds"]<10 and
                    regions[-1]["at_seconds"]>890 and
                    all(0<=entry["black_fraction"]<=1 for entry in regions)):
                raise RuntimeError("Distributed audit did not cover the whole MP4.")
            sidecar=project.output.with_name(
                project.output.stem+"_TIMELINE.json")
            report=json.loads(sidecar.read_text("utf-8"))
            if (not sidecar.is_file() or
                    len(report["render_decisions"])!=len(sampled) or
                    not project.output.is_file()):
                raise RuntimeError("The real montage or EDL is missing.")
            if _digest(original)!=source_hash:
                raise RuntimeError("The original two-hour video was modified.")
            print(
                "REAL LONGFORM PASS: two-hour MP4 -> 15-minute MP4, "
                +str(len(sampled))+" activity-selected segments, "
                "source unchanged, FFprobe and EDL checked.",
                flush=True)
        return 0
    except Exception as exc:
        print("REAL LONGFORM FAIL: "+type(exc).__name__+": "+str(exc),
              file=sys.stderr,flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
