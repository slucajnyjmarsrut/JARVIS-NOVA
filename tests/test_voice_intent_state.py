"""Regression tests for Russian wake, F9 and incomplete spoken commands.

Pure in-memory text state; no microphone or downloaded checkpoints.
"""
import unittest
from unittest import mock

from voice_engine import Voice


class VoiceIntentStateTests(unittest.TestCase):
    def make_voice(self):
        heard=[]
        statuses=[]
        return Voice(heard.append,statuses.append,lambda:False),heard,statuses

    def test_repeated_complete_action_overrides_incomplete_fragment(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,101]):
            voice.accept_text("джарвис открой")
            voice.accept_text("открой блокнот")
        self.assertEqual(heard,["открой блокнот"])
        self.assertEqual(voice.pending,"")

    def test_changed_action_overrides_incomplete_fragment(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,101]):
            voice.accept_text("джарвис открой")
            voice.accept_text("запусти браузер")
        self.assertEqual(heard,["запусти браузер"])

    def test_repeated_verb_still_asks_for_missing_app_name(self):
        voice,heard,status=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,101,102]):
            voice.accept_text("джарвис открой")
            voice.accept_text("открой")
            voice.accept_text("блокнот")
        self.assertEqual(heard,["открой блокнот"])
        self.assertEqual(sum("Что открыть" in s for s in status),2)

    def test_new_jarvis_request_clears_old_incomplete_verb(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,101]):
            voice.accept_text("джарвис открой")
            voice.accept_text("джарвис как дела")
        self.assertEqual(heard,["как дела"])
        self.assertEqual(voice.pending,"")
        self.assertEqual(voice.pending_until,0.0)

    def test_normal_short_followup_still_completes_partial_command(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,103]):
            voice.accept_text("эй, джарвис, открой")
            voice.accept_text("блокнот")
        self.assertEqual(heard,["открой блокнот"])
        self.assertEqual(voice.pending,"")

    def test_expired_partial_verb_not_attached_to_later_followup(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,107]):
            voice.accept_text("джарвис открой")
            voice.until=120  # a still-open, independently extended follow-up
            voice.accept_text("что нового")
        self.assertEqual(heard,["что нового"])
        self.assertEqual(voice.pending_until,0.0)

    def test_unactivated_noise_cannot_suppress_f9_authorized_identical_words(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,100.1]):
            voice.accept_text("открой блокнот")  # background ignored
            voice.until=108  # user pressed F9
            voice.accept_text("открой блокнот")
        self.assertEqual(heard,["открой блокнот"])

    def test_explicit_f9_activation_starts_a_fresh_request(self):
        voice,heard,_=self.make_voice()
        voice.running=True
        voice.mic_ready=True
        with mock.patch("voice_engine.time.monotonic",side_effect=[100,102,103]):
            voice.accept_text("джарвис открой")
            voice.activate()
            voice.accept_text("как дела")
        self.assertEqual(heard,["как дела"])
        self.assertEqual(voice.pending,"")

    def test_stop_discards_partial_speech_from_previous_session(self):
        voice,heard,_=self.make_voice()
        with mock.patch("voice_engine.time.monotonic",return_value=100):
            voice.accept_text("джарвис открой")
        self.assertNotEqual(voice.pending,"")
        voice.stop()
        self.assertEqual(voice.pending,"")
        self.assertEqual(voice.pending_until,0.0)
        self.assertEqual(heard,[])

    def test_microphone_disconnection_clears_abandoned_command(self):
        voice,_,_=self.make_voice()
        voice.running=True
        voice.mic_ready=True
        voice._generation=5
        with mock.patch("voice_engine.time.monotonic",return_value=100):
            voice.accept_text("джарвис открой")
            self.assertTrue(voice._mic_disconnected(5))
        self.assertEqual(voice.pending,"")
        self.assertEqual(voice.pending_until,0.0)


if __name__=="__main__":
    unittest.main()
