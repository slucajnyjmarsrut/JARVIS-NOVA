"""Microphone packet-gap regression with in-memory fake PortAudio.

No real devices, audio recordings, external checkpoints or networking.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from voice_engine import Voice


class MicrophonePacketLossTests(unittest.TestCase):
    def run_fake_microphone(self, frame_count, overflow_at=()):
        statuses=[]
        heard=[]
        vosk_packets=[]
        pcm=(np.ones(1600,dtype="<i2")*180).tobytes()
        voice=Voice(heard.append,lambda status:report(status),lambda:False)
        voice.running=True
        voice._generation=23

        def report(status):
            statuses.append(status)
            if "Микрофон пропустил" in status:
                voice.running=False

        class Recognizer:
            def SetWords(self,*args):
                pass
            def AcceptWaveform(self,packet):
                vosk_packets.append(packet)
                return False

        class FakeStream:
            def __init__(self,**kwargs):
                self.callback=kwargs["callback"]
            def __enter__(self):
                for index in range(frame_count):
                    status=(types.SimpleNamespace(input_overflow=True)
                            if index in overflow_at else None)
                    self.callback(pcm,1600,None,status)
                return self
            def __exit__(self,*args):
                return False

        vosk=types.SimpleNamespace(
            SetLogLevel=lambda *args:None,
            Model=lambda *args:object(),
            KaldiRecognizer=lambda *args:Recognizer())
        sd=types.SimpleNamespace(
            PortAudioError=OSError,
            query_devices=lambda *args,**kw:{"default_samplerate":16000},
            RawInputStream=FakeStream)

        # In the no-loss case, finish after the first actual input packet.
        voice.on_audio_level=lambda _:setattr(voice,"running",False)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"vosk"/"am").mkdir(parents=True)
            (root/"vosk"/"am"/"final.mdl").write_bytes(b"stub")
            with mock.patch("voice_engine.assets",return_value=root),mock.patch.dict(
                    sys.modules,{"vosk":vosk,"sounddevice":sd}):
                voice._run(23)
        return statuses,heard,vosk_packets

    def test_audio_queue_eviction_is_visible_and_discards_partial_utterance(self):
        # 75 queued 100ms frames overflow the 60-frame bounded queue.
        statuses,heard,processed=self.run_fake_microphone(75)
        self.assertTrue(any("Микрофон пропустил" in s for s in statuses))
        self.assertEqual(heard,[])
        self.assertEqual(processed,[])

    def test_portaudio_input_overflow_is_visible_and_never_spliced(self):
        statuses,heard,processed=self.run_fake_microphone(1,overflow_at={0})
        self.assertTrue(any("Микрофон пропустил" in s for s in statuses))
        self.assertEqual(heard,[])
        self.assertEqual(processed,[])

    def test_normal_frames_have_no_false_packet_loss_warning(self):
        statuses,heard,processed=self.run_fake_microphone(1)
        self.assertFalse(any("Микрофон пропустил" in s for s in statuses))
        self.assertEqual(heard,[])
        self.assertEqual(len(processed),1)


if __name__=="__main__":
    unittest.main()
