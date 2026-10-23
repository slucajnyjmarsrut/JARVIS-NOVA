"""Exact PCM16 microphone FIR resampling across packet boundaries, offline."""
import unittest
import numpy as np

from audio_io import BufferedMicResampler, AudioFormatError, prepare_audio


class BufferedMicResamplerTests(unittest.TestCase):
    def test_44k_and_48k_packets_match_one_continuous_decode(self):
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                t=np.arange(rate*2,dtype=np.float64)/rate
                pcm=(10000*np.sin(2*np.pi*3500*t)).astype("<i2")
                direct=np.clip(prepare_audio(pcm,rate)*32768.0,
                               -32768,32767).astype("<i2")
                mic=BufferedMicResampler(rate)
                frame=rate//10
                packets=[mic.feed(pcm[i:i+frame].tobytes())
                         for i in range(0,len(pcm),frame)]
                self.assertEqual(packets[0],b"")
                packets.append(mic.flush())
                output=np.frombuffer(b"".join(packets),dtype="<i2")
                np.testing.assert_array_equal(output,direct)

    def test_previous_independent_block_resampling_distorted_boundaries(self):
        rate=48000
        t=np.arange(rate,dtype=np.float64)/rate
        pcm=(10000*np.sin(2*np.pi*3500*t)).astype("<i2")
        reference=prepare_audio(pcm,rate)
        old=np.concatenate([
            prepare_audio(pcm[i:i+rate//10],rate)
            for i in range(0,len(pcm),rate//10)])
        self.assertGreater(float(np.max(np.abs(old-reference))),.01)

    def test_native_16k_pcm_passes_without_extra_delay(self):
        mic=BufferedMicResampler(16000)
        sample=(np.arange(1600,dtype="<i2")-800).tobytes()
        self.assertEqual(mic.feed(sample),sample)
        self.assertEqual(mic.flush(),b"")

    def test_resampler_reset_discards_old_audio_after_tts(self):
        mic=BufferedMicResampler(48000)
        frame=(np.ones(4800,dtype="<i2")*180).tobytes()
        self.assertEqual(mic.feed(frame),b"")
        mic.reset()
        self.assertEqual(mic.feed(frame),b"")
        self.assertEqual(len(mic.feed(frame)),3200)

    def test_invalid_rates_and_odd_pcm_are_rejected(self):
        with self.assertRaises(AudioFormatError):
            BufferedMicResampler(0)
        with self.assertRaises(AudioFormatError):
            BufferedMicResampler(48000).feed(bytes([1]))


if __name__=="__main__":
    unittest.main()
