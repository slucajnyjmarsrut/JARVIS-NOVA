"""Actual OpenAI Whisper inference, offline checkpoint only; no network downloads.

Production usage:
    recognizer = WhisperRecognizer(Path('models/base.pt'))
    recognizer.initialize()            # loads Whisper model from disk
    text = recognizer.transcribe(samples, sample_rate=16000)
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Callable

import numpy as np

from audio_io import prepare_audio, read_pcm16_wav, WHISPER_RATE


class WhisperInitializationError(RuntimeError):
    pass


# SHA256 published in the user-supplied whisper-20250625/whisper/__init__.py manifest.
OFFICIAL_BASE_SHA256 = "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e"


@dataclass(frozen=True)
class WhisperConfig:
    checkpoint: Path
    device: str = "cpu"
    language: str = "ru"
    min_seconds: float = 0.35
    max_seconds: float = 30.0
    silence_rms: float = 0.001
    check_sha256: bool = True


class WhisperRecognizer:
    def __init__(self, config: WhisperConfig, *, loader: Callable[..., Any] | None = None):
        self.config = config
        self._loader = loader
        self._model: Any = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def initialize(self) -> None:
        path = Path(self.config.checkpoint)
        if not path.is_file():
            raise WhisperInitializationError(
                f"Whisper checkpoint missing: {path}. "
                "The uploaded whisper-20250625.zip contains SOURCE, not base.pt model weights."
            )
        if path.stat().st_size < 10_000_000:
            raise WhisperInitializationError(f"Checkpoint too small or damaged: {path}")
        if self.config.check_sha256 and path.name == "base.pt":
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != OFFICIAL_BASE_SHA256:
                raise WhisperInitializationError(
                    "Whisper base.pt SHA256 mismatch: checkpoint is corrupted or not official"
                )
        try:
            if self._loader is None:
                import whisper
                load = whisper.load_model
            else:
                load = self._loader
            self._model = load(str(path), device=self.config.device)
        except Exception as exc:
            self._model = None
            raise WhisperInitializationError(f"Unable to load Whisper checkpoint: {exc}") from exc

    def transcribe(self, samples: np.ndarray, *, sample_rate: int) -> str:
        if not self.ready:
            raise WhisperInitializationError("Call initialize() before transcribe()")
        signal = prepare_audio(samples, sample_rate, target_rate=WHISPER_RATE)
        duration = len(signal) / WHISPER_RATE
        if not (self.config.min_seconds <= duration <= self.config.max_seconds):
            raise ValueError(f"Audio must be {self.config.min_seconds}–{self.config.max_seconds} seconds")
        rms = float(np.sqrt(np.mean(signal.astype(np.float64) ** 2)))
        if rms < self.config.silence_rms:
            return ""  # prevent hallucinations on digital silence
        result = self._model.transcribe(
            signal,
            language=self.config.language,
            task="transcribe",
            fp16=self.config.device.startswith("cuda"),
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.6,
        )
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise RuntimeError("Whisper returned an invalid result")
        return result["text"].strip()

    def transcribe_wav(self, file_path: str | Path) -> str:
        samples, rate = read_pcm16_wav(file_path)
        return self.transcribe(samples, sample_rate=rate)
