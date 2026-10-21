"""Quality regression for Russian Whisper without physical recording or cloud."""
import queue
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np  # Windows native extension preloaded before module mocks.

from asr_quality import (should_refine,prefer_refined,transcript_confidence,
                         suspicious_wake_prefix,should_refine_short_phrase,
                         prefer_short_refined,russian_app_vocabulary)
from speech_capture import AdaptiveSpeechGate
from voice_engine import Voice
from main import Jarvis


def recognition(text,logprob=-0.15,compression=1.0,silence=0.05):
    return {"text":text,"segments":[{
        "avg_logprob":logprob,"compression_ratio":compression,
        "no_speech_prob":silence}]}


class RecognitionQualityTests(unittest.TestCase):
    def test_near_wake_requires_low_confidence_and_segment_metadata(self):
        self.assertTrue(suspicious_wake_prefix(
            recognition("джавис открой блокнот",logprob=-1.2)))
        self.assertTrue(suspicious_wake_prefix(
            recognition("эй джайвис что делаешь",logprob=-1.0)))
        self.assertFalse(suspicious_wake_prefix(
            recognition("джавис открой блокнот",logprob=-.1)))
        self.assertFalse(suspicious_wake_prefix({"text":"джавис открой блокнот"}))
        self.assertFalse(suspicious_wake_prefix(
            recognition("джастин открой блокнот",logprob=-2.0)))
        self.assertFalse(suspicious_wake_prefix(
            recognition("сделай громче",logprob=-2.0)))

    def test_accurate_small_recovers_corrupted_wake_but_fast_does_not(self):
        for mode,expected in (("accurate",["открой блокнот"]),("fast",[])):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/"base.pt").write_bytes(b"stub")
                (root/"small.pt").write_bytes(b"stub")
                captured=[]
                done=threading.Event()
                models=[]
                v=Voice(lambda s:captured.append(s),lambda _:None,lambda:False)
                v.recognition_mode=mode
                def first(*a,**kw):
                    models.append("base")
                    return recognition("джавис открой блокнот",logprob=-1.15)
                def refined(*a,**kw):
                    models.append("small")
                    return recognition("джарвис открой блокнот",logprob=-.2)
                v._get_whisper_model=lambda _:types.SimpleNamespace(transcribe=first)
                v._get_small_model=lambda _:types.SimpleNamespace(transcribe=refined)
                v.on_transcript=lambda _:done.set()
                with mock.patch("voice_engine.assets",return_value=root):
                    v._try_whisper((np.ones(16000,dtype="<i2")*120).tobytes(),False)
                    deadline=time.monotonic()+3
                    while v.whisper_busy and time.monotonic()<deadline:
                        time.sleep(.01)
                self.assertEqual(captured,expected)
                self.assertEqual(models,["base","small"] if mode=="accurate" else ["base"])

    def test_wake_recovery_never_dispatches_weak_or_missing_wake(self):
        for second in (
            recognition("открой блокнот",logprob=-.1),
            recognition("джарвис открой блокнот",logprob=-1.5),
            {"text":"джарвис открой блокнот"}):
            with self.subTest(second=second),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/"base.pt").write_bytes(b"stub")
                (root/"small.pt").write_bytes(b"stub")
                called=[]
                v=Voice(called.append,lambda _:None,lambda:False)
                v._get_whisper_model=lambda _:types.SimpleNamespace(transcribe=lambda *a,**kw:
                    recognition("джавис открой блокнот",logprob=-1.0))
                v._get_small_model=lambda _:types.SimpleNamespace(transcribe=lambda *a,**kw:second)
                with mock.patch("voice_engine.assets",return_value=root):
                    v._try_whisper((np.ones(16000,dtype="<i2")*120).tobytes(),False)
                    deadline=time.monotonic()+3
                    while v.whisper_busy and time.monotonic()<deadline:
                        time.sleep(.01)
                self.assertEqual(called,[])

    def test_short_russian_false_word_is_refined_but_greeting_is_fast(self):
        self.assertTrue(should_refine_short_phrase(
            recognition("джарвис джайдес",logprob=-.14),True))
        self.assertTrue(should_refine_short_phrase(
            recognition("джайдес",logprob=-.14),True))
        self.assertFalse(should_refine_short_phrase(
            recognition("джайдес",logprob=-.14),False))
        self.assertFalse(should_refine_short_phrase(
            recognition("привет",logprob=-.14),True))
        self.assertFalse(should_refine_short_phrase(
            recognition("блокнот",logprob=-.14),True))
        self.assertFalse(should_refine_short_phrase(
            recognition("джайдес",logprob=-1.1),True))
        self.assertFalse(should_refine_short_phrase(
            {"text":"джайдес"},True))
        self.assertFalse(should_refine_short_phrase(
            recognition("джайдес",logprob=-.14,silence=.8),True))

    def test_second_pass_cannot_invent_app_command_from_garbled_word(self):
        first=recognition("джайдес",logprob=-.3)
        corrected=recognition("что делаешь",logprob=-.05)
        invented=recognition("открой блокнот",logprob=-.01)
        self.assertIs(prefer_short_refined(first,corrected),corrected)
        self.assertIs(prefer_short_refined(first,invented),first)
        self.assertIs(prefer_short_refined(first,{"text":"что делаешь"}),first)

    def test_accurate_mode_recovers_short_question_with_bounded_second_pass(self):
        utterance=(np.ones(16000,dtype="<i2")*120).tobytes()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"stub")
            (root/"small.pt").write_bytes(b"stub")
            calls=[]
            delivered=[]
            done=threading.Event()
            def transcribe(*a,**kw):
                calls.append(kw)
                result=(recognition("джарвис джайдес",logprob=-.35) if
                        kw["beam_size"]==2 else
                        recognition("джарвис что делаешь",logprob=-.06))
                if len(calls)==2:done.set()
                return result
            voice=Voice(delivered.append,lambda _:None,lambda:False)
            voice._get_small_model=lambda _:types.SimpleNamespace(transcribe=transcribe)
            voice.until=time.monotonic()+8
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper(utterance,False)
                self.assertTrue(done.wait(3))
                deadline=time.monotonic()+3
                while voice.whisper_busy and time.monotonic()<deadline:
                    time.sleep(.01)
            self.assertEqual(delivered,["что делаешь"])
            self.assertEqual([c["beam_size"] for c in calls],[2,5])
            self.assertTrue(all(c["language"]=="ru" for c in calls))

    def test_short_question_does_not_trigger_extra_decode_in_fast_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"stub")
            (root/"small.pt").write_bytes(b"stub")
            calls=[]
            done=threading.Event()
            def transcribe(*a,**kw):
                calls.append(kw["beam_size"])
                done.set()
                return recognition("джайдес",logprob=-.25)
            voice=Voice(lambda _:None,lambda _:None,lambda:False)
            voice.recognition_mode="fast"
            voice._get_whisper_model=lambda _:types.SimpleNamespace(transcribe=transcribe)
            voice.until=time.monotonic()+8
            with mock.patch("voice_engine.assets",return_value=root):
                voice._try_whisper((np.ones(16000,dtype="<i2")*120).tobytes(),False)
                self.assertTrue(done.wait(3))
                deadline=time.monotonic()+3
                while voice.whisper_busy and time.monotonic()<deadline:
                    time.sleep(.01)
            self.assertEqual(calls,[2])

    def test_low_confidence_suffix_triggers_bounded_retry(self):
        phrase={"text":"джарвис расскажи прогноз","segments":[
            {"avg_logprob":-.15,"no_speech_prob":.02,
             "compression_ratio":1.0,"start":0.0,"end":.7},
            {"avg_logprob":-1.13,"no_speech_prob":.04,
             "compression_ratio":1.0,"start":.7,"end":1.15}]}
        self.assertGreater(transcript_confidence(phrase),-.76)
        self.assertTrue(should_refine(phrase,True))
        self.assertFalse(should_refine(phrase,False))
        bad_noise={**phrase,"segments":[
                   {**phrase["segments"][0],"avg_logprob":0.0},
                   {**phrase["segments"][1],"avg_logprob":-1.1,
                    "no_speech_prob":.9}]}
        self.assertFalse(should_refine(bad_noise,True))
        too_brief={**phrase,"segments":[phrase["segments"][0],
                    {**phrase["segments"][1],"end":.8}]}
        self.assertFalse(should_refine(too_brief,True))

    def test_app_name_hints_are_only_vocabulary_not_commands(self):
        self.assertIsNone(russian_app_vocabulary(recognition("что делаешь")))
        self.assertIsNone(russian_app_vocabulary(recognition("помоги")))
        prompt=russian_app_vocabulary(recognition("джарвис открой тилеграм"))
        self.assertIn("Телеграм",prompt)
        self.assertIn("Дискорд",prompt)
        self.assertNotIn("открой",prompt.casefold())
        self.assertNotIn("джарвис",prompt.casefold())
        self.assertLess(len(prompt),200)

    def test_poor_last_segment_refines_russian_app_name_with_local_hint(self):
        finished=threading.Event()
        heard=[]
        calls=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"base.pt").write_bytes(b"fixture")
            (root/"small.pt").write_bytes(b"fixture")
            def transcribe(samples,**kwargs):
                calls.append(kwargs)
                if kwargs["beam_size"]==2:
                    return {"text":"джарвис открой тилеграм","segments":[
                        {"avg_logprob":-.15,"compression_ratio":1,
                         "no_speech_prob":.01,"start":0.0,"end":.55},
                        {"avg_logprob":-1.15,"compression_ratio":1,
                         "no_speech_prob":.02,"start":.55,"end":1.2}]}
                finished.set()
                return recognition("джарвис открой телеграм",logprob=-.11)
            v=Voice(heard.append,lambda _:None,lambda:False)
            v._get_small_model=lambda _:types.SimpleNamespace(transcribe=transcribe)
            v.until=time.monotonic()+8
            with mock.patch("voice_engine.assets",return_value=root):
                v._try_whisper((np.ones(16000,dtype="<i2")*120).tobytes(),False)
                self.assertTrue(finished.wait(3))
                deadline=time.monotonic()+3
                while v.whisper_busy and time.monotonic()<deadline:
                    time.sleep(.01)
            self.assertEqual(heard,["открой телеграм"])
            self.assertEqual([kw["beam_size"] for kw in calls],[2,5])
            self.assertNotIn("initial_prompt",calls[0])
            self.assertIn("Телеграм",calls[1]["initial_prompt"])

    def test_good_russian_transcript_skips_expensive_second_pass(self):
        self.assertFalse(should_refine(recognition("джарвис открой блокнот"),True))

    def test_poor_confidence_triggers_second_pass_only_for_woken_command(self):
        bad=recognition("джарвис открой бронз",logprob=-1.10)
        self.assertTrue(should_refine(bad,True))
        self.assertFalse(should_refine(bad,False))
        better=recognition("джарвис открой браузер",logprob=-.11)
        self.assertIs(prefer_refined(bad,better),better)

    def test_empty_transcript_can_be_retried_only_after_activation(self):
        self.assertTrue(should_refine({"text":""},True))
        self.assertFalse(should_refine({"text":""},False))
        second=recognition("джарвис запусти блокнот")
        self.assertIs(prefer_refined({"text":""},second),second)

    def test_hallucination_not_rescued_if_stronger_pass_says_silence(self):
        bad=recognition("джарвис удали все",logprob=-1.8)
        silent={"text":"","segments":[]}
        self.assertIs(prefer_refined(bad,silent),silent)

    def test_metadata_missing_keeps_first_if_decoders_disagree(self):
        first={"text":"джарвис открой блокнот"}
        second={"text":"джарвис удали файлы"}
        self.assertIs(prefer_refined(first,second),first)
        self.assertIsNone(transcript_confidence(first))

    def test_quality_decode_calls_model_twice_only_for_weak_woken_audio(self):
        got=[]
        event=threading.Event()
        transcripts=[]
        calls=[]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/"base.pt").write_bytes(b"mock")
            def fake_transcribe(samples,**kw):
                calls.append(kw)
                return (recognition("джарвис открой бронз",logprob=-1.3) if
                        kw["beam_size"]==2 else
                        recognition("джарвис открой браузер",logprob=-.18))
            v=Voice(lambda s:(got.append(s),event.set()),lambda _:None,
                    lambda:False,on_transcript=transcripts.append)
            v.whisper_model=types.SimpleNamespace(transcribe=fake_transcribe)
            v.until=time.monotonic()+8  # F9 activation is a real user action
            with mock.patch("voice_engine.assets",return_value=path):
                v._try_whisper((np.ones(16000,dtype="<i2")*160).tobytes(),False)
                self.assertTrue(event.wait(3))
        self.assertEqual(got,["открой браузер"])
        self.assertEqual(transcripts,["джарвис открой браузер"])
        self.assertEqual([call["beam_size"] for call in calls],[2,5])
        self.assertTrue(all(call["language"]=="ru" for call in calls))

    def test_background_noise_with_low_confidence_does_not_trigger_second_pass(self):
        calls=[]
        event=threading.Event()
        got=[]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/"base.pt").write_bytes(b"mock")
            def fake_transcribe(samples,**kw):
                calls.append(kw)
                event.set()
                return recognition("шумовой фон",logprob=-1.75)
            v=Voice(got.append,lambda _:None,lambda:False)
            v.whisper_model=types.SimpleNamespace(transcribe=fake_transcribe)
            with mock.patch("voice_engine.assets",return_value=path):
                v._try_whisper((np.ones(16000,dtype="<i2")*60).tobytes(),False)
                self.assertTrue(event.wait(3))
                deadline=time.monotonic()+3
                while v.whisper_busy and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(len(calls),1)
        self.assertEqual(got,[])

    def test_quality_pass_cannot_dispatch_results_after_stop(self):
        entered,proceed=threading.Event(),threading.Event()
        got=[]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/"base.pt").write_bytes(b"mock")
            def fake_transcribe(samples,**kw):
                if kw["beam_size"]==2:
                    entered.set()
                    proceed.wait(3)
                    return recognition("джарвис открой блокнот",logprob=-1.5)
                return recognition("джарвис открой браузер",logprob=-.1)
            v=Voice(got.append,lambda _:None,lambda:False)
            v.whisper_model=types.SimpleNamespace(transcribe=fake_transcribe)
            v.until=time.monotonic()+8
            with mock.patch("voice_engine.assets",return_value=path):
                v._try_whisper(bytes(32000),True)
                self.assertTrue(entered.wait(2))
                v.stop()
                proceed.set()
                time.sleep(.1)
        self.assertEqual(got,[])


class SensitivityTests(unittest.TestCase):
    def test_sensitivity_does_not_inflate_learned_noise_floor(self):
        basic=AdaptiveSpeechGate(noise_floor=5.0)
        boosted=AdaptiveSpeechGate(noise_floor=5.0)
        for _ in range(40):
            basic.observe(2.5)
            boosted.observe(2.5,sensitivity=2.0)
        self.assertAlmostEqual(basic.noise_floor,boosted.noise_floor,places=5)
        quiet=AdaptiveSpeechGate(noise_floor=5.0)
        self.assertEqual(quiet.observe(7.0),"idle")
        self.assertEqual(quiet.observe(7.0,sensitivity=1.8),"idle")
        self.assertEqual(quiet.observe(7.0,sensitivity=1.8),"start")


class TranscriptUiTests(unittest.TestCase):
    def test_last_recognized_command_remains_visible_separately_from_status(self):
        app=types.SimpleNamespace(q=queue.Queue(),_closing=False,
            voice_enabled=True,hud_transcript=types.SimpleNamespace(set=mock.Mock()),
            after=mock.Mock(),pump=mock.Mock())
        app.q.put(("transcript","джарвис открой блокнот"))
        Jarvis.pump(app)
        app.hud_transcript.set.assert_called_once_with(
            "РАСПОЗНАНО: джарвис открой блокнот")


if __name__=="__main__":
    unittest.main()
