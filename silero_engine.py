"""Russian Silero v5 TTS from a local .pt torch.package checkpoint.

Returns audio samples in RAM; playing them requires sounddevice + an audio output.
No installer EXE is executed, no model is silently downloaded.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


class SileroInitializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SileroConfig:
    checkpoint: Path
    device: str = "cpu"
    speaker: str = "xenia"
    sample_rate: int = 48_000


class SileroSynthesizer:
    def __init__(self, config: SileroConfig, *, loader: Callable[[Path], Any] | None = None):
        self.config = config
        self._loader = loader
        self._model: Any = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def initialize(self) -> None:
        path = Path(self.config.checkpoint)
        if not path.is_file():
            raise SileroInitializationError(
                f"Silero checkpoint missing: {path}. "
                "A SileroTTS installer EXE is not a v5_ru.pt checkpoint."
            )
        if path.stat().st_size < 1_000_000:
            raise SileroInitializationError(f"Checkpoint too small or damaged: {path}")
        try:
            if self._loader is not None:
                model = self._loader(path)
            else:
                import torch
                model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
            self._model = model.to(self.config.device)
        except Exception as exc:
            self._model = None
            raise SileroInitializationError(f"Unable to load Silero checkpoint: {exc}") from exc

    def synthesize(self, text: str) -> np.ndarray:
        """Synthesize a single short utterance into mono float32 PCM at 48000 Hz."""
        if not self.ready:
            raise SileroInitializationError("Call initialize() before synthesize()")
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            raise ValueError("Cannot synthesize an empty utterance")
        if len(cleaned) > 400:
            raise ValueError("Split long text into sentences of 400 characters or less")
        import torch
        with torch.inference_mode():
            audio = self._model.apply_tts(
                text=cleaned,
                speaker=self.config.speaker,
                sample_rate=self.config.sample_rate,
            )
        if isinstance(audio, torch.Tensor):
            array = audio.detach().cpu().float().numpy()
        else:
            array = np.asarray(audio, dtype=np.float32)
        array = np.ravel(array).astype(np.float32, copy=False)
        if array.size == 0 or not np.all(np.isfinite(array)):
            raise RuntimeError("Silero returned empty or invalid audio")
        return np.ascontiguousarray(np.clip(array, -1.0, 1.0))

    def play(self, text: str) -> None:
        """Optional audible playback, blocks until finished; suspends microphone in future pipeline."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("Playback needs the sounddevice package") from exc
        pcm = self.synthesize(text)
        sd.play(pcm, samplerate=self.config.sample_rate, blocking=True)
