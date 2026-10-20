"""Stage 2 inference engines wired into the existing RC4 Windows application.

Production constructors never use fakes; models and portable Vision binary MUST
already be bundled by the Windows build. No online API or silent downloads.
"""
from __future__ import annotations

from pathlib import Path
import threading
import numpy as np

from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from microphone import record_utterance
from screen_capture import ScreenFrameSource
from silero_engine import SileroConfig, SileroSynthesizer
from speaker import assets
from trimodal_pipeline import TriModalPipeline
from vision_engine import LocalOllamaVision, VisionConfig
from whisper_engine import WhisperConfig, WhisperRecognizer


class TrimodalService:
    def __init__(self, *, asset_root: Path | None = None,
                 runtime=None, recognizer=None, synthesizer=None, vision=None,
                 microphone=record_utterance, screen=None):
        root = asset_root or assets().parent
        models = root / 'models'
        self.runtime = runtime or BundledVisionRuntime(BundledRuntimeConfig(root=root))
        self.recognizer = recognizer or WhisperRecognizer(
            WhisperConfig(models / 'base.pt'))
        self.synthesizer = synthesizer or SileroSynthesizer(
            SileroConfig(models / 'v5_ru.pt'))
        self.vision = vision
        self._make_vision = vision is None
        self._microphone = microphone
        self._screen = screen or ScreenFrameSource()
        self._stop = threading.Event()
        self._busy = threading.Event()
        self._ready = False
        self._lock = threading.RLock()

    @property
    def speaking(self) -> bool:
        """Used by the Vosk mic to suppress echo and overlapping input."""
        return self._busy.is_set()

    @property
    def ready(self) -> bool:
        return self._ready and not self._stop.is_set()

    def initialize(self) -> None:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError('JARVIS is closing')
            if self.ready:
                return
            try:
                self.recognizer.initialize()
                self.synthesizer.initialize()
                endpoint = self.runtime.start()
                if self._stop.is_set():
                    raise RuntimeError('JARVIS closed during initialization')
                if self._make_vision:
                    self.vision = LocalOllamaVision(VisionConfig(endpoint=endpoint))
                self.vision.initialize()
                if self._stop.is_set():
                    raise RuntimeError('JARVIS closed during model initialization')
                self._ready = True
            except Exception:
                self._ready = False
                self.runtime.stop()
                raise

    def run_once(self, *, source: str = 'screen',
                 screen_consent: bool = False, seconds: float = 5.0,
                 audio_samples=None, sample_rate: int = 16_000):
        if source != 'screen':
            raise ValueError('Webcam capture has been removed from JARVIS NOVA')
        if not self.ready:
            raise RuntimeError('Trimodal engines not initialized')
        if self._busy.is_set():
            raise RuntimeError('Trimodal request already executing')
        self._busy.set()
        try:
            pipeline = TriModalPipeline(
                recognizer=self.recognizer, vision=self.vision,
                synthesizer=self.synthesizer, microphone=self._microphone,
                screen=self._screen)
            if self._stop.is_set():
                raise RuntimeError('JARVIS is closing')
            return pipeline.run_once(
                source=source, screen_consent=screen_consent, seconds=seconds,
                audio_samples=audio_samples, sample_rate=sample_rate)
        finally:
            self._busy.clear()

    def shutdown(self) -> None:
        self._stop.set()
        self._ready = False
        try:
            import sounddevice as sd
            sd.stop()
        except (ImportError, OSError):
            pass
        self.runtime.stop()
