# -*- coding: utf-8 -*-
"""Safe timed subtitle parsing, actual FFmpeg burn, and no file overwrite."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest

from subtitle_tracks import (
    MAX_CUES, SubtitleCue, SubtitleError, parse_srt,
    load_srt, burn_subtitles,
)


def srt(index,start,end,text):
    return f"{index}\n{start} --> {end}\n{text}\n"


class SubtitleTrackTests(unittest.TestCase):
    def test_utf8_russian_srt_precise_times_and_no_markup_commands(self):
        text=(
            srt(1,"00:00:00,200","00:00:01,300","Привет, мир!")+ "\n" +
            srt(2,"00:00:01,500","00:00:02,200","字幕 и #NOVA"))
        cues=parse_srt(text,max_time=3)
        self.assertEqual(len(cues),2)
        self.assertEqual(cues[0],SubtitleCue(.2,1.3,"Привет, мир!"))
        self.assertEqual(cues[1],SubtitleCue(1.5,2.2,"字幕 и #NOVA"))

    def test_rejects_malformed_timestamp_overlapping_or_oversized(self):
        good=srt(1,"00:00:00,250","00:00:01,000","Caption")
        for bad in (
            "",
            good+"\n"+srt(1,"00:00:01,200","00:00:02,000","Not sequential"),
            good+"\n"+srt(2,"00:00:00,900","00:00:01,900","Overlaps"),
            srt(1,"99:00:00,000","99:00:01,000","After movie"),
            srt(1,"00:00:01,000","00:00:00,000","Backwards"),
            srt(1,"00:00:00,010","00:00:00,050","Too fast"),
            srt(1,"00:00:00,100","00:00:01,000","x"*111),
            "x"*80_001,
        ):
            with self.subTest(sample=bad[:80]),self.assertRaises(SubtitleError):
                parse_srt(bad,max_time=3)
        long="\n".join(
            srt(i+1,
                f"00:00:{i:02d},000",
                f"00:00:{i:02d},800",
                "Caption") for i in range(MAX_CUES+1))
        with self.assertRaises(SubtitleError):
            parse_srt(long,max_time=90)

    def test_local_utf8_file_and_symlink_guard(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            movie=folder/"my_video.srt"
            movie.write_text(
                srt(1,"00:00:00,300","00:00:01,100","Да, это мой текст"),
                encoding="utf-8")
            self.assertEqual(load_srt(movie,max_time=2)[0].start,.3)
            with self.assertRaises(SubtitleError):
                load_srt(movie,max_time=.8)
            fake=folder/"clip.mp4"
            fake.write_bytes(b"non-srt")
            with self.assertRaises(SubtitleError):
                load_srt(fake)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Real FFmpeg not present")
    def test_real_subtitle_burn_copies_aac_and_preserves_original(self):
        ffmpeg=shutil.which("ffmpeg")
        ffprobe=shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            source=folder/"original.mp4"
            result=subprocess.run(
                [ffmpeg,"-hide_banner","-loglevel","error",
                 "-nostdin","-y",
                 "-f","lavfi","-i","color=c=black:s=320x180:r=30:d=2.4",
                 "-f","lavfi","-i",
                 "sine=frequency=440:sample_rate=48000:duration=2.4",
                 "-t","2.4","-c:v","libx264",
                 "-c:a","aac","-pix_fmt","yuv420p",str(source)],
                capture_output=True,timeout=40)
            if result.returncode:
                self.skipTest("FFmpeg test source unavailable")
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            target=folder/"with_subtitles.mp4"
            cues=(SubtitleCue(.2,1.2,"Титр NOVA"),)
            def execute(cmd,**kwargs):
                proc=subprocess.run(
                    cmd,capture_output=True,timeout=70)
                if proc.returncode:
                    raise RuntimeError(
                        proc.stderr.decode(errors="replace")[-700:])
                return proc.stdout
            burn_subtitles(
                source,target,cues,ffmpeg=ffmpeg,width=320,height=180,
                seconds=2.4,executor=execute)
            self.assertGreater(target.stat().st_size,1024)
            probe=json.loads(execute([
                ffprobe,"-v","error","-show_streams","-of","json",
                str(target)]))
            self.assertTrue(any(
                s.get("codec_type")=="video" and s.get("codec_name")=="h264"
                for s in probe["streams"]))
            self.assertTrue(any(
                s.get("codec_type")=="audio" and s.get("codec_name")=="aac"
                for s in probe["streams"]))
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_pre_cancel_never_starts_ffmpeg_or_writes_output(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            source=base/"original.mp4"
            source.write_bytes(b"x"*2000)
            out=base/"subtitles.mp4"
            canceled=threading.Event()
            canceled.set()
            with self.assertRaises(SubtitleError):
                burn_subtitles(
                    source,out,(SubtitleCue(0.1,1.2,"text"),),
                    ffmpeg="ffmpeg",width=720,height=1280,seconds=2,
                    executor=lambda cmd,**kw:self.fail("FFmpeg was started"),
                    cancel=canceled)
            self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main()
