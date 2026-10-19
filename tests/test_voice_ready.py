"""Voice F9 activation must survive long device/model startup."""
import time
import unittest

from voice_engine import Voice


class VoiceReadinessTests(unittest.TestCase):
    def make(self):
        statuses=[]
        voice=Voice(lambda _:None,statuses.append,lambda:False)
        voice.running=True
        voice._generation=2
        return voice,statuses

    def test_f9_pressed_while_initializing_rearms_when_stream_opens(self):
        voice,statuses=self.make()
        voice.activate()
        self.assertTrue(voice._manual_pending)
        self.assertEqual(voice.until,0)
        self.assertIn("загружается",statuses[-1])
        self.assertTrue(voice._mark_mic_ready(2,48000))
        self.assertTrue(voice.mic_ready)
        self.assertFalse(voice._manual_pending)
        self.assertGreater(voice.until,time.monotonic()+7)
        self.assertIn("Слушаю команду",statuses[-1])
        self.assertTrue(any("48000" in s for s in statuses))

    def test_f9_when_ready_refreshes_listen_window(self):
        voice,statuses=self.make()
        voice._mark_mic_ready(2,16000)
        voice.activate()
        self.assertGreater(voice.until,time.monotonic()+7)
        self.assertFalse(voice._manual_pending)
        self.assertIn("Слушаю команду",statuses[-1])

    def test_stop_drops_pending_activation(self):
        voice,_=self.make()
        voice.activate()
        voice.stop()
        self.assertFalse(voice._manual_pending)
        self.assertFalse(voice.mic_ready)
        self.assertEqual(voice.until,0)
        self.assertFalse(voice._mark_mic_ready(2,16000))

    def test_stale_voice_worker_cannot_reenable_listening(self):
        voice,_=self.make()
        voice.activate()
        voice._generation=3
        self.assertFalse(voice._mark_mic_ready(2,16000))
        self.assertFalse(voice.mic_ready)
        self.assertEqual(voice.until,0)

    def test_f9_does_not_start_audio_when_stopped(self):
        voice,statuses=self.make()
        voice.running=False
        voice.activate()
        self.assertEqual(voice.until,0)
        self.assertFalse(voice._manual_pending)
        self.assertIn("недоступен",statuses[-1])


if __name__=="__main__":
    unittest.main()
