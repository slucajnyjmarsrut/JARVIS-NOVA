"""Hands-free follow-up is allowed only after voice playback ends."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from main import Jarvis


class FollowupTests(unittest.TestCase):
    @staticmethod
    def fake():
        playing = threading.Event()
        release = threading.Event()
        activated = threading.Event()
        def speak(text,style='normal'):
            playing.set()
            release.wait(3)
        voice = SimpleNamespace(activate=lambda: activated.set())
        app = SimpleNamespace(_closing=False, _shutdown=threading.Event(),
                              voice_enabled=True, engine="bundled", speaker=SimpleNamespace(say=speak),
                              voice=voice, log=Mock(), status=SimpleNamespace(set=Mock()))
        return app, playing, release, activated

    def test_listens_only_after_silero_finishes(self):
        app, playing, release, activated = self.fake()
        Jarvis.reply(app, "Привет!")
        self.assertTrue(playing.wait(2))
        self.assertFalse(activated.is_set(), "Whisper must not listen over TTS")
        release.set()
        self.assertTrue(activated.wait(2))

    def test_does_not_rearm_after_shutdown(self):
        app, playing, release, activated = self.fake()
        Jarvis.reply(app, "До свидания")
        self.assertTrue(playing.wait(2))
        app._shutdown.set()
        release.set()
        self.assertFalse(activated.wait(.2))

    def test_no_automatic_followup_in_command_only_mode(self):
        app, playing, release, activated = self.fake()
        app.engine = "none"
        Jarvis.reply(app, "Готово")
        self.assertTrue(playing.wait(2))
        release.set()
        self.assertFalse(activated.wait(.2))


if __name__ == "__main__":
    unittest.main()
