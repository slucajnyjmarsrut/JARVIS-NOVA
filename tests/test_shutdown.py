"""Exit regression: clicking X shuts down instead of minimizing to background."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import Jarvis
from speaker import Speaker
from voice_engine import Voice


class ImmediateThread:
    def __init__(self, target=None, **kwargs):
        self.target = target
        self.daemon = kwargs.get('daemon')
    def start(self):
        self.target()


class SafeFakeTimer:
    calls = 0
    def __init__(self, delay, func):
        self.delay=delay
        self.func=func
        self.daemon=False
    def start(self):
        SafeFakeTimer.calls+=1


class ShutdownTests(unittest.TestCase):
    def test_closing_root_stops_everything_only_once(self):
        microphone=SimpleNamespace(stopping=False,running=True,stop=Mock())
        speaker=SimpleNamespace(shutdown=Mock())
        fake=SimpleNamespace(_closing=False,_shutdown=threading.Event(),
            voice_enabled=True,control_allowed=True,vision_allowed=True,
            voice=microphone,speaker=speaker,destroy=Mock())
        with patch('main.threading.Thread',ImmediateThread), patch('main.threading.Timer',SafeFakeTimer):
            Jarvis.close(fake)
            Jarvis.close(fake)
        self.assertTrue(fake._shutdown.is_set())
        self.assertFalse(fake.voice_enabled)
        self.assertFalse(fake.control_allowed)
        self.assertFalse(fake.vision_allowed)
        self.assertTrue(microphone.stopping)
        self.assertFalse(microphone.running)
        microphone.stop.assert_called_once()
        speaker.shutdown.assert_called_once()
        fake.destroy.assert_called_once()

    def test_voice_commands_ignored_after_stop(self):
        heard=[]
        v=Voice(heard.append,lambda x:None,lambda:False)
        v.stop()
        v.accept_text('Джарвис открой Chrome')
        self.assertEqual(heard,[])

    def test_speaker_closing_event_prevents_late_audio(self):
        sp=Speaker()
        sp.shutdown()
        self.assertTrue(sp._closing.is_set())
        self.assertIs(sp.say('Это не должно озвучиваться'),False)
        self.assertFalse(sp.busy)

if __name__=='__main__':unittest.main()
