# -*- coding: utf-8 -*-
"""RAM-only soft-speech capture and bounded gain for offline Russian ASR.

Input levels vary dramatically between laptop arrays, headset microphones
and Bluetooth hands-free inputs. None of these helpers changes OS gain or
persists audio, and background noise alone never authorizes a command.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class AdaptiveSpeechGate:
    """Track a quiet microphone noise floor, two-frame onset and adaptive hangover.

    The previous hard-coded 24/32768 PCM RMS minimum missed quiet speech.
    Do not continuously train the noise baseline while a phrase is in progress.
    """
    noise_floor: float = 3.5
    active: bool = False
    attack: int = 0
    silence: int = 0
    speech_frames: int = 0

    def reset(self):
        self.active=False
        self.attack=0
        self.silence=0
        self.speech_frames=0

    @property
    def onset_threshold(self) -> float:
        return max(7.0,min(1200.0,self.noise_floor*1.8+3.0))

    def observe(self,rms: float,sensitivity: float = 1.0,
                hangover_frames: int = 9) -> str:
        """Per 100ms packet. Calibrate noise on *raw* RMS, not boosted RMS."""
        rms=max(0.0,float(rms))
        sensitivity=max(0.75,min(2.0,float(sensitivity)))
        if self.active:
            if rms*sensitivity>=max(6.0,self.noise_floor*1.35+2.0):
                self.silence=0
                self.speech_frames+=1
            else:
                self.silence+=1
            if self.silence>=max(6,min(12,int(hangover_frames))):
                self.reset()
                return "end"
            return "speech"
        if rms*sensitivity>=self.onset_threshold:
            self.attack+=1
            if self.attack>=2:
                self.active=True
                self.silence=0
                self.speech_frames=self.attack
                return "start"
        else:
            self.attack=0
            # Bounded slow adjustment, using only frames unlikely to be speech.
            self.noise_floor=.988*self.noise_floor+.012*min(rms,self.noise_floor*1.5)
            self.noise_floor=max(1.0,self.noise_floor)
        return "idle"


def prepare_whisper_audio(pcm: bytes) -> np.ndarray:
    """16k PCM16 -> safe float32 with quiet-speech gain and optional rumble cut.

    Gain is per complete utterance (not per packet), preserving word envelopes
    and preventing pumping. Peak limited to avoid clipping. Do not normalize
    silence, DC-only packets or single isolated impulses.
    """
    if len(pcm)%2:
        raise ValueError("PCM16 audio length must be even")
    samples=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768.0
    if samples.size<256:
        return samples
    if float(np.std(samples))<0.000025:
        return samples  # digital silence or constant/non-speech DC
    # Filter 50/60Hz hum and handling rumble. This uses only RAM arrays.
    from scipy.signal import butter,sosfilt
    filtered=sosfilt(butter(2,75,fs=16000,btype="highpass",output="sos"),samples).astype(np.float32)
    frames=filtered[:len(filtered)//320*320].reshape(-1,320)
    if not frames.size:
        return filtered
    levels=np.sqrt(np.mean(frames*frames,axis=1))
    high=float(np.percentile(levels,85))
    if high<0.00010:
        return filtered  # silence/hiss below usable speech
    active=levels[levels>=max(0.00010,high*.30)]
    if active.size<2:
        return filtered
    typical=float(np.median(active))
    # Target ~3.5% FS RMS, with at most 16x digital amplification.
    gain=min(16.0,max(1.0,0.035/max(typical,0.0001)))
    peak=float(np.max(np.abs(filtered)))
    if peak>0:
        gain=min(gain,0.92/peak)
    return np.clip(filtered*gain,-.92,.92).astype(np.float32)
