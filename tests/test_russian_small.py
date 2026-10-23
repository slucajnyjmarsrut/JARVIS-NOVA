"""Russian speech quality: multilingual small default with offline base fallback.

Uses synthetic PCM16 + fake model objects. Real checkpoint validation runs
separately on the Windows packaging runner.
"""
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from voice_engine import Voice
from verify_models import get_small_whisper_digest


def pcm():
    t=np.arange(16000)/16000.0
    return np.round(1200*np.sin(2*np.pi*220*t)).astype("<i2").tobytes()


class RussianAccuracyTests(unittest.TestCase):
    def test_default_mode_and_safe_switch(self):
        voice=Voice(lambda _:None,lambda _:None,lambda:False)
        self.assertEqual(voice.recognition_mode,"balanced")
        voice.set_recognition_mode("fast")
        self.assertEqual(voice.recognition_mode,"fast")
        voice.set_recognition_mode("balanced")
        self.assertEqual(voice.recognition_mode,"balanced")
        voice.set_recognition_mode("accurate")
        for candidate in ("", "turbo", "remote"):
            with self.assertRaises(ValueError):
                voice.set_recognition_mode(candidate)

    def test_official_small_digest_is_validated(self):
        sha="a"*64
        fake=types.SimpleNamespace(_MODELS={
            "small":"https://example.test/models/"+sha+"/small.pt"})
        self.assertEqual(get_small_whisper_digest(fake),sha)
        for url in ("https://example.test/small.pt",
                    "https://example.test/models/invalid/small.pt"):
            with self.assertRaises(RuntimeError):
                get_small_whisper_digest(types.SimpleNamespace(
                    _MODELS={"small":url}))

    def test_active_command_uses_small_and_preserves_russian_words(self):
        event=threading.Event()
        heard=[]
        loader=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"base.pt").write_bytes(b"unit stub")
            (root/"small.pt").write_bytes(b"unit stub")
            class Model:
                def __init__(self,name):self.name=name
                def transcribe(self,samples,**kwargs):
                    loader.append((self.name,kwargs["language"],kwargs["beam_size"]))
                    if self.name=="small":
                        return {"text":"джарвис открой браузер",
                                "segments":[{"avg_logprob":-.12,
                                             "no_speech_prob":0.01,
                                             "compression_ratio":1.0}]}
                    return {"text":"джарвис открой бронз"}
            voice=Voice(lambda value:(heard.append(value),event.set()),
                        lambda _:None,lambda:False)
            voice.recognition_mode="accurate"
            voice._get_small_model=lambda path:Model("small")
            voice._get_whisper_model=lambda path:Model("base")
            voice.until=time.monotonic()+8
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(),False)
                self.assertTrue(event.wait(3))
        self.assertEqual(heard,["открой браузер"])
        self.assertEqual(loader,[("small","ru",2)])

    def test_fast_mode_remains_base_without_second_model_load(self):
        event=threading.Event()
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"base.pt").write_bytes(b"mock")
            (root/"small.pt").write_bytes(b"mock")
            voice=Voice(lambda _:event.set(),lambda _:None,lambda:False)
            voice.recognition_mode="fast"
            voice.until=time.monotonic()+8
            voice._get_small_model=lambda _:self.fail("small loaded in fast mode")
            voice._get_whisper_model=lambda path:types.SimpleNamespace(
                transcribe=lambda audio,**kwargs:(
                    calls.append(kwargs),{"text":"джарвис привет"})[-1])
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(),False)
                self.assertTrue(event.wait(3))
        self.assertEqual(len(calls),1)

    def test_missing_small_model_uses_base_even_in_accurate_mode(self):
        event=threading.Event()
        paths=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"base.pt").write_bytes(b"mock")
            voice=Voice(lambda _:event.set(),lambda _:None,lambda:False)
            voice.until=time.monotonic()+8
            voice._get_small_model=lambda _:self.fail("should not be called")
            def fallback(path):
                paths.append(path.name)
                return types.SimpleNamespace(
                    transcribe=lambda *a,**kw:{"text":"джарвис привет"})
            voice._get_whisper_model=fallback
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(),False)
                self.assertTrue(event.wait(3))
        self.assertEqual(paths,["base.pt"])

    def test_stopped_microphone_does_not_dispatch_small_result(self):
        entered=threading.Event()
        resume=threading.Event()
        output=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"base.pt").write_bytes(b"stub")
            (root/"small.pt").write_bytes(b"stub")
            voice=Voice(output.append,lambda _:None,lambda:False)
            voice.until=time.monotonic()+8
            def transcribe(*a,**kw):
                entered.set()
                resume.wait(3)
                return {"text":"джарвис открой блокнот"}
            voice.recognition_mode="accurate"
            voice._get_small_model=lambda _:types.SimpleNamespace(transcribe=transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(),False)
                self.assertTrue(entered.wait(2))
                voice.stop()
                resume.set()
                time.sleep(.1)
        self.assertEqual(output,[])


if __name__=="__main__":
    unittest.main()
