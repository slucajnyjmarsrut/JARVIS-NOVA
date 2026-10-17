"""Audio conversion shared by the ASR and capture modules. No files created."""
from __future__ import annotations

from math import gcd
from pathlib import Path
import wave

import numpy as np
from scipy.signal import resample_poly


WHISPER_RATE = 16_000


class AudioFormatError(ValueError):
    pass


def prepare_audio(samples: np.ndarray, sample_rate: int, *, target_rate: int = WHISPER_RATE) -> np.ndarray:
    """Convert mono/stereo floating or signed-integer PCM to 16-kHz mono float32 [-1, 1]."""
    if not 8_000 <= sample_rate <= 192_000:
        raise AudioFormatError(f"Invalid source sample rate: {sample_rate}")
    array = np.asarray(samples)
    if array.ndim == 2:
        if not 1 <= array.shape[1] <= 2:
            raise AudioFormatError("Expected 1 or 2 audio channels")
    elif array.ndim != 1:
        raise AudioFormatError("Expected mono or stereo audio")
    if array.size == 0:
        raise AudioFormatError("Empty audio")
    if np.issubdtype(array.dtype, np.signedinteger):
        scale = float(max(abs(np.iinfo(array.dtype).min), np.iinfo(array.dtype).max))
        array = array.astype(np.float32) / scale
    elif np.issubdtype(array.dtype, np.floating):
        array = array.astype(np.float32)
    else:
        raise AudioFormatError(f"Unsupported sample data type: {array.dtype}")
    if not np.all(np.isfinite(array)):
        raise AudioFormatError("Audio contains NaN/Inf")
    if array.ndim == 2:
        array = array.mean(axis=1)
    if sample_rate != target_rate:
        divisor = gcd(sample_rate, target_rate)
        array = resample_poly(array, target_rate // divisor, sample_rate // divisor)
    return np.ascontiguousarray(np.clip(array, -1.0, 1.0), dtype=np.float32)


def read_pcm16_wav(file_path: str | Path) -> tuple[np.ndarray, int]:
    """Read only uncompressed PCM16 WAV (deliberately avoids an ffmpeg subprocess)."""
    with wave.open(str(file_path), "rb") as f:
        if f.getcomptype() != "NONE" or f.getsampwidth() != 2:
            raise AudioFormatError("Expected uncompressed 16-bit PCM WAV")
        channels = f.getnchannels()
        rate = f.getframerate()
        if channels not in (1, 2):
            raise AudioFormatError("Expected mono or stereo WAV")
        raw = f.readframes(f.getnframes())
    values = np.frombuffer(raw, dtype="<i2")
    if channels == 2:
        values = values.reshape(-1, 2)
    return values, rate
