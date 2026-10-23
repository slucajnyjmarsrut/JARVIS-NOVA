"""Latency controls for local Russian assistant, without external models/devices."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock,patch

import numpy as np  # Pre-load native extension before sys.modules interception.

from local_chat import LocalChat
from voice_engine import Voice


class QuickVoiceTests(unittest.TestCase):
    def test_sensitivity_is_bounded_and_stored(self):
        voice=Voice(lambda _:None,lambda _:None,lambda:False)
        voice.set_sensitivity(1.8)
        self.assertAlmostEqual(voice.sensitivity,1.8)
        for v in (0,.5,2.5):
            with self.assertRaises(ValueError):
                voice.set_sensitivity(v)

    def test_whisper_warmup_and_first_command_share_one_model_instance(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)
            (p/"base.pt").write_bytes(b"test-only")
            called=[]
            loading=threading.Event()
            unblock=threading.Event()
            model=types.SimpleNamespace(transcribe=lambda *a,**kw:{"text":"джарвис привет"})
            def load(*args,**kwargs):
                called.append(1)
                loading.set()
                if not unblock.wait(2):
                    raise AssertionError("Model warmup blocked")
                return model
            voice=Voice(lambda _:None,lambda _:None,lambda:False)
            voice.running=True
            voice._generation=12
            with patch("voice_engine.assets",return_value=p),patch.dict(
                    sys.modules,{"whisper":types.SimpleNamespace(load_model=load)}):
                voice._prewarm_whisper(12)
                self.assertTrue(loading.wait(2))
                completed=[]
                thread=threading.Thread(
                    target=lambda:completed.append(voice._get_whisper_model(p/"base.pt")))
                thread.start()
                unblock.set()
                thread.join(3)
                self.assertFalse(thread.is_alive())
                voice._whisper_warm_thread.join(3)
            self.assertEqual(len(called),1)
            self.assertIs(completed[0],model)

    def test_cpu_recognition_uses_bounded_search_and_russian(self):
        got=threading.Event()
        kwargs=[]
        heard=[]
        with TemporaryDirectory() as folder:
            p=Path(folder)
            (p/"base.pt").write_bytes(b"mock")
            model=types.SimpleNamespace(
                transcribe=lambda sample,**kw:
                    (kwargs.append(kw),{"text":"джарвис как дела"})[-1])
            v=Voice(lambda s:(heard.append(s),got.set()),lambda s:None,lambda:False)
            v.whisper_model=model
            with patch("voice_engine.assets",return_value=p):
                v._try_whisper((np.ones(16000,dtype="<i2")*1000).tobytes(),False)
                self.assertTrue(got.wait(3))
        self.assertEqual(heard,["как дела"])
        self.assertEqual(kwargs[0]["beam_size"],2)
        self.assertEqual(kwargs[0]["best_of"],1)
        self.assertEqual(kwargs[0]["language"],"ru")

    def test_qwen_responds_briefly_without_hidden_thinking(self):
        payload=[]
        chat=LocalChat(types.SimpleNamespace(config=types.SimpleNamespace(model="qwen3-vl:2b-instruct"),
                          start=lambda:"http://127.0.0.1:11434"),
                       requester=lambda endpoint,data:
                           (payload.append(data),{"message":{"content":"Готово."}})[-1])
        self.assertEqual(chat.ask("Расскажи про модель"),"Готово.")
        self.assertFalse(payload[0]["think"])
        self.assertEqual(payload[0]["keep_alive"],"20m")
        self.assertLessEqual(payload[0]["options"]["num_predict"],120)
        self.assertEqual(payload[0]["stream"],False)


if __name__=="__main__":
    unittest.main()
