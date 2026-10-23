"""Simulate Windows/Bluetooth microphone disconnects without real hardware."""
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock
import numpy as np  # native Windows extension before fake modules

from voice_engine import Voice


class MicrophoneRecoveryTests(unittest.TestCase):
    def run_worker(self, *, fail_open=1, forever=False, on_ready=None, device=None):
        statuses=[]
        opened=[]
        device_queries=[]
        calls=[0]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"vosk"/"am").mkdir(parents=True)
            (root/"vosk"/"am"/"final.mdl").write_bytes(b"mock-only")
            samples=(np.ones(1600,dtype="<i2")*450).tobytes()
            class FakeStream:
                def __init__(self,**kw):
                    self.callback=kw["callback"]
                    opened.append(kw["device"])
                def __enter__(self):
                    calls[0]+=1
                    if forever or calls[0]<=fail_open:
                        raise OSError("Bluetooth microphone disconnected")
                    # A 48-kHz device supplies 4800 samples/100ms. The
                    # buffered FIR converter needs the next packet as context.
                    rate=48000 if device==7 else 16000
                    frame=(np.ones(rate//10,dtype="<i2")*450).tobytes()
                    self.callback(frame,rate//10,None,None)
                    if rate!=16000:
                        self.callback(frame,rate//10,None,None)
                    return self
                def __exit__(self,*exc):
                    return False
            def device_info(name=None,kind=None):
                device_queries.append(name)
                return {"default_samplerate":48000 if name==7 else 16000}
            sd=types.SimpleNamespace(
                PortAudioError=OSError,
                query_devices=device_info,
                RawInputStream=FakeStream)
            vosk=types.SimpleNamespace(
                SetLogLevel=lambda *_:None,
                Model=lambda *_:object(),
                KaldiRecognizer=lambda *_:types.SimpleNamespace(
                    SetWords=lambda *_:None,AcceptWaveform=lambda *_:False))
            voice=Voice(lambda _:None,statuses.append,lambda:False)
            voice.running=True
            voice._generation=9
            voice.input_device=device
            def level_callback(level):
                if on_ready is not None:
                    on_ready(voice)
                voice.running=False  # bound execution; one real audio frame
            voice.on_audio_level=level_callback
            waits=[]
            def wait(gen,seconds):
                waits.append(seconds)
                if forever:
                    voice.running=False
                    return False
                voice.activate() if calls[0]==1 else None
                return True
            voice._wait_for_mic=wait
            with mock.patch("voice_engine.assets",return_value=root),mock.patch.dict(
                    sys.modules,{"sounddevice":sd,"vosk":vosk}):
                voice._run(9)
        return voice,statuses,opened,waits,device_queries

    def test_reopens_device_after_one_portaudio_failure_and_receives_frames(self):
        activated=[]
        def on_ready(voice):
            activated.append(voice.until>time.monotonic())
        voice,status,opened,waits,queries=self.run_worker(
            fail_open=1,on_ready=on_ready,device=7)
        self.assertEqual(opened,[7,7])
        self.assertEqual(queries,[7,7])
        self.assertEqual(len(waits),1)
        self.assertTrue(any("переподключение 1/5" in x for x in status))
        self.assertTrue(any("Vosk готов" in x for x in status))
        self.assertEqual(activated,[True], "F9 during reconnection should be honored")
        self.assertFalse(any(x.startswith("Ошибка микрофона:") for x in status))

    def test_stopping_during_backoff_is_quick_and_no_permanent_error(self):
        _,status,opened,waits,_=self.run_worker(forever=True)
        self.assertEqual(len(opened),1)
        self.assertEqual(waits,[.6])
        self.assertFalse(any(x.startswith("Ошибка микрофона:") for x in status))

    def test_missing_default_input_has_no_silent_microphone_switch(self):
        voice,status,opened,_,queries=self.run_worker(fail_open=2,device=None)
        self.assertEqual(opened,[None,None,None])
        self.assertEqual(queries,[None,None,None])
        self.assertFalse(any(x.startswith("Ошибка микрофона:") for x in status))
        self.assertIsNone(voice.input_device)

    def test_six_consecutive_failures_show_actionable_permanent_error(self):
        voice,status,opened,waits,_=self.run_worker(fail_open=6,device=7)
        self.assertEqual(len(opened),6)
        self.assertEqual(len(waits),5)
        self.assertTrue(status[-1].startswith("Ошибка микрофона:"))
        self.assertIn("после 5 попыток",status[-1])
        self.assertFalse(voice.running)
        self.assertFalse(voice.mic_ready)

    def test_microphone_lost_rearms_active_listening_window(self):
        voice=Voice(lambda _:None,lambda _:None,lambda:False)
        voice.running=True
        voice._generation=5
        voice.mic_ready=True
        voice.until=time.monotonic()+4
        self.assertTrue(voice._mic_disconnected(5))
        self.assertFalse(voice.mic_ready)
        self.assertTrue(voice._manual_pending)
        self.assertEqual(voice.until,0)
        self.assertTrue(voice._mark_mic_ready(5,44100))
        self.assertGreater(voice.until,time.monotonic()+7)

    def test_stale_generation_disconnection_is_noop(self):
        voice=Voice(lambda _:None,lambda _:None,lambda:False)
        voice.running=True
        voice._generation=5
        voice.mic_ready=True
        self.assertFalse(voice._mic_disconnected(4))
        self.assertTrue(voice.mic_ready)


if __name__=="__main__":
    unittest.main()
