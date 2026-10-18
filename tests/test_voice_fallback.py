"""Exercise Whisper scheduling in memory without a microphone or ML installation."""
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_engine import Voice


class WhisperFallbackTests(unittest.TestCase):
    def test_voice_recovery_without_vosk_wake(self):
        heard = []
        event = threading.Event()
        temp = tempfile.TemporaryDirectory()
        try:
            models = Path(temp.name)
            (models / 'base.pt').write_bytes(b'test-only, not a real model')
            recognizer = types.SimpleNamespace(
                transcribe=lambda *a, **kw: {'text': 'джарвис открой Chrome'})
            fake_whisper = types.SimpleNamespace(load_model=lambda *a, **kw: recognizer)
            v = Voice(lambda text: (heard.append(text), event.set()), lambda _: None, lambda: False)
            with mock.patch('voice_engine.assets', return_value=models), mock.patch.dict(
                    sys.modules, {'whisper': fake_whisper}):
                # One second of fake 16kHz PCM; no audio saved to disk.
                v._try_whisper(bytes(16000 * 2), False)
                self.assertTrue(event.wait(timeout=3), 'Whisper fallback was not delivered')
                self.assertEqual(heard, ['открой Chrome'])
                self.assertFalse(v.whisper_busy)
                v._try_whisper(bytes(16000 * 2), False)
                self.assertEqual(heard, ['открой Chrome']) # de-duplicated utterance
        finally:
            temp.cleanup()

    def test_whisper_corrects_vosk_when_wake_was_detected(self):
        heard = []
        got = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "base.pt").write_bytes(b"test-only")
            recognizer = types.SimpleNamespace(
                transcribe=lambda *a, **kw: {"text": "джарвис открой блокнот"})
            model = types.SimpleNamespace(load_model=lambda *a, **kw: recognizer)
            voice = Voice(lambda value: (heard.append(value), got.set()),
                          lambda _: None, lambda: False)
            with mock.patch("voice_engine.assets", return_value=root), mock.patch.dict(
                    sys.modules, {"whisper": model}):
                voice._try_whisper(bytes(32000), True,
                                   fallback_text="джарвис пуст пуст")
                self.assertTrue(got.wait(3))
        self.assertEqual(heard, ["открой блокнот"])


if __name__ == '__main__':
    unittest.main()
