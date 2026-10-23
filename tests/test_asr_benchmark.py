"""Benchmark metrics and WAV path (no models, no microphone or network)."""
import csv
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from scripts.benchmark_russian_asr import (
    benchmark_wavs, edit_distance, score_pairs, words,
)


class OfflineRussianBenchmarkTests(unittest.TestCase):
    def test_wer_cer_russian_punctuation_and_yo(self):
        self.assertEqual(words("Эй, Джарвис, включи Ёлку!"),
                         ["эй","джарвис","включи","елку"])
        self.assertEqual(edit_distance(["открой","блокнот"],
                                       ["открой","браузер"]),1)
        metrics=score_pairs([
            ("Джарвис, открой блокнот","джарвис открой браузер",.4,1.2),
            ("Покажи ёлку!","покажи елку",.6,1.0),
        ])
        self.assertEqual(metrics["reference_words"],5)
        self.assertEqual(metrics["word_errors"],1)
        self.assertAlmostEqual(metrics["wer"],.2)
        self.assertGreater(metrics["cer"],0.0)
        self.assertAlmostEqual(metrics["wake_recall"],1.0)
        self.assertAlmostEqual(metrics["false_wake_rate"],0.0)
        self.assertFalse(metrics["recordings_uploaded"])

    def test_false_wake_and_missed_wake_rates_are_separate(self):
        report=score_pairs([
            ("Джарвис, привет","джарвис привет",.2,.8),
            ("Эй, Джарвис!","привет",.2,.8),
            ("Вчера был дождь","джарвис открой браузер",.2,.8),
        ])
        self.assertEqual(report["wake_phrases"],2)
        self.assertEqual(report["nonwake_phrases"],1)
        self.assertEqual(report["wake_recall"],.5)
        self.assertEqual(report["false_wake_rate"],1.0)

    def test_empty_data_and_invalid_latency_cannot_fake_metrics(self):
        with self.assertRaises(ValueError):
            score_pairs([])
        with self.assertRaises(ValueError):
            score_pairs([("слово","слово",-1,1)])
        with self.assertRaises(ValueError):
            score_pairs([("слово","слово",1,0)])

    def test_local_wav_stays_in_memory_and_returns_only_aggregate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            wav=root/"phrase.wav"
            with wave.open(str(wav),"wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes((np.ones(16000,dtype="<i2")*200).tobytes())
            manifest=root/"phrases.csv"
            with manifest.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.writer(handle)
                writer.writerow(["audio","reference"])
                writer.writerow(["phrase.wav","Джарвис, открой блокнот"])
            weights=root/"base.pt"
            weights.write_bytes(b"test-only")
            seen=[]
            def load_model(path,device):
                self.assertEqual(path,str(weights))
                self.assertEqual(device,"cpu")
                return types.SimpleNamespace(transcribe=lambda samples,**kwargs:
                    (seen.append((len(samples),kwargs)),
                     {"text":"джарвис открой блокнот"})[-1])
            result=benchmark_wavs(manifest,weights,model_loader=load_model)
            self.assertEqual(result["wer"],0)
            self.assertEqual(result["wake_recall"],1.0)
            self.assertEqual(seen[0][0],16000)
            self.assertEqual(seen[0][1]["language"],"ru")
            self.assertNotIn("phrase.wav",str(result))
            self.assertNotIn("джарвис",str(result).lower())

    def test_missing_audio_bad_headers_and_model_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            model=base/"base.pt"
            model.write_bytes(b"fake")
            bad=base/"list.csv"
            bad.write_text("wav,reference\nfoo.wav,тест\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark_wavs(bad,model)
            bad.write_text("audio,reference\nmissing.wav,слова\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark_wavs(bad,model)
            with self.assertRaises(FileNotFoundError):
                benchmark_wavs(bad,base/"missing.pt")


if __name__=="__main__":
    unittest.main()
