# -*- coding: utf-8 -*-
"""Multi-track JARVIS: no overwrite, correct FFmpeg streams and real MP4."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest

from multitrack_composer import (
    MultitrackError, MultitrackProject, VisualLayer, POSITIONS,
    build_filter_graph, validate_project, render_multitrack,
    is_multitrack_request, save_multitrack, load_multitrack,
)


class MultitrackTests(unittest.TestCase):
    def test_chat_routes_explicit_multilayer_commands_only(self):
        for text in ("Джарвис, сделай многодорожечный монтаж",
                     "наложи логотип на видео","добавь озвучку к видео",
                     "наложи видео на видео"):
            self.assertTrue(is_multitrack_request(text),text)
        for text in ("включи музыку","сделай эдит","открой ютуб"):
            self.assertFalse(is_multitrack_request(text),text)

    def test_gui_starts_without_internet_or_rendering(self):
        import tkinter as tk
        from multitrack_ui import MultitrackWindow
        try:
            root=tk.Tk()
        except tk.TclError:
            self.skipTest("No graphical Windows/Tk display")
        root.withdraw()
        view=None
        try:
            view=MultitrackWindow(root)
            view.update_idletasks()
            self.assertEqual(len(view.layer_files),3)
            self.assertEqual(len(view.layer_widths),3)
            self.assertEqual(len(view.layer_opacities),3)
            self.assertFalse(view._busy)
            self.assertIsNone(view._busy_since)
            self.assertEqual(str(view._progress.cget("mode")),"indeterminate")
            self.assertEqual(view._events.qsize(),0)
        finally:
            if view is not None:
                view.destroy()
            root.destroy()

    def fixture(self,root):
        root=Path(root)
        base=root/"original.mp4"
        image=root/"logo.png"
        base.write_bytes(b"MZ-original-video"*100)
        image.write_bytes(b"\x89PNG\r\n" + b"sample"*90)
        return MultitrackProject(
            base_video=base,output_video=root/"finished.mp4",
            layers=(VisualLayer(image,start=.5,duration=1.2),),
            title="JARVIS NOVA",music=None,voiceover=None)

    def test_editable_multitrack_json_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            project=self.fixture(root)
            filename=Path(root)/"JARVIS_Multi.json"
            save_multitrack(project,filename)
            loaded=load_multitrack(filename)
            self.assertTrue(loaded.base_video.samefile(project.base_video))
            self.assertEqual(loaded.output_video.name,project.output_video.name)
            self.assertTrue(
                loaded.output_video.parent.samefile(project.output_video.parent))
            self.assertEqual(len(loaded.layers),1)
            self.assertTrue(loaded.layers[0].path.samefile(project.layers[0].path))
            self.assertEqual(loaded.layers[0].width_percent,26)
            self.assertEqual(loaded.layers[0].opacity,1.)
            with self.assertRaises(MultitrackError):
                save_multitrack(project,filename)
            corrupted=Path(root)/"corrupted.json"
            corrupted.write_text(
                '{"format":"jarvis_multitrack_edit_v1",'
                '"layers":[{"file":"../../secret.mp4"}]}',encoding="utf-8")
            with self.assertRaises(MultitrackError):
                load_multitrack(corrupted)
            with self.assertRaises(MultitrackError):
                validate_project(
                    replace(project,layers=(
                        replace(project.layers[0],start="nan"),)))

    def test_all_positions_and_multiple_track_graphs(self):
        with tempfile.TemporaryDirectory() as directory:
            project=self.fixture(directory)
            for position in POSITIONS:
                test=replace(project,layers=(
                    replace(project.layers[0],position=position),))
                validate_project(test)
                graph,video,audio=build_filter_graph(
                    test,duration=3.0,width=720,height=1280,
                    has_base_audio=True,title_index=2,silent_index=None)
                self.assertIn("overlay=",graph)
                self.assertIn("colorchannelmixer=aa=1.000",graph)
                self.assertIn("enable='between(t,0.500,1.700)'",graph)
                self.assertEqual(video,"vtitle")
                self.assertEqual(audio,"abase")
                self.assertNotIn("http",graph)

    def test_music_voice_no_audio_has_three_live_audio_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            project=self.fixture(directory)
            root=Path(directory)
            music=root/"music.mp3"
            voice=root/"voice.wav"
            music.write_bytes(b"music"*50)
            voice.write_bytes(b"voice"*50)
            project=replace(project,music=music,voiceover=voice)
            graph,video,audio=build_filter_graph(
                project,duration=4.0,width=1280,height=720,
                has_base_audio=False,title_index=2,silent_index=5)
            self.assertIn("[5:a:0]aresample",graph)
            self.assertIn("amix=inputs=3",graph)
            self.assertIn("volume=0.220[music]",graph)
            self.assertEqual(audio,"finalaudio")

    def test_banned_sources_bad_values_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            project=self.fixture(directory)
            for broken in (
                replace(project,title="A"*121),
                replace(project,layers=(replace(project.layers[0],opacity=0.0),)),
                replace(project,layers=(replace(project.layers[0],position=";rm -rf"),)),
                replace(project,layers=(replace(project.layers[0],start=89.,duration=1.),)*4),
                replace(project,output_video=project.base_video),
            ):
                with self.subTest(broken=broken), self.assertRaises(MultitrackError):
                    validate_project(broken)
            output=Path(project.output_video)
            output.write_bytes(b"user-edits")
            with self.assertRaises(MultitrackError):
                validate_project(project)
            self.assertEqual(output.read_bytes(),b"user-edits")

    def test_no_overwrite_and_pre_cancel_never_start_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            project=self.fixture(directory)
            before=hashlib.sha256(Path(project.base_video).read_bytes()).hexdigest()
            stop=threading.Event()
            stop.set()
            with self.assertRaisesRegex(MultitrackError,"отменён до чтения"):
                render_multitrack(project,cancel=stop,tools=("ffmpeg","ffprobe"))
            self.assertFalse(Path(project.output_video).exists())
            self.assertEqual(
                hashlib.sha256(Path(project.base_video).read_bytes()).hexdigest(),before)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg missing on this runner")
    def test_real_layered_mp4_with_logo_title_music_and_voice(self):
        from PIL import Image
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            base=root/"base.mp4"
            logo=root/"logo.png"
            voice=root/"voice.wav"
            music=root/"music.wav"
            Image.new("RGBA",(90,45),(255,20,30,210)).save(logo)
            def execute(args):
                proc=subprocess.run(
                    args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
                if proc.returncode:
                    self.fail(proc.stderr.decode(errors="replace")[-500:])
            execute([ffmpeg,"-hide_banner","-loglevel","error","-y",
                     "-f","lavfi","-i","color=c=blue:s=320x180:r=30:d=2.4",
                     "-f","lavfi","-i",
                     "sine=frequency=440:sample_rate=48000:duration=2.4",
                     "-t","2.4","-c:v","libx264","-pix_fmt","yuv420p",
                     "-c:a","aac",str(base)])
            for name,frequency in ((voice,880),(music,220)):
                execute([ffmpeg,"-hide_banner","-loglevel","error","-y",
                         "-f","lavfi","-i",
                         f"sine=frequency={frequency}:sample_rate=48000:duration=2.4",
                         str(name)])
            digest=hashlib.sha256(base.read_bytes()).hexdigest()
            project=MultitrackProject(
                base_video=base,output_video=root/"ready.mp4",
                layers=(VisualLayer(logo,start=.2,duration=1.5,
                                    position="top-left",width_percent=35),),
                title="NOVA",voiceover=voice,music=music)
            result=render_multitrack(project,tools=(ffmpeg,ffprobe))
            output=Path(result["output"])
            self.assertTrue(output.is_file())
            self.assertEqual(result["technical_quality"]["video_codec"],"h264")
            self.assertEqual(result["technical_quality"]["audio_codec"],"aac")
            self.assertEqual(result["technical_quality"]["width"],320)
            self.assertEqual(result["technical_quality"]["height"],180)
            self.assertEqual(len(result["layers"]),1)
            self.assertTrue(output.with_name("ready_MULTITRACK.json").is_file())
            self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(),digest)
            with self.assertRaises(MultitrackError):
                render_multitrack(project,tools=(ffmpeg,ffprobe))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg missing on this runner")
    def test_real_silent_base_with_video_picture_in_picture(self):
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            base=root/"base.mp4"
            pip=root/"pip.mp4"
            for target,color in ((base,"black"),(pip,"yellow")):
                result=subprocess.run(
                    [ffmpeg,"-hide_banner","-loglevel","error","-y",
                     "-f","lavfi","-i",
                     f"color=c={color}:s=320x180:r=30:d=2.2",
                     "-t","2.2","-c:v","libx264",
                     "-pix_fmt","yuv420p",str(target)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
                if result.returncode:
                    self.skipTest("FFmpeg test input unavailable.")
            result=render_multitrack(MultitrackProject(
                base_video=base,output_video=root/"pip_output.mp4",
                layers=(VisualLayer(pip,start=.1,duration=1.5),)),
                tools=(ffmpeg,ffprobe))
            self.assertEqual(result["technical_quality"]["audio_codec"],"aac")
            self.assertGreater(Path(result["output"]).stat().st_size,1024)


if __name__=="__main__":
    unittest.main()
