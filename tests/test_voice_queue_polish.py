"""Voice reliability: full queue preserves older requests and waits for TTS.

PCM is synthetic and not persisted; no microphone, Whisper weights or network.
"""
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np  # native import before voice mocks on Windows
from voice_engine import Voice


def pcm(code):
    return bytes([code,0])*16000


class QueuePolishTests(unittest.TestCase):
    def test_full_queue_does_not_silently_evict_older_phrases(self):
        entered,release,finished=(threading.Event() for _ in range(3))
        heard=[]
        notices=[]
        def transcribe(samples,**kwargs):
            code=int(round(float(samples[0])*32768))
            if code==1:
                entered.set()
                if not release.wait(3):raise RuntimeError("test timeout")
            return {"text":{1:"джарвис первый",2:"джарвис второй",
                            3:"джарвис третий",4:"джарвис четвёртый"}[code]}
        def on_heard(text):
            heard.append(text)
            if len(heard)==3:finished.set()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"base.pt").write_bytes(b"mock")
            voice=Voice(on_heard,notices.append,lambda:False)
            voice.whisper_model=types.SimpleNamespace(transcribe=transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(1),True)
                self.assertTrue(entered.wait(2))
                for code in (2,3,4):
                    voice._try_whisper(pcm(code),True)
                self.assertEqual(len(voice.whisper_queue),2)
                self.assertEqual([p[0][0] for p in voice.whisper_queue],[2,3])
                self.assertTrue(any("очередь полна" in s for s in notices))
                release.set()
                self.assertTrue(finished.wait(4),repr(heard))
                self.assertEqual(heard,["первый","второй","третий"])

    def test_queued_recognition_waits_for_silero_to_finish(self):
        entered,release,first,finished=(threading.Event() for _ in range(4))
        speaking=threading.Event()
        heard=[]
        def transcribe(samples,**kwargs):
            code=int(round(float(samples[0])*32768))
            if code==1:
                entered.set()
                if not release.wait(3):raise RuntimeError("test timeout")
            return {"text":"джарвис первый" if code==1 else "джарвис второй"}
        def on_heard(text):
            heard.append(text)
            if text=="первый":
                speaking.set()
                first.set()
            elif text=="второй":
                finished.set()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"base.pt").write_bytes(b"mock")
            voice=Voice(on_heard,lambda s:None,speaking.is_set)
            voice.whisper_model=types.SimpleNamespace(transcribe=transcribe)
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(pcm(1),True)
                self.assertTrue(entered.wait(2))
                voice._try_whisper(pcm(2),True)
                release.set()
                self.assertTrue(first.wait(3))
                time.sleep(.15)
                self.assertEqual(heard,["первый"])
                speaking.clear()
                self.assertTrue(finished.wait(3),repr(heard))
                self.assertEqual(heard,["первый","второй"])


if __name__=="__main__":
    unittest.main()
