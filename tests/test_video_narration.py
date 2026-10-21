# -*- coding: utf-8 -*-
"""Russian Silero narration tests; real FFmpeg exercised when provisioned."""
from pathlib import Path
import json
import tempfile
import unittest
import wave

import numpy as np
from video_narration import (NarrationError, narration_text,
                             synthesize_narration, mix_local_narration,
                             try_narrate_video)
from viral_studio import ffmpeg_tools, ViralStudioError, _execute


class _SileroStub:
    def __init__(self, seconds=1.):
        self.seconds=seconds
        self.words=[]
    def synthesize(self, text):
        self.words.append(text)
        t=np.linspace(0.,self.seconds,int(48000*self.seconds),endpoint=False)
        return (np.sin(t*2*np.pi*320)*.24).astype(np.float32)


class VoiceoverTests(unittest.TestCase):
    def test_wav_is_real_48khz_mono_and_no_raw_source_is_modified(self):
        with tempfile.TemporaryDirectory() as td:
            wav=Path(td)/"generated.wav"
            stub=_SileroStub(1.2)
            duration=synthesize_narration("Привет, это тест.",wav,3.,synthesizer=stub)
            self.assertAlmostEqual(duration,1.2,places=2)
            with wave.open(str(wav),"rb") as input:
                self.assertEqual(input.getframerate(),48000)
                self.assertEqual(input.getnchannels(),1)
                self.assertEqual(input.getsampwidth(),2)
                self.assertGreater(input.getnframes(),48000)
            self.assertEqual(stub.words,["Привет, это тест."])
            with self.assertRaises(NarrationError):
                synthesize_narration("Еще раз",wav,3.,synthesizer=stub)

    def test_long_audio_rejected_not_cut_off_during_sentence(self):
        with tempfile.TemporaryDirectory() as td:
            wav=Path(td)/"too_long.wav"
            with self.assertRaises(NarrationError):
                synthesize_narration("Привет!",wav,1.3,synthesizer=_SileroStub(2.5))
            self.assertFalse(wav.exists())
            with self.assertRaises(NarrationError):
                synthesize_narration("",wav,5.,synthesizer=_SileroStub())

    def test_bad_pcm_rejected_and_original_video_not_deleted(self):
        class Bad:
            def synthesize(self,*_):
                return np.array([float("nan"),.4],dtype=np.float32)
        with tempfile.TemporaryDirectory() as td:
            wav=Path(td)/"bad.wav"
            with self.assertRaises(NarrationError):
                synthesize_narration("Слово",wav,2.,synthesizer=Bad())
            self.assertFalse(wav.exists())

    def test_short_narration_is_derived_from_user_script(self):
        from types import SimpleNamespace
        brief=SimpleNamespace(script="Короткий текст",hook="Начало",
                              call_to_action="Подпишись")
        self.assertEqual(narration_text(brief),"Начало Подпишись")
        brief.script="Небольшой авторский текст по теме ролика."
        self.assertEqual(narration_text(brief),brief.script)
        brief.script="Очень длинно "*50
        self.assertEqual(narration_text(brief),"Начало Подпишись")

    def test_failed_voiceover_preserves_final_video(self):
        with tempfile.TemporaryDirectory() as td:
            video=Path(td)/"finished.mp4"
            video.write_bytes(b"original MP4 bytes")
            result=try_narrate_video(video,object(),synth=_SileroStub())
            self.assertFalse(result["narrated"])
            self.assertEqual(video.read_bytes(),b"original MP4 bytes")

    def test_real_ffmpeg_silero_stub_mix_and_codec_verification(self):
        try:
            ffmpeg,ffprobe=ffmpeg_tools()
        except ViralStudioError:
            self.skipTest("FFmpeg not provisioned on this runner")
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"input.mp4"
            _execute([ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
                     "-f","lavfi","-i","color=c=green:s=180x320:r=16:d=3",
                     "-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
                     "-t","3","-c:v","libx264","-pix_fmt","yuv420p",
                     "-c:a","aac","-shortest",str(output)],timeout=40)
            before=output.stat().st_size
            meta=mix_local_narration(output,"Привет!",synthesizer=_SileroStub(1.2),
                                     tools=(ffmpeg,ffprobe))
            self.assertTrue(meta["narrated"])
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size,1000)
            self.assertNotEqual(output.stat().st_size,before)
            from smart_montage import verify_output_media
            verified=verify_output_media(output,ffprobe,3.)
            self.assertTrue(verified["quality_checked"])
            self.assertEqual(verified["audio_codec"],"aac")
            self.assertFalse(list(Path(td).glob("jarvis_narration_*")))

if __name__=="__main__":
    unittest.main()
