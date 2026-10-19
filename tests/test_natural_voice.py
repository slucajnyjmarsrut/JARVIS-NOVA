"""Speech quality, cancellation, feedback and asynchronous reply style."""
import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock,patch

import numpy as np
from speech_output import split_for_tts
from speaker import Speaker
from main import Jarvis


class SentenceChunkTests(unittest.TestCase):
    def test_whitespace_and_sentences_keep_all_words(self):
        text="  Привет!  Как  дела?\nЭто длинная мысль. И вот продолжение."
        chunks=split_for_tts(text,max_chars=40)
        self.assertTrue(all(0<len(x)<=40 for x in chunks))
        self.assertEqual(" ".join(chunks)," ".join(text.split()))
        self.assertGreaterEqual(len(chunks),2)

    def test_very_long_word_does_not_break_model_limit(self):
        chunks=split_for_tts("а"*1000,max_chars=70)
        self.assertTrue(all(len(x)<=70 for x in chunks))
        self.assertEqual("".join(chunks),"а"*1000)

    def test_limit_length_before_sending_to_tts(self):
        result=split_for_tts("тест "+"длинный "*5000,max_total=500)
        self.assertTrue(result)
        self.assertLessEqual(sum(len(x)+1 for x in result),600)
        self.assertTrue(result[-1].endswith("…"))

    def test_empty_and_non_text_are_safe(self):
        self.assertEqual(split_for_tts(" \n "),())
        self.assertEqual(split_for_tts(None),())


class PlaybackQualityTests(unittest.TestCase):
    def test_smooth_edges_and_limit_invalid_peaks(self):
        audio=np.ones(4800,dtype=np.float32)*1.5
        cleaned=Speaker.clean_playback(audio,"normal")
        self.assertEqual(cleaned.shape,audio.shape)
        self.assertEqual(float(cleaned[0]),0)
        self.assertEqual(float(cleaned[-1]),0)
        self.assertLessEqual(float(np.max(cleaned)),.98)
        self.assertGreater(float(cleaned[1000]),.96)

    def test_whisper_is_quiet_relative_to_normal_after_fades(self):
        audio=np.ones(4800,dtype=np.float32)*.6
        normal=Speaker.clean_playback(audio,"normal")
        quiet=Speaker.clean_playback(audio,"whisper")
        self.assertAlmostEqual(float(np.max(quiet)),.144,places=3)
        self.assertGreater(float(np.max(normal)),float(np.max(quiet))*4)

    def test_nan_and_inf_do_not_reach_audio_driver(self):
        result=Speaker.clean_playback(
            np.array([np.nan,np.inf,-np.inf,.6]*400,dtype=np.float32),"normal")
        self.assertTrue(np.all(np.isfinite(result)))
        self.assertLessEqual(float(np.max(np.abs(result))),.98)

    def test_long_silero_reply_uses_multiple_bounded_phrases_and_busy_during_wait(self):
        speaker=Speaker()
        phrases=[]
        active=[]
        class Model:
            def apply_tts(self,**kw):
                phrases.append(kw["text"])
                return types.SimpleNamespace(cpu=lambda:types.SimpleNamespace(
                    numpy=lambda:np.ones(1200,dtype=np.float32)*.4))
        speaker.mode="silero"
        speaker.model=Model()
        class Audio:
            @staticmethod
            def play(pcm,rate):
                active.append(speaker.busy)
                self_assert.assertLessEqual(float(np.max(np.abs(pcm))),.98)
            @staticmethod
            def wait():
                active.append(speaker.busy)
        self_assert=self
        original=" ".join(["Здесь предложение о работе помощника."]*65)
        with patch.dict(sys.modules,{"sounddevice":Audio}):
            self.assertTrue(speaker.say(original,style="normal"))
        self.assertGreater(len(phrases),2)
        self.assertTrue(all(len(p)<=280 for p in phrases))
        self.assertTrue(all(active))
        self.assertFalse(speaker.busy)
        self.assertEqual(" ".join(phrases),original)

    def test_tts_error_is_reported_not_silently_ignored(self):
        speaker=Speaker()
        class Model:
            def apply_tts(self,**kw):
                raise RuntimeError("test audio device failure")
        speaker.mode="silero"
        speaker.model=Model()
        with patch.dict(sys.modules,{"sounddevice":types.SimpleNamespace()}):
            self.assertFalse(speaker.say("Тестовый ответ"))
        self.assertIn("device failure",speaker.last_error)
        self.assertFalse(speaker.busy)


class AsyncStyleTests(unittest.TestCase):
    @staticmethod
    def make_app():
        result=[]
        done=threading.Event()
        def speak(text,style="normal"):
            result.append((text,style))
            done.set()
            return True
        app=types.SimpleNamespace(_closing=False,_shutdown=threading.Event(),
            voice_enabled=False,engine="bundled",executing=True,
            _answer_style="normal",q=queue.Queue(),
            speaker=types.SimpleNamespace(say=speak,last_error=""),
            log=Mock(),status=types.SimpleNamespace(set=Mock()),
            after=Mock(),pump=Mock())
        app.reply=lambda text:Jarvis.reply(app,text)
        return app,result,done

    def test_delayed_chat_keeps_whisper_style_after_unrelated_message(self):
        app,calls,done=self.make_app()
        app._answer_style="normal"
        app.q.put(("chat_result",(True,"Тихо отвечаю","whisper")))
        Jarvis.pump(app)
        self.assertTrue(done.wait(2))
        self.assertEqual(calls,[("Тихо отвечаю","whisper")])
        self.assertEqual(app._answer_style,"normal")

    def test_action_result_keeps_normal_even_when_previous_command_whispered(self):
        app,calls,done=self.make_app()
        app._answer_style="whisper"
        app.learning=types.SimpleNamespace(feedback=Mock())
        app._pending_alias=None
        app.q.put(("action_result",(True,"Готово",("open_app",),"normal")))
        Jarvis.pump(app)
        self.assertTrue(done.wait(2))
        self.assertEqual(calls,[("Готово","normal")])
        app.learning.feedback.assert_called_once()

    def test_tts_device_error_is_visible_in_gui_status(self):
        app,_,_=self.make_app()
        app.q.put(("tts_error","PortAudioError: нет устройства"))
        Jarvis.pump(app)
        app.status.set.assert_called_with("Ошибка озвучивания: PortAudioError: нет устройства")


if __name__=="__main__":
    unittest.main()
