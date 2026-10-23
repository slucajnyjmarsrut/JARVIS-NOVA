"""No physical mic: reproduce quiet Russian words, phrase segmentation & gain."""
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from speech_capture import AdaptiveSpeechGate,prepare_whisper_audio
from voice_engine import Voice


def quiet_sine(pcm_level=12,seconds=1.0):
    n=int(16000*seconds)
    t=np.arange(n,dtype=np.float64)/16000
    return np.round(np.sin(2*np.pi*185*t)*pcm_level).astype("<i2").tobytes()


class QuietCaptureTests(unittest.TestCase):
    def test_activated_short_command_finishes_after_seven_quiet_frames(self):
        gate=AdaptiveSpeechGate()
        gate.observe(16)
        self.assertEqual(gate.observe(16),"start")
        for i in range(6):
            self.assertEqual(gate.observe(1,hangover_frames=7),"speech")
        self.assertEqual(gate.observe(1,hangover_frames=7),"end")
        self.assertFalse(gate.active)

    def test_passive_capture_retains_nine_quiet_frames(self):
        gate=AdaptiveSpeechGate()
        gate.observe(16)
        self.assertEqual(gate.observe(16),"start")
        for i in range(8):
            self.assertEqual(gate.observe(1),"speech")
        self.assertEqual(gate.observe(1),"end")

    def test_soft_pcm_starts_speech_below_old_hardcoded_24_rms_threshold(self):
        gate=AdaptiveSpeechGate()
        for _ in range(4):
            self.assertEqual(gate.observe(2),"idle")
        starts=[gate.observe(12) for _ in range(5)]
        self.assertEqual(starts.count("start"),1)
        self.assertTrue(gate.active)
        self.assertIn("end",[gate.observe(1) for _ in range(10)])
        self.assertFalse(gate.active)

    def test_brief_noise_spike_does_not_start_a_phrase(self):
        gate=AdaptiveSpeechGate()
        self.assertEqual(gate.observe(200),"idle")
        self.assertEqual(gate.observe(2),"idle")
        self.assertFalse(gate.active)

    def test_noise_floor_copes_with_different_microphones(self):
        gate=AdaptiveSpeechGate(noise_floor=110)
        self.assertEqual(gate.observe(130),"idle")
        self.assertEqual(gate.observe(135),"idle")
        self.assertEqual(gate.observe(310),"idle")
        self.assertEqual(gate.observe(310),"start")

    def test_whisper_gain_increases_soft_voice_without_clipping(self):
        original=quiet_sine(12)
        amplified=prepare_whisper_audio(original)
        self.assertGreater(float(np.sqrt(np.mean(amplified**2))),.002)
        self.assertLessEqual(float(np.max(np.abs(amplified))),.921)
        self.assertTrue(np.isfinite(amplified).all())
        self.assertEqual(len(amplified),16000)

    def test_loud_voice_not_made_louder_and_silence_not_hallucinated(self):
        loud=quiet_sine(19000)
        adjusted=prepare_whisper_audio(loud)
        self.assertLessEqual(float(np.max(np.abs(adjusted))),.921)
        self.assertEqual(len(adjusted),16000)
        self.assertEqual(float(prepare_whisper_audio(bytes(32000)).max()),0.0)
        with self.assertRaises(ValueError):
            prepare_whisper_audio(b"\x00")

    def test_short_quiet_whisper_confirmed_command_can_pass_without_vosk_wake(self):
        event=threading.Event()
        captured=[]
        heard=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"mock")
            voice=Voice(lambda t:(heard.append(t),event.set()),lambda _:None,lambda:False)
            voice.whisper_model=types.SimpleNamespace(transcribe=lambda samples,**kw:
                (captured.append((float(np.sqrt(np.mean(samples**2))),kw)),
                 {"text":"джарвис открой блокнот"})[-1])
            # 0.35 seconds is shorter than the old .5s minimum.
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(quiet_sine(12,.35),did_wake=False)
                self.assertTrue(event.wait(3))
        self.assertEqual(heard,["открой блокнот"])
        self.assertGreater(captured[0][0],.002)
        self.assertEqual(captured[0][1]["language"],"ru")

    def test_worker_detects_soft_wake_and_dispatches_whisper_transcript(self):
        finished=threading.Event()
        got=[]
        statuses=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"vosk"/"am").mkdir(parents=True)
            (root/"vosk"/"am"/"final.mdl").write_bytes(b"mock")
            (root/"base.pt").write_bytes(b"mock")
            # 4 packets of room noise, 8 packets of quiet Russian-like tone,
            # 11 packets of silence. All under old 24-PCM hard-coded gate.
            packets=[(np.ones(1600,dtype="<i2")*2).tobytes()]*4
            packets += [quiet_sine(18,.1)]*8
            packets += [bytes(3200)]*11
            class FakeStream:
                def __init__(self,**kw):self.callback=kw["callback"]
                def __enter__(self):
                    for item in packets:
                        self.callback(item,1600,None,None)
                    return self
                def __exit__(self,*args):return False
            class VoskStub:
                def SetWords(self,*a):pass
                def AcceptWaveform(self,*a):return False
                def FinalResult(self):return '{"text":""}'
            sd=types.SimpleNamespace(
                query_devices=lambda *a,**kw:{"default_samplerate":16000},
                RawInputStream=FakeStream)
            vosk=types.SimpleNamespace(SetLogLevel=lambda *_:None,
                Model=lambda *_:object(),KaldiRecognizer=lambda *_:VoskStub())
            voice=Voice(lambda text:(got.append(text),finished.set()),statuses.append,lambda:False)
            voice.whisper_model=types.SimpleNamespace(transcribe=lambda samples,**kw:
                {"text":"джарвис открой блокнот"})
            with mock.patch("voice_engine.assets",return_value=root),mock.patch.dict(
                    sys.modules,{"sounddevice":sd,"vosk":vosk}):
                voice.start()
                try:
                    self.assertTrue(finished.wait(4),repr(statuses))
                finally:
                    voice.stop()
        self.assertEqual(got,["открой блокнот"])


if __name__=="__main__":
    unittest.main()
