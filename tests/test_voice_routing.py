"""Regression coverage for authoritative Whisper intent and worker cancellation.

No model checkpoints or live microphone required.
"""
import sys
import tempfile
import threading
import time
import types
import unittest
import numpy as np  # Import native extension before patch.dict to avoid DLL reloading on Windows.
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice_engine import Voice


class VoiceRoutingTests(unittest.TestCase):
    def check_whisper(self, recognized, fallback):
        heard, vision, status = [], [], []
        finished = threading.Event()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "base.pt").write_bytes(b"test-only")
            fake_model = types.SimpleNamespace(
                transcribe=lambda *a, **kw: {"text": recognized})
            fake_whisper = types.SimpleNamespace(load_model=lambda *a, **kw: fake_model)
            voice = Voice(heard.append, status.append, lambda: False,
                          on_vision_audio=lambda pcm, src: (vision.append((pcm, src)), finished.set()))
            with mock.patch("voice_engine.assets", return_value=root), mock.patch.dict(
                    sys.modules, {"whisper": fake_whisper}):
                pcm = bytes(32000)
                voice._try_whisper(pcm, did_wake=True, fallback_text=fallback)
                timeout = time.monotonic() + 3
                while voice.whisper_busy and time.monotonic() < timeout:
                    time.sleep(.01)
                self.assertFalse(voice.whisper_busy, repr(status))
            return heard, vision

    def test_vosk_false_vision_guess_does_not_start_camera(self):
        heard, vision = self.check_whisper("кто ты", "джарвис посмотри в камеру")
        self.assertEqual(heard, ["кто ты"])
        self.assertEqual(vision, [])

    def test_whisper_confirmed_screen_uses_original_audio(self):
        heard, vision = self.check_whisper("посмотри на экран", "джарвис кто ты")
        self.assertEqual(heard, [])
        self.assertEqual(vision, [(bytes(32000), "screen")])

    def test_whisper_confirmed_camera_uses_original_audio(self):
        heard, vision = self.check_whisper("посмотри в камеру", "джарвис пуст")
        self.assertEqual(heard, [])
        self.assertEqual(vision, [(bytes(32000), "camera")])

    def test_no_late_dispatch_after_microphone_stop(self):
        started = threading.Event()
        proceed = threading.Event()
        heard, vision = [], []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "base.pt").write_bytes(b"test-only")
            def transcribe(*args, **kwargs):
                started.set()
                self.assertTrue(proceed.wait(3))
                return {"text": "посмотри в камеру"}
            fake_whisper = types.SimpleNamespace(
                load_model=lambda *a, **kw: types.SimpleNamespace(transcribe=transcribe))
            voice = Voice(heard.append, lambda _: None, lambda: False,
                          on_vision_audio=lambda pcm, src: vision.append(src))
            with mock.patch("voice_engine.assets", return_value=root), mock.patch.dict(
                    sys.modules, {"whisper": fake_whisper}):
                voice._try_whisper(bytes(32000), did_wake=True)
                self.assertTrue(started.wait(3))
                voice.stop()
                proceed.set()
                timeout = time.monotonic() + 3
                while voice.whisper_busy and time.monotonic() < timeout:
                    time.sleep(.01)
        self.assertEqual(heard, [])
        self.assertEqual(vision, [])

    def test_native_windows_audio_rates_are_resampled_to_whisper_pcm(self):
        for rate in (44100,48000):
            with self.subTest(rate=rate):
                mono=(np.ones(rate//10,dtype=np.int16)*1000).tobytes()
                audio=Voice.normalize_mic_packet(mono,rate)
                self.assertEqual(len(audio),3200)  # 100 ms at 16 kHz, 16-bit.
                values=np.frombuffer(audio,dtype="<i2")
                self.assertGreater(float(np.mean(values)),850)
                self.assertLess(float(np.mean(values)),1150)
        original=b"\\x01\\x00"*1600
        self.assertEqual(Voice.normalize_mic_packet(original,16000),original)
        with self.assertRaises(ValueError):
            Voice.normalize_mic_packet(original,1000)

    def test_microphone_device_selection_validation(self):
        voice = Voice(lambda _: None, lambda _: None, lambda: False)
        with self.assertRaises(ValueError):
            voice.set_input_device(-1)
        with self.assertRaises(ValueError):
            voice.set_input_device(True)
        voice.set_input_device(3)
        self.assertEqual(voice.input_device, 3)
        voice.set_input_device(None)
        self.assertIsNone(voice.input_device)
        voice.running = True
        with self.assertRaises(RuntimeError):
            voice.set_input_device(1)


if __name__ == "__main__":
    unittest.main()
