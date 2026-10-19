"""GUI status telemetry for microphone reconnect / permanent failure."""
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from main import Jarvis


class Var:
    def __init__(self,value=""):
        self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class MicrophoneStatusTests(unittest.TestCase):
    @staticmethod
    def app(event):
        obj=SimpleNamespace(_closing=False,
            q=queue.Queue(),
            voice_enabled=True,
            mic_state=Var("Микрофон: включён"),
            status=Var("готов"),
            hud_level_value=.2,hud_level_at=5.,
            after=Mock())
        obj.q.put(("status",event))
        return obj

    def test_transient_disconnect_keeps_voice_enabled_but_clears_stale_meter(self):
        app=self.app("Микрофон: переподключение 2/5 через 1.2 с · устройство пропало")
        Jarvis.pump(app)
        self.assertTrue(app.voice_enabled)
        self.assertIn("переподключается",app.mic_state.get())
        self.assertEqual(app.hud_level_value,0)
        self.assertEqual(app.hud_level_at,0)
        app.after.assert_called_once()

    def test_vosk_ready_marks_microphone_listening_again(self):
        app=self.app("Vosk готов · микрофон 48000 Гц → 16000 Гц · жду «Джарвис»")
        Jarvis.pump(app)
        self.assertTrue(app.voice_enabled)
        self.assertIn("включён",app.mic_state.get())

    def test_permanent_disconnect_requires_user_reenable(self):
        app=self.app("Ошибка микрофона: Не удалось восстановить микрофон после 5 попыток")
        Jarvis.pump(app)
        self.assertFalse(app.voice_enabled)
        self.assertIn("ошибка",app.mic_state.get())

    def test_old_recovery_status_cannot_resurrect_stopped_mic(self):
        app=self.app("Vosk готов · микрофон 16000 Гц")
        app.voice_enabled=False
        Jarvis.pump(app)
        self.assertFalse(app.voice_enabled)
        self.assertEqual(app.mic_state.get(),"Микрофон: включён")
        self.assertEqual(app.status.get(),"готов")


if __name__=="__main__":
    unittest.main()
