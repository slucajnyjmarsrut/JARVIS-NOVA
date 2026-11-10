# -*- coding: utf-8 -*-
"""Popular video edit presets and actual FFmpeg export without touching footage."""
from pathlib import Path
from unittest import mock
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest

from popular_edits import (
    STYLES, STYLE_BY_NAME, PopularEditError,
    source_clips, select_style, speed_for,
    _segment_filter, render_popular_edit, verify_edit_output_media,
    is_popular_edit_request,
)
from pro_montage import ProOptions, validate_options, color_filter


class PopularEditTests(unittest.TestCase):
    def test_explicit_edit_commands_open_guided_studio_only(self):
        for request in ("сделай эдит", "Джарвис, сделай эдит для тиктока",
                        "хочу эдит", "смонтируй видео", "сделай монтаж"):
            self.assertTrue(is_popular_edit_request(request),request)
        for ordinary in ("как работает монтаж", "создай аккаунт в ютубе",
                         "скачай мою модель", "закажи обед"):
            self.assertFalse(is_popular_edit_request(ordinary),ordinary)

    def test_many_distinct_real_styles_and_platform_aspects(self):
        self.assertEqual(len(STYLES),16)
        self.assertEqual(len(STYLE_BY_NAME),16)
        for style in STYLES:
            with self.subTest(style=style.name):
                self.assertEqual(select_style(style.name),style)
                self.assertTrue(all(size % 2 == 0 for size in style.size))
                self.assertLessEqual(max(style.size),1280)
                self.assertGreaterEqual(style.seconds,.75)
                validate_options(ProOptions(
                    color=style.color, transition=style.transition_seconds,
                    transition_style=style.transition))
                self.assertTrue(color_filter(style.color) or style.color=="none")
                filtergraph=_segment_filter(
                    style,speed=speed_for(style,0),seconds=style.seconds,
                    has_audio=True)
                self.assertIn("crop=",filtergraph)
                self.assertIn("atempo=",filtergraph)
                self.assertNotIn("http",filtergraph)
        self.assertEqual(select_style("tiktok").size,(720,1280))
        self.assertEqual(select_style("reels").size,(720,1280))
        self.assertEqual(select_style("cinematic").size,(1280,720))
        self.assertEqual(select_style("podcast").size,(960,960))
        self.assertEqual(select_style("product").size,(864,1080))
        self.assertEqual(speed_for(select_style("velocity"),0),.65)
        self.assertEqual(speed_for(select_style("velocity"),1),1.8)

    def test_verifier_accepts_wide_square_portrait_and_refuses_wrong_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/"rendered.mp4"
            video.write_bytes(b"fake-mp4"*200)
            for size in ((720,1280),(1280,720),(960,960),(864,1080)):
                with self.subTest(size=size):
                    payload={"format":{"duration":"3.1"},"streams":[
                        {"codec_type":"video","codec_name":"h264",
                         "width":size[0],"height":size[1]},
                        {"codec_type":"audio","codec_name":"aac"}]}
                    data=verify_edit_output_media(
                        video,"ffprobe",size=size,expected_seconds=3.0,
                        executor=lambda argv,**kwargs: json.dumps(payload).encode())
                    self.assertEqual((data["width"],data["height"]),size)
                    with self.assertRaises(PopularEditError):
                        verify_edit_output_media(
                            video,"ffprobe",size=(640,360),
                            expected_seconds=3.0,
                            executor=lambda argv,**kwargs: json.dumps(payload).encode())

    def test_invalid_or_model_injected_style_cannot_be_used_as_filter(self):
        for value in ("", "../danger", "tiktok;rm", "fade=evil", "glitch;upload"):
            with self.assertRaises(PopularEditError):
                select_style(value)
        with self.assertRaises(ValueError):
            validate_options(ProOptions(transition_style="malicious;movie=url"))
        with self.assertRaises(ValueError):
            color_filter("shell(\"evil\")")

    def test_owned_folder_enforces_maximum_and_keeps_original_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(PopularEditError):
                source_clips(root)
            source=root/"source"
            source.mkdir()
            files=[]
            for i in range(10):
                path=source/f"{i:02d}.mp4"
                path.write_bytes(b"x"*2500)
                files.append(path)
            actual=source_clips(source)
            self.assertEqual([p.name for p in actual],[p.name for p in files])
            self.assertTrue(all(a.samefile(b) for a,b in zip(actual,files)))
            extra=source/"11.mp4"
            extra.write_bytes(b"x"*2500)
            with self.assertRaises(PopularEditError):
                source_clips(source)

    def test_symlink_source_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            real=root/"clips"
            real.mkdir()
            (real/"a.mp4").write_bytes(b"x"*2500)
            alias=root/"alias"
            try:
                alias.symlink_to(real,target_is_directory=True)
            except (OSError,NotImplementedError):
                self.skipTest("Windows runner lacks symlink privilege")
            with self.assertRaises(PopularEditError):
                source_clips(alias)

    def test_no_write_inside_source_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            clip=raw/"a.mp4"
            clip.write_bytes(b"x"*2500)
            target=root/"out.mp4"
            target.write_bytes(b"existing")
            with self.assertRaises(PopularEditError):
                render_popular_edit(raw,target,style="shorts",tools=("ffmpeg","ffprobe"))
            self.assertEqual(target.read_bytes(),b"existing")
            with self.assertRaises(PopularEditError):
                render_popular_edit(raw,raw/"out.mp4",style="shorts",
                                    tools=("ffmpeg","ffprobe"))
            with self.assertRaises(PopularEditError):
                render_popular_edit(raw,root/"out.mov",style="shorts",
                                    tools=("ffmpeg","ffprobe"))

    def test_pre_cancel_never_reads_or_edits_user_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=root/"raw"
            raw.mkdir()
            clip=raw/"a.mp4"
            clip.write_bytes(b"x"*2500)
            before=hashlib.sha256(clip.read_bytes()).hexdigest()
            canceled=threading.Event()
            canceled.set()
            with self.assertRaisesRegex(PopularEditError,"отменён"):
                render_popular_edit(
                    raw,root/"out.mp4",style="meme",cancel=canceled,
                    tools=("ffmpeg","ffprobe"))
            self.assertEqual(hashlib.sha256(clip.read_bytes()).hexdigest(),before)
            self.assertFalse((root/"out.mp4").exists())

    def test_cancel_during_large_export_rolls_back_mp4_and_sidecar(self):
        from popular_edits import _copy_export_with_cancel
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            original=base/"raw"
            original.mkdir()
            clip=original/"01.mp4"
            clip.write_bytes(b"private source"*250)
            before=hashlib.sha256(clip.read_bytes()).hexdigest()
            out=base/"result.mp4"
            event=threading.Event()

            def segment_render(args, **_):
                Path(args[-1]).write_bytes(b"video chunk"*300)

            def final_render(parts,lengths,output,ffmpeg,**_):
                Path(output).write_bytes(b"rendered-video"*400)
                return {"expected_seconds":1.8}

            def interrupt_during_video_copy(source, destination, **kwargs):
                if Path(source.name).name=="finished.mp4":
                    event.set()
                return _copy_export_with_cancel(source,destination,**kwargs)

            with mock.patch("viral_studio._probe",
                            side_effect=[(2.5,True),(1.8,True)]), \
                 mock.patch("popular_edits.finish_video",
                            side_effect=final_render), \
                 mock.patch("popular_edits.verify_edit_output_media",
                            return_value={"quality_checked":True}), \
                 mock.patch("popular_edits._copy_export_with_cancel",
                            side_effect=interrupt_during_video_copy):
                with self.assertRaisesRegex(PopularEditError,"Экспорт отменён"):
                    render_popular_edit(
                        original,out,style="shorts",cancel=event,
                        tools=("ffmpeg","ffprobe"),executor=segment_render)
            self.assertFalse(out.exists())
            self.assertFalse(base.joinpath("result_EDL.json").exists())
            self.assertEqual(hashlib.sha256(clip.read_bytes()).hexdigest(),before)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg not available to runner")
    def test_real_ffmpeg_exports_verified_mp4_with_original_untouched(self):
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"my-originals"
            source.mkdir()
            clip=source/"01.mp4"
            created=subprocess.run(
                [ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y",
                 "-f","lavfi","-i","color=c=blue:s=320x180:r=30:d=2.1",
                 "-c:v","libx264","-pix_fmt","yuv420p",str(clip)],
                capture_output=True,timeout=40)
            if created.returncode:
                self.skipTest("FFmpeg lacks libx264: " +
                              created.stderr.decode(errors="replace")[-140:])
            digest=hashlib.sha256(clip.read_bytes()).hexdigest()
            result=render_popular_edit(
                source,root/"meme.mp4",style="meme",tools=(ffmpeg,ffprobe))
            movie=Path(result["output"])
            self.assertTrue(movie.is_file())
            self.assertGreater(movie.stat().st_size,1000)
            self.assertEqual(result["size"],[720,1280])
            self.assertEqual(result["style"],"meme")
            self.assertEqual(len(result["segments"]),1)
            self.assertEqual(hashlib.sha256(clip.read_bytes()).hexdigest(),digest)
            edl=movie.with_name("meme_EDL.json")
            self.assertTrue(edl.is_file())
            self.assertFalse(json.loads(edl.read_text(encoding="utf-8"))["published"])
            with self.assertRaises(PopularEditError):
                render_popular_edit(
                    source,movie,style="meme",tools=(ffmpeg,ffprobe))
            self.assertEqual(hashlib.sha256(clip.read_bytes()).hexdigest(),digest)


    @unittest.skipUnless(shutil.which("ffmpeg"),
                         "Actual FFmpeg required to evaluate filter expressions")
    def test_every_preset_filter_graph_is_accepted_by_real_ffmpeg(self):
        """Exercise the color, crop and speed expressions of all 16 presets."""
        ffmpeg=shutil.which("ffmpeg")
        for style in STYLES:
            with self.subTest(style=style.name):
                command=[
                    ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
                    "-f","lavfi","-i",
                    "color=c=blue:s=320x180:r=30:d=0.4",
                    "-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                    "-filter_complex",_segment_filter(
                        style,speed=speed_for(style,0),
                        seconds=style.seconds,has_audio=False),
                    "-map","[v]","-map","[a]",
                    "-frames:v","1","-t","0.15","-f","null","-",
                ]
                result=subprocess.run(command,capture_output=True,timeout=40)
                self.assertEqual(
                    result.returncode,0,
                    result.stderr.decode(errors="replace")[-500:])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg and FFprobe required")
    def test_every_transition_effect_renders_a_real_h264_mp4(self):
        """Every advertised transition must be accepted by FFmpeg."""
        from pro_montage import SAFE_TRANSITIONS, finish_video
        ffmpeg=shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            videos=[]
            for idx,shade in enumerate(("blue","yellow")):
                clip=root/f"source{idx}.mp4"
                command=[ffmpeg,"-hide_banner","-loglevel","error","-y",
                         "-f","lavfi","-i",
                         f"color=c={shade}:s=160x288:r=30:d=1.35",
                         "-f","lavfi","-i",
                         "anullsrc=r=48000:cl=stereo",
                         "-t","1.35","-c:v","libx264",
                         "-pix_fmt","yuv420p","-c:a","aac",str(clip)]
                result=subprocess.run(command,capture_output=True,timeout=40)
                if result.returncode:
                    self.skipTest("FFmpeg unavailable for real transition renders")
                videos.append(clip)
            def run(cmd,timeout=240,cancel=None):
                p=subprocess.run(cmd,capture_output=True,timeout=timeout)
                if p.returncode:
                    raise RuntimeError(
                        p.stderr.decode(errors="replace")[-450:])
                return p.stdout
            for transition in sorted(SAFE_TRANSITIONS):
                with self.subTest(transition=transition):
                    movie=root/f"{transition}.mp4"
                    finish_video(
                        videos,[1.35,1.35],movie,ffmpeg,
                        options=ProOptions(
                            transition=.2,transition_style=transition),
                        executor=run)
                    self.assertGreater(movie.stat().st_size,1000)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Actual FFmpeg and FFprobe required")
    def test_real_two_clips_wide_vertical_velocity_and_fades(self):
        """Cover multiple real render paths, including silent inputs and speed."""
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"originals"
            folder.mkdir()
            for name,color,audio in (
                ("01.mp4","red",True),("02.mp4","blue",False)):
                cmd=[ffmpeg,"-hide_banner","-loglevel","error","-y",
                     "-f","lavfi","-i",
                     f"color=c={color}:s=320x180:r=30:d=3.8"]
                if audio:
                    cmd+=["-f","lavfi","-i",
                          "sine=frequency=440:sample_rate=48000:duration=3.8"]
                cmd+=["-c:v","libx264","-pix_fmt","yuv420p"]
                if audio:
                    cmd+=["-c:a","aac"]
                cmd+=["-t","3.8",str(folder/name)]
                result=subprocess.run(cmd,capture_output=True,timeout=50)
                if result.returncode:
                    self.skipTest("FFmpeg test input encode not supported")
            digests={
                p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.iterdir()}
            for style in ("velocity","gaming","retro","reels"):
                with self.subTest(style=style):
                    out=root/(style+".mp4")
                    info=render_popular_edit(folder,out,style=style,
                                             tools=(ffmpeg,ffprobe))
                    self.assertTrue(out.is_file())
                    self.assertEqual(len(info["segments"]),2)
                    self.assertEqual(tuple(info["size"]),
                                     select_style(style).size)
                    self.assertTrue(info["technical_quality"]["quality_checked"])
                    self.assertEqual(info["segments"][1]["audio"],"silence")
                    data=json.loads(out.with_name(
                        out.stem+"_EDL.json").read_text(encoding="utf-8"))
                    self.assertFalse(data["published"])
            for p in folder.iterdir():
                self.assertEqual(
                    hashlib.sha256(p.read_bytes()).hexdigest(),digests[p.name])

if __name__ == "__main__":
    unittest.main()
