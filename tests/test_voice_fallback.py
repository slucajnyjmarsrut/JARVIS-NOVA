"""Exercise Whisper scheduling in memory without a microphone or ML installation."""
import sys
import tempfile
import threading
import time
import types
import unittest
import numpy as np  # Import native numpy extension before patch.dict(sys.modules) snapshots it.
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_engine import Voice


class WhisperFallbackTests(unittest.TestCase):
    def test_wake_addresses_with_commas_and_dashes(self):
        # Natural spoken introductions used to be ignored after punctuation.
        examples = (
            ("Эй, Джарвис, открой блокнот", "открой блокнот"),
            ("Слушай, Джарвис. как дела?", "как дела?"),
            ("Ну — Джарвис! открой Chrome", "открой Chrome"),
            ("Окей: Жарвис, включи музыку", "включи музыку"),
            ("Привет, Джарвис, что делаешь?", "что делаешь?"),
            ("Джарвис, открой блокнот", "открой блокнот"),
        )
        for spoken, command in examples:
            with self.subTest(spoken=spoken):
                heard = []
                voice = Voice(heard.append, lambda _: None, lambda: False)
                voice.accept_text(spoken)
                self.assertEqual(heard, [command])
                self.assertEqual(strip_wake(spoken), command)

    def test_wake_only_interjection_arms_followup(self):
        heard = []
        statuses = []
        voice = Voice(heard.append, statuses.append, lambda: False)
        voice.accept_text("Эй, Джарвис!")
        self.assertEqual(heard, [])
        self.assertTrue(any("Слушаю команду" in s for s in statuses))
        voice.accept_text("открой блокнот")
        self.assertEqual(heard, ["открой блокнот"])

    def test_unrelated_or_embedded_name_cannot_activate(self):
        for spoken in (
            "вчера Джарвис открыл окно",
            "эйджарвис открой блокнот",
            "джарвисов открой блокнот",
            "эй, пожалуйста, джарвис открой блокнот",
            "привет, журнал открой блокнот",
            "потом скажи Джарвис открой браузер",
        ):
            with self.subTest(spoken=spoken):
                heard = []
                voice = Voice(heard.append, lambda _: None, lambda: False)
                voice.accept_text(spoken)
                self.assertEqual(heard, [])
                self.assertFalse(WAKE.match(spoken))

    def test_whisper_wake_with_spoken_comma_recovers_when_vosk_misses(self):
        heard, completed = [], threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            (models / "base.pt").write_bytes(b"fixture")
            recognizer = types.SimpleNamespace(
                transcribe=lambda *args, **kwargs:
                    {"text": "эй, джарвис, открой блокнот"})
            whisper = types.SimpleNamespace(load_model=lambda *a, **kw: recognizer)
            voice = Voice(lambda command: (heard.append(command), completed.set()),
                          lambda _: None, lambda: False)
            with mock.patch("voice_engine.assets", return_value=models), mock.patch.dict(
                    sys.modules, {"whisper": whisper}):
                voice._try_whisper(bytes(32000), did_wake=False)
                self.assertTrue(completed.wait(3))
                deadline = time.monotonic() + 3
                while voice.whisper_busy and time.monotonic() < deadline:
                    time.sleep(.01)
        self.assertEqual(heard, ["открой блокнот"])

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
                deadline=time.monotonic()+3
                while v.whisper_busy and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(heard, ['открой Chrome'])
                self.assertFalse(v.whisper_busy)
                v._try_whisper(bytes(16000 * 2), False)
                self.assertEqual(heard, ['открой Chrome']) # de-duplicated utterance
        finally:
            temp.cleanup()

    def test_whisper_corrects_vosk_when_wake_was_detected(self):
        heard = []
        statuses = []
        got = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "base.pt").write_bytes(b"test-only")
            recognizer = types.SimpleNamespace(
                transcribe=lambda *a, **kw: {"text": "джарвис открой блокнот"})
            model = types.SimpleNamespace(load_model=lambda *a, **kw: recognizer)
            voice = Voice(lambda value: (heard.append(value), got.set()),
                          lambda msg: statuses.append(msg), lambda: False)
            with mock.patch("voice_engine.assets", return_value=root), mock.patch.dict(
                    sys.modules, {"whisper": model}):
                voice._try_whisper(bytes(32000), True,
                                   fallback_text="джарвис пуст пуст")
                self.assertTrue(got.wait(3))
                deadline=time.monotonic()+3
                while voice.whisper_busy and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(heard, ["открой блокнот"], "Whisper statuses: " + repr(statuses))


    def test_whisper_uses_vosk_wake_even_if_wake_missing_from_transcript(self):
        heard=[]
        statuses=[]
        got=threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"fixture")
            fake=types.SimpleNamespace(load_model=lambda *a,**kw: types.SimpleNamespace(
                transcribe=lambda *a,**kw: {"text":"кто ты"}))
            voice=Voice(lambda text:(heard.append(text),got.set()),lambda msg:statuses.append(msg),lambda:False)
            with mock.patch("voice_engine.assets",return_value=root),mock.patch.dict(
                    sys.modules,{"whisper":fake}):
                voice._try_whisper(bytes(32000),True,fallback_text="джарвис пуст пуст")
                self.assertTrue(got.wait(3))
                deadline=time.monotonic()+3
                while voice.whisper_busy and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(heard,["кто ты"],"Whisper statuses: "+repr(statuses))


if __name__ == '__main__':
    unittest.main()
