"""Regression for speech during slow Whisper inference (synthetic PCM only)."""
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np  # Import native Windows extension before altering sys.modules.

from voice_engine import Voice


class WhisperQueueTests(unittest.TestCase):
    def setup_voice(self,root,slow):
        captured=[]
        delivered=threading.Event()
        def send(text):
            captured.append(text)
            if len(captured)>=2:delivered.set()
        voice=Voice(send,lambda text:None,lambda:False)
        voice.whisper_model=types.SimpleNamespace(transcribe=slow)
        return voice,captured,delivered

    def test_second_awakened_phrase_is_recognized_after_first(self):
        entered=threading.Event()
        release=threading.Event()
        counter=[0]
        def transcribe(*args,**kwargs):
            counter[0]+=1
            if counter[0]==1:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("timeout in test")
                return {"text":"джарвис привет"}
            return {"text":"джарвис открой блокнот"}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"base.pt").write_bytes(b"mock")
            voice,heard,done=self.setup_voice(root,transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(bytes(32000),did_wake=True)
                self.assertTrue(entered.wait(2))
                voice._try_whisper(bytes(32000),did_wake=True)
                self.assertEqual(len(voice.whisper_queue),1)
                release.set()
                self.assertTrue(done.wait(4),repr(heard))
                self.assertEqual(heard,["привет","открой блокнот"])
                self.assertEqual(counter[0],2)

    def test_stopped_voice_drops_queued_audio_and_late_results(self):
        entered=threading.Event()
        release=threading.Event()
        completed=threading.Event()
        def transcribe(*args,**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("timeout")
            completed.set()
            return {"text":"джарвис посмотри в камеру"}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"base.pt").write_bytes(b"mock")
            seen=[]
            voice=Voice(seen.append,lambda _:None,lambda:False,
                        on_vision_audio=lambda _,src:seen.append(src))
            voice.whisper_model=types.SimpleNamespace(transcribe=transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(bytes(32000),did_wake=True)
                self.assertTrue(entered.wait(2))
                voice._try_whisper(bytes(32000),did_wake=True)
                self.assertEqual(len(voice.whisper_queue),1)
                voice.stop()
                self.assertFalse(voice.whisper_queue)
                release.set()
                self.assertTrue(completed.wait(2))
                time.sleep(.04)
                self.assertFalse(seen)

    def test_background_utterance_is_not_queued_without_activation(self):
        entered=threading.Event()
        release=threading.Event()
        def transcribe(*args,**kwargs):
            entered.set()
            release.wait(3)
            return {"text":"джарвис привет"}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"base.pt").write_bytes(b"mock")
            voice,_,_=self.setup_voice(root,transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(bytes(32000),did_wake=True)
                self.assertTrue(entered.wait(2))
                voice._try_whisper(bytes(32000),did_wake=False)
                self.assertFalse(voice.whisper_queue)
                release.set()


if __name__=="__main__":
    unittest.main()
