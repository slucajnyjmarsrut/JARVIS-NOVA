"""Automatic acoustic whisper reply checks with synthetic 16 kHz speech."""
import queue
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from whisper_mode import WhisperClassifier, speech_acoustics, normalize_style
from speaker import Speaker
from voice_engine import Voice
from main import Jarvis


def wave(style, gain=.015):
    rng=np.random.default_rng(27)
    t=np.arange(16000,dtype=np.float32)/16000
    signal=(rng.standard_normal(len(t)) if style=="whisper"
            else np.sin(2*np.pi*170*t))
    signal=signal*gain
    return np.round(np.clip(signal,-1,1)*32767).astype("<i2").tobytes()


class AcousticClassificationTests(unittest.TestCase):
    def test_low_airy_speech_triggers_quiet_reply(self):
        classifier=WhisperClassifier()
        rms,periodic=speech_acoustics(wave("whisper"))
        self.assertGreater(rms,.006)
        self.assertLess(periodic,.42)
        self.assertEqual(classifier.classify(wave("whisper")),"whisper")

    def test_quiet_voiced_speech_keeps_normal_volume(self):
        classifier=WhisperClassifier()
        self.assertEqual(classifier.classify(wave("normal",.016)),"normal")

    def test_normal_after_whisper_restores_normal_style(self):
        cls=WhisperClassifier()
        self.assertEqual(cls.classify(wave("whisper")),"whisper")
        self.assertEqual(cls.classify(wave("normal",.095)),"normal")
        self.assertEqual(cls.classify(wave("whisper")),"whisper")

    def test_silence_and_invalid_style_default_to_normal(self):
        self.assertEqual(WhisperClassifier().classify(bytes(32000)),"normal")
        self.assertEqual(normalize_style("anything else"),"normal")


class PlaybackTests(unittest.TestCase):
    def test_reply_captures_whisper_then_resets_for_other_ui_actions(self):
        from unittest.mock import Mock
        replied=threading.Event()
        calls=[]
        def say(text,style="normal"):
            calls.append((text,style))
            replied.set()
        app=types.SimpleNamespace(
            _closing=False,_shutdown=threading.Event(),
            voice_enabled=False,engine="none",_answer_style="whisper",
            speaker=types.SimpleNamespace(say=say),
            log=Mock(),status=types.SimpleNamespace(set=Mock()))
        Jarvis.reply(app,"Первый ответ")
        self.assertTrue(replied.wait(2))
        self.assertEqual(calls[0],("Первый ответ","whisper"))
        self.assertEqual(app._answer_style,"normal")
        replied.clear()
        Jarvis.reply(app,"Ответ по кнопке")
        self.assertTrue(replied.wait(2))
        self.assertEqual(calls[1],("Ответ по кнопке","normal"))

    def test_whisper_gain_is_reduced_but_normal_stays_full(self):
        pcm=np.ones(4800,dtype=np.float32)*.7
        normal=Speaker.soften_audio(pcm,"normal")
        hushed=Speaker.soften_audio(pcm,"whisper")
        self.assertAlmostEqual(float(np.max(normal)),.7,places=5)
        self.assertAlmostEqual(float(np.max(hushed)),.168,places=4)

    def test_silero_pcm_playback_uses_individual_style(self):
        from unittest.mock import Mock
        speaker=Speaker()
        class Model:
            def apply_tts(self,**kwargs):
                return types.SimpleNamespace(cpu=lambda:types.SimpleNamespace(
                    numpy=lambda:np.ones(480,dtype=np.float32)*.4))
        speaker.mode="silero"
        speaker.model=Model()
        sd=types.SimpleNamespace(play=Mock(),wait=Mock())
        with mock.patch.dict("sys.modules",{"sounddevice":sd}):
            speaker.say("Тише",style="whisper")
            quiet=sd.play.call_args.args[0]
            speaker.say("Обычно",style="normal")
            loud=sd.play.call_args.args[0]
        self.assertLess(float(np.max(quiet)),float(np.max(loud))*.27)
        self.assertEqual(sd.play.call_count,2)

    def test_gui_passes_style_of_specific_voice_message_to_reply(self):
        from unittest.mock import Mock
        app=types.SimpleNamespace(_closing=False,q=queue.Queue(),after=Mock(),
            handle_text=Mock(),pump=Mock(),_answer_style="normal")
        app.q.put(("heard",("открой окно","whisper")))
        Jarvis.pump(app)
        self.assertEqual(app._answer_style,"whisper")
        app.q.put(("heard",("открой окно","normal")))
        Jarvis.pump(app)
        self.assertEqual(app._answer_style,"normal")


class WhisperDeliveryTests(unittest.TestCase):
    def test_real_whisper_routing_preserves_style_until_heard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"mock")
            heard=[]
            finished=threading.Event()
            voice=Voice(lambda text:None,lambda _:None,lambda:False,
                        on_heard_styled=lambda txt,style:(heard.append((txt,style)),finished.set()))
            voice.whisper_model=types.SimpleNamespace(transcribe=lambda *a,**k:
                                                      {"text":"джарвис привет"})
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(wave("whisper"),True)
                self.assertTrue(finished.wait(3))
            self.assertEqual(heard,[("привет","whisper")])


if __name__=="__main__":
    unittest.main()
