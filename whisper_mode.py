# -*- coding: utf-8 -*-
"""Lightweight acoustic *estimate* of whisper-like vs normal speech.

It is not a trained whisper detector. Input is the same RAM-only 16 kHz mono
PCM16 utterance already authorized for speech recognition. An audible voiced
periodic signal stays NORMAL even when the microphone gain is low.
"""
from __future__ import annotations
import math

import numpy as np


def _max_periodicity(frame: np.ndarray) -> float:
    """Maximum normalized pitch-period correlation; low for airy whisper."""
    centered=frame.astype(np.float32,copy=False)
    centered=centered-centered.mean()
    if centered.size<320 or float(np.dot(centered,centered))<1e-6:
        return 0.0
    best=0.0
    # 80–340Hz fundamental at 16kHz. Test at most 115 small vectors.
    for lag in range(47,161):
        left,right=centered[:-lag],centered[lag:]
        energy=math.sqrt(float(np.dot(left,left)*np.dot(right,right)))
        if energy>1e-6:
            best=max(best,float(np.dot(left,right))/energy)
    return min(1.0,max(0.0,best))


def speech_acoustics(pcm: bytes) -> tuple[float,float]:
    """RMS of voiced/speech frames and proportion with stable pitch.

    Not an instruction classifier; never use this score to authorize a command.
    """
    if len(pcm)<640 or len(pcm)%2:
        return 0.0,0.0
    samples=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768.0
    frames=samples[:len(samples)//480*480].reshape(-1,480)
    if not len(frames):
        return 0.0,0.0
    rms=np.sqrt(np.mean(frames*frames,axis=1))
    high=float(np.percentile(rms,85))
    if high<.0025:
        return 0.0,0.0  # no reliable speech: cannot claim whisper
    # Ignore gaps, pre-roll silence and the model tail, but keep soft words.
    active=np.flatnonzero(rms>=max(.0025,high*.30))
    if active.size<2:
        return 0.0,0.0
    level=float(np.median(rms[active]))
    # Run pitch probe only on a bounded representative set; no latency spikes.
    selected=active[np.linspace(0,len(active)-1,min(12,len(active)),dtype=int)]
    voiced=sum(_max_periodicity(frames[i])>.57 for i in selected)
    return level,voiced/max(1,len(selected))


class WhisperClassifier:
    def __init__(self):
        self.normal_rms=.055  # conservative uncalibrated default

    def classify(self,pcm: bytes) -> str:
        rms,periodic=speech_acoustics(pcm)
        if rms==0:
            return "normal"
        # Require BOTH relatively quiet speech AND mostly unvoiced texture;
        # this prevents simply speaking normally but quietly from switching.
        limit=max(.018,min(.045,self.normal_rms*.58))
        quiet=rms<limit
        style="whisper" if quiet and periodic<.42 else "normal"
        # Calibrate only confident, adequately audible normal speech. Never
        # learn from silence/whisper or TTS output.
        if style=="normal" and periodic>=.48 and rms>=.018:
            self.normal_rms=.85*self.normal_rms+.15*rms
        return style


def normalize_style(style) -> str:
    return "whisper" if style=="whisper" else "normal"
