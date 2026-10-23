"""Microphone quality diagnostics: synthetic PCM only, no sounddevice."""
import unittest
import numpy as np

from scripts.check_microphone_quality import summarize_pcm_packets


class MicrophoneQualityChecks(unittest.TestCase):
    @staticmethod
    def constant(value,frames=1600):
        return (np.ones(frames,dtype="<i2")*value).tobytes()

    def test_normal_signal_reports_only_aggregate_metadata(self):
        result=summarize_pcm_packets(
            [self.constant(1000)]*10,48000)
        self.assertEqual(result["sample_rate_hz"],48000)
        self.assertEqual(result["packets_received"],10)
        self.assertEqual(result["portaudio_overflows"],0)
        self.assertEqual(result["clipped_samples_percent"],0.0)
        self.assertFalse(result["audio_recordings_saved"])
        self.assertNotIn("pcm",str(result).casefold())
        self.assertEqual(len(result["diagnostics"]),1)

    def test_silence_prompts_user_to_check_input_source(self):
        result=summarize_pcm_packets([bytes(3200)]*8,16000)
        self.assertEqual(result["near_silent_packets"],8)
        self.assertTrue(any("тихий" in s for s in result["diagnostics"]))

    def test_clipping_and_dropped_packets_are_visible(self):
        high=self.constant(32767)
        result=summarize_pcm_packets(
            [high]*5,44100,overflows=2,lost=3)
        self.assertGreater(result["clipped_samples_percent"],90.0)
        self.assertEqual(result["portaudio_overflows"],2)
        self.assertEqual(result["queue_dropped_packets"],3)
        self.assertTrue(any("Перегрузка" in s for s in result["diagnostics"]))
        self.assertTrue(any("Пропущены" in s for s in result["diagnostics"]))

    def test_bad_rate_and_invalid_pcm_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize_pcm_packets([],16000)
        with self.assertRaises(ValueError):
            summarize_pcm_packets([b"\x01"],16000)
        with self.assertRaises(ValueError):
            summarize_pcm_packets([self.constant(12)],1000)


if __name__=="__main__":
    unittest.main()
