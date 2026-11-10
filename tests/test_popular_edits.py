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
)
from pro_montage import ProOptions, validate_options, color_filter


class PopularEditTests(unittest.TestCase):
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
            self.assertEqual(
                [p.resolve() for p in source_clips(source)],
                [p.resolve() for p in files])
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


if __name__ == "__main__":
    unittest.main()
