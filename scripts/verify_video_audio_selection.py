# -*- coding: utf-8 -*-
"""Real FFmpeg selection test: quiet video with intermittent audio narration.

This is a technical evidence test, not an artistic or semantic benchmark.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from viral_studio import _probe, _execute, ffmpeg_tools
from smart_highlight_selection import select_active_cuts
from video_timeline import draft_longform_cuts


def main():
    try:
        ffmpeg,ffprobe=ffmpeg_tools()
        with tempfile.TemporaryDirectory(prefix="nova-audio-signal-") as td:
            file=Path(td)/"static_picture_with_pulsed_audio.mp4"
            cmd=[
                ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y",
                "-f","lavfi","-i","color=c=gray:s=160x90:r=2:d=120",
                "-f","lavfi","-i","sine=f=440:r=8000:d=120",
                "-map","0:v:0","-map","1:a:0",
                "-filter:a","volume=if(gte(mod(t\\,10)\\,7)\\,1\\,0):eval=frame",
                "-c:v","libx264","-preset","ultrafast","-crf","35",
                "-c:a","aac","-b:a","32k","-shortest",str(file)
            ]
            subprocess.run(cmd,check=True,timeout=75,
                           stdin=subprocess.DEVNULL,capture_output=True)
            length,audio=_probe(file,ffprobe)
            if not audio or abs(length-120)>1:
                raise RuntimeError("Source has no detectable audio.")
            baseline=draft_longform_cuts(((file,length),),target_seconds=30)
            cuts,report=select_active_cuts(
                ((file,length),),target_seconds=30,
                ffmpeg=ffmpeg,executor=_execute,
                audio_sources={file:True},max_audio_windows=48)
            if report.audio_usable<20 or report.fallback:
                raise RuntimeError("Real sound samples were not decoded: "
                                   +repr(report))
            shifted=sum(a.source_start>b.source_start+1
                        for a,b in zip(cuts,baseline))
            if shifted<6:
                raise RuntimeError("Audio did not shift source selections: "+
                                   str(shifted)+"/"+str(len(cuts)))
            if abs(sum(c.duration for c in cuts)-30)>.1:
                raise RuntimeError("Audio changed the requested timeline length.")
            print("REAL AUDIO SIGNAL PASS: pulsed voice-frequency signal, "+
                  str(report.audio_usable)+" decoded windows, "+
                  str(shifted)+" activity-shifted cuts.",flush=True)
        return 0
    except Exception as exc:
        print("REAL AUDIO SIGNAL FAIL: "+str(exc),file=sys.stderr,flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
