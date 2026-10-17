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
                self.assertEqual(heard, ['открой Chrome']) # 2 s cooldown
        finally:
            temp.cleanup()

    def test_whisper_skips_vosk_wake(self):
        seen=[]
        v=Voice(seen.append, lambda _: None, lambda: False)
        v._try_whisper(bytes(32000), True)
        self.assertEqual(seen, [])


if __name__ == '__main__':
    unittest.main()
