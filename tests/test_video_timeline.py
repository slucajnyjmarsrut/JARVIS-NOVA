# -*- coding: utf-8 -*-
"""Editable timeline tests: exact trim math, history, safe files, FFmpeg."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from video_timeline import (
    ASPECTS, MAX_CUTS, TimelineCut, TimelineError, TimelineHistory,
    TimelineProject, _segment_graph, estimate_seconds,
    save_timeline, load_timeline, validate_timeline, render_timeline,
)


class TimelineTests(unittest.TestCase):
    def fixture(self, root):
        base=Path(root)
        one=base/"01.mp4"
        two=base/"02.mp4"
        one.write_bytes(b"sample"*500)
        two.write_bytes(b"sample-two"*600)
        project=TimelineProject(
            cuts=(TimelineCut(one, source_start=.1, duration=1.7,
                              speed=1.0, caption="Первый титр"),
                  TimelineCut(two, source_start=.4, duration=1.5,
                              speed=1.5, caption="")),
            output=base/"edited.mp4",
            aspect="Shorts / Reels / TikTok 9:16", color="vibrant",
            transition="fadeblack",transition_seconds=.15)
        return project

    def test_real_timeline_lengths_transitions_and_four_aspects(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            self.assertEqual(len(ASPECTS),4)
            self.assertEqual(estimate_seconds(p),3.05)
            for aspect in ASPECTS:
                with self.subTest(aspect=aspect):
                    q=replace(p,aspect=aspect)
                    validate_timeline(q)
                    graph=_segment_graph(
                        aspect,q.color,1.,1.7,True,caption_index=1)
                    self.assertIn(f"scale={ASPECTS[aspect][0]}:{ASPECTS[aspect][1]}",graph)
                    self.assertIn("fade=t=in",graph)
                    self.assertIn("overlay=0:0",graph)
                    self.assertIn("[v]",graph)

    def test_copy_move_split_and_undo_redo_never_mutate_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            original=[c.path.read_bytes() for c in p.cuts]
            history=TimelineHistory(limit=4)
            before=p.cuts
            history.push(before)
            reordered=tuple(reversed(before))
            self.assertEqual(history.undo(reordered),before)
            self.assertEqual(history.redo(before),reordered)
            history.push(reordered)
            first=reordered[0]
            cut_at=.75
            left=replace(first,duration=cut_at)
            right=replace(first,source_start=first.source_start+cut_at*first.speed,
                          duration=first.duration-cut_at)
            self.assertAlmostEqual(right.source_start,.4+1.125)
            self.assertAlmostEqual(left.duration+right.duration,first.duration)
            self.assertEqual([c.path.read_bytes() for c in p.cuts],original)

    def test_json_project_roundtrip_unknown_fields_are_ignored_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            project_file=Path(tmp)/"timeline.json"
            save_timeline(p,project_file)
            loaded=load_timeline(project_file)
            # Windows may spell the SAME directory as RUNNER~1 or
            # runneradmin (8.3 alias); verify file identity, not text.
            self.assertEqual(loaded.aspect,p.aspect)
            self.assertEqual(loaded.color,p.color)
            self.assertEqual(loaded.transition,p.transition)
            self.assertEqual(loaded.transition_seconds,p.transition_seconds)
            self.assertEqual(loaded.output.name,p.output.name)
            self.assertTrue(loaded.output.parent.samefile(p.output.parent))
            self.assertEqual(len(loaded.cuts),len(p.cuts))
            for imported,original in zip(loaded.cuts,p.cuts):
                self.assertTrue(imported.path.samefile(original.path))
                self.assertEqual(imported.source_start,original.source_start)
                self.assertEqual(imported.duration,original.duration)
                self.assertEqual(imported.speed,original.speed)
                self.assertEqual(imported.caption,original.caption)
            with self.assertRaises(TimelineError):
                save_timeline(p,project_file)
            attack=Path(tmp)/"malformed.json"
            attack.write_text('{"schema":"not-a-timeline","cuts":[]}',encoding="utf-8")
            with self.assertRaises(TimelineError):
                load_timeline(attack)
            overlarge=Path(tmp)/"large.json"
            overlarge.write_bytes(b"z"*120_001)
            with self.assertRaises(TimelineError):
                load_timeline(overlarge)

    def test_incorrect_paths_and_speeds_are_rejected_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            for broken in (
                replace(p,cuts=()),
                replace(p,cuts=p.cuts*(MAX_CUTS+1)),
                replace(p,cuts=(replace(p.cuts[0],duration=100),)),
                replace(p,cuts=(replace(p.cuts[0],speed=100),)),
                replace(p,cuts=(replace(p.cuts[0],speed=float("nan")),)),
                replace(p,cuts=(replace(p.cuts[0],caption="a"*111),)),
                replace(p,aspect=";exec"),
                replace(p,color="url=https://external.site"),
                replace(p,transition=";rm"),
                replace(p,transition_seconds=.9),
                replace(p,output=p.cuts[0].path),
                replace(p,output=Path(tmp)/"not_mp4.txt"),
            ):
                with self.subTest(broken=broken),self.assertRaises(TimelineError):
                    validate_timeline(broken)
            p.output.write_bytes(b"existing")
            with self.assertRaises(TimelineError):
                validate_timeline(p)
            self.assertEqual(p.output.read_bytes(),b"existing")

    def test_srt_after_final_duration_fails_before_ffmpeg_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            project=self.fixture(tmp)
            subtitle=root/"long_after_cut.srt"
            subtitle.write_text(
                chr(10).join([
                    "1","00:00:06,000 --> 00:00:07,000",
                    "Too late",""]),encoding="utf-8")
            project=replace(project,subtitles=subtitle)
            with mock.patch("viral_studio._probe") as probe:
                with self.assertRaisesRegex(TimelineError,"SRT"):
                    render_timeline(
                        project,tools=("ffmpeg","ffprobe"))
                probe.assert_not_called()
            self.assertFalse(project.output.exists())

    def test_abort_before_probe_does_not_touch_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            cancel=threading.Event()
            cancel.set()
            with mock.patch("viral_studio._probe") as probe:
                with self.assertRaisesRegex(TimelineError,"отменён"):
                    render_timeline(p,cancel=cancel,tools=("ffmpeg","ffprobe"))
                probe.assert_not_called()
            self.assertFalse(p.output.exists())

    def test_fails_if_requested_segment_extends_beyond_real_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            with mock.patch("viral_studio._probe",return_value=(2.0,True)):
                with self.assertRaisesRegex(TimelineError,"слишком короткий"):
                    render_timeline(p,tools=("ffmpeg","ffprobe"),
                                    executor=mock.Mock())
            self.assertFalse(p.output.exists())

    def test_captioned_silent_segment_uses_bounded_silence_not_source_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(tmp)
            p=replace(p,cuts=(replace(p.cuts[0],speed=1.5),))
            progress=[]
            commands=[]
            def fake_execute(args,**kwargs):
                commands.append(args)
                if args[0]=="ffmpeg":
                    Path(args[-1]).write_bytes(b"movie"*400)
                return b""
            def fake_finish(parts,lengths,output,ffmpeg,**kwargs):
                Path(output).write_bytes(b"finished"*400)
                return {"expected_seconds":1.7,"transition":"none"}
            with mock.patch("viral_studio._probe",return_value=(4.,False)), \
                 mock.patch("viral_studio._make_caption_png",
                            side_effect=lambda text,path,w,h:Path(path).write_bytes(b"title"*200)), \
                 mock.patch("video_timeline.finish_video",side_effect=fake_finish), \
                 mock.patch("video_timeline.verify_edit_output_media",
                            return_value={"duration":1.7,"quality_checked":True}):
                result=render_timeline(
                    p,tools=("ffmpeg","ffprobe"),executor=fake_execute,
                    progress=lambda n,total,label:progress.append((n,total,label)))
            cmd=commands[0]
            graph=cmd[cmd.index("-filter_complex")+1]
            self.assertIn("[1:a:0]aresample=48000",graph)
            self.assertIn("[2:v:0]format=rgba",graph)
            self.assertIn("setpts=(PTS-STARTPTS)/1.500",graph)
            self.assertIn("overlay=0:0",graph)
            self.assertTrue(p.output.is_file())
            self.assertEqual(result["cuts"][0]["caption"],"Первый титр")
            self.assertFalse(result["published"])
            self.assertTrue(progress)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg unavailable")
    def test_real_precise_two_clip_trim_speed_caption_and_transition(self):
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tracks=[]
            for idx,color in enumerate(("red","blue")):
                path=root/f"source_{idx}.mp4"
                cmd=[ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
                     "-y","-f","lavfi","-i",
                     f"color=c={color}:s=320x180:r=30:d=3.2"]
                if idx==0:
                    cmd+=["-f","lavfi","-i",
                          "sine=frequency=440:sample_rate=48000:duration=3.2"]
                cmd+=["-t","3.2","-c:v","libx264","-pix_fmt","yuv420p"]
                if idx==0:
                    cmd+=["-c:a","aac"]
                cmd += [str(path)]
                proc=subprocess.run(cmd,capture_output=True,timeout=40)
                if proc.returncode:
                    self.skipTest("FFmpeg test input encode unavailable: "+
                                  proc.stderr.decode(errors="replace")[-150:])
                tracks.append(path)
            checksums=[hashlib.sha256(p.read_bytes()).hexdigest() for p in tracks]
            subtitles=root/"captions.srt"
            subtitles.write_text(
                "1\n00:00:00,300 --> 00:00:01,300\nПервый клип\n"
                "\n2\n00:00:01,500 --> 00:00:02,300\nФинал!\n",
                encoding="utf-8")
            project=TimelineProject(
                cuts=(
                    TimelineCut(tracks[0],source_start=.3,duration=1.5,
                                speed=1.,caption="Привет из NOVA"),
                    TimelineCut(tracks[1],source_start=.2,duration=1.4,
                                speed=1.6,caption=""),
                ),
                output=root/"final.mp4",aspect="YouTube / Gaming 16:9",
                color="cinematic",transition="dissolve",
                transition_seconds=.12,subtitles=subtitles)
            result=render_timeline(project,tools=(ffmpeg,ffprobe))
            self.assertGreater(project.output.stat().st_size,1000)
            self.assertEqual(result["technical_quality"]["video_codec"],"h264")
            self.assertEqual(result["technical_quality"]["audio_codec"],"aac")
            self.assertEqual(result["technical_quality"]["width"],1280)
            self.assertEqual(result["technical_quality"]["height"],720)
            self.assertEqual(len(result["render_decisions"]),2)
            self.assertEqual(result["subtitle_cues"],2)
            self.assertAlmostEqual(result["duration"],estimate_seconds(project),delta=.6)
            self.assertTrue(project.output.with_name("final_TIMELINE.json").is_file())
            self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in tracks],checksums)
            with self.assertRaises(TimelineError):
                render_timeline(project,tools=(ffmpeg,ffprobe))

    def test_window_controls_open_without_automatic_website_or_render(self):
        import tkinter as tk
        from video_timeline_ui import TimelineWindow
        try:
            root=tk.Tk()
        except tk.TclError:
            self.skipTest("Tk graphical display unavailable")
        root.withdraw()
        window=None
        try:
            window=TimelineWindow(root)
            window.update_idletasks()
            self.assertFalse(window._busy)
            self.assertIsNone(window._busy_since)
            self.assertEqual(str(window._progress.cget("mode")),"indeterminate")
            self.assertEqual(window._cuts,[])
            self.assertEqual(window._events.qsize(),0)
            with tempfile.TemporaryDirectory() as tmp:
                p=self.fixture(tmp)
                window._modify(list(p.cuts),0)
                self.assertEqual(len(window._cuts),2)
                # Real Tk canvas mouse press/release changes the clip order.
                width=max(240,window._timeline.winfo_width()-16)
                window._timeline_pressed(SimpleNamespace(x=8+int(width*.20)))
                window._timeline_released(SimpleNamespace(x=8+int(width*.85)))
                self.assertEqual(window._cuts[1].path,p.cuts[0].path)
                window.undo()
                self.assertEqual(window._cuts[0].path,p.cuts[0].path)
                window._select(0)
                window.split_at.set("0.8")
                window.split()
                self.assertEqual(len(window._cuts),3)
                self.assertEqual(window._cuts[1].source_start,.9)
                window.undo()
                self.assertEqual(len(window._cuts),2)
                window.redo()
                self.assertEqual(len(window._cuts),3)
        finally:
            if window is not None:
                window.destroy()
            root.destroy()


if __name__=="__main__":
    unittest.main()
