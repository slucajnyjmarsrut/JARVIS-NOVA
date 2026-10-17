"""Fixed-duration microphone capture. Real PortAudio backend via sounddevice."""
from __future__ import annotations

import numpy as np

from audio_io import prepare_audio, WHISPER_RATE


def record_utterance(seconds: float = 5.0, *, device: int | str | None = None) -> np.ndarray:
    if not 0.5 <= seconds <= 30.0:
        raise ValueError("Recording must be 0.5–30 seconds")
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Install sounddevice and provide an input device") from exc
    dev = sd.query_devices(device, kind="input")
    native_rate = int(round(dev["default_samplerate"]))
    if native_rate <= 0:
        raise RuntimeError("Microphone reports invalid sample rate")
    samples = sd.rec(
        int(round(seconds * native_rate)),
        samplerate=native_rate,
        channels=1,
        dtype="float32",
        device=device,
        blocking=True,
    )
    return prepare_audio(samples, native_rate, target_rate=WHISPER_RATE)
