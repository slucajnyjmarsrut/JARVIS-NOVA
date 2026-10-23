"""Real voice-worker input telemetry with fake audio I/O, no physical mic/model."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np  # Load native extension before patch.dict (Windows).

from voice_engine import Voice


class VoiceTelemetryTests(unittest.TestCase):
    def drive_worker(self, callback):
        statuses=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"vosk"/"am").mkdir(parents=True)
            (root/"vosk"/"am"/"final.mdl").write_bytes(b"fixture")
            # Exact 100ms of int16 input with 25% of full scale.
            samples=(np.ones(1600,dtype="<i2")*8192).tobytes()
            fake_vosk=types.SimpleNamespace(
                SetLogLevel=lambda *_:None,
                Model=lambda *_:object(),
                KaldiRecognizer=lambda *_:types.SimpleNamespace(
                    SetWords=lambda *_:None,
                    AcceptWaveform=lambda *_:False,
                ))
            class FakeStream:
                def __init__(self,**kwargs):
                    self.callback=kwargs["callback"]
                def __enter__(self):
                    self.callback(samples,1600,None,None)
                    return self
                def __exit__(self,*args):
                    return False
            fake_sd=types.SimpleNamespace(
                query_devices=lambda *args,**kwargs:{"default_samplerate":16000},
                RawInputStream=FakeStream,
            )
            voice=Voice(lambda _:None,statuses.append,lambda:False,
                        on_audio_level=lambda value:callback(voice,value))
            voice.running=True
            voice._generation=1
            with mock.patch("voice_engine.assets",return_value=root),mock.patch.dict(
                    sys.modules,{"sounddevice":fake_sd,"vosk":fake_vosk}):
                voice._run(1)
        return statuses

    def test_reports_bounded_actual_signal_fraction(self):
        readings=[]
        def collect(voice,value):
            readings.append(value)
            voice.running=False
        statuses=self.drive_worker(collect)
        self.assertEqual(len(readings),1)
        self.assertAlmostEqual(readings[0],.25,places=4)
        self.assertFalse(any(s.startswith("Ошибка микрофона:") for s in statuses))

    def test_dashboard_callback_failure_cannot_crash_microphone_worker(self):
        def failing(voice,value):
            voice.running=False
            raise RuntimeError("pretend UI was destroyed")
        statuses=self.drive_worker(failing)
        self.assertFalse(any(s.startswith("Ошибка микрофона:") for s in statuses))


if __name__=="__main__":
    unittest.main()
