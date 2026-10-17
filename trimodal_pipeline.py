"""Offline, real-model speech -> Whisper -> image -> local Vision -> Silero.

The supplied model engines must be real/initialized in production. Tests use
injected doubles to verify security and ordering, never to claim AI readiness.
Images/audio remain in memory, and permissions are checked before capture.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any
import numpy as np


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class CycleResult:
    transcript: str
    answer: str
    camera_used: bool
    source: str = 'camera'


class TriModalPipeline:
    def __init__(self, *, recognizer: Any, vision: Any, synthesizer: Any,
                 microphone: Any, camera: Any, screen: Any = None):
        self.recognizer = recognizer
        self.vision = vision
        self.synthesizer = synthesizer
        self.microphone = microphone
        self.camera = camera
        self.screen = screen
        self._active = False
        self._guard = Lock()

    def ready(self) -> bool:
        return all((self.recognizer.ready, self.vision.ready, self.synthesizer.ready))

    def run_once(self, *, camera_consent: bool = False, screen_consent: bool = False,
                 source: str = 'camera', seconds: float = 5.0,
                 play_audio: bool = True, audio_samples: Any = None,
                 sample_rate: int = 16_000) -> CycleResult:
        """One real inference turn, optional pre-recorded in-memory PCM for Vosk wake.

        When audio_samples is supplied, capture will NOT record the mic again.
        For camera and screen, grant permission before microphone/vision calls.
        """
        if source not in {'camera', 'screen'}:
            raise ValueError('Image source must be camera or screen')
        if source == 'camera' and not camera_consent:
            raise PermissionError('Explicit camera consent required')
        if source == 'screen' and not screen_consent:
            raise PermissionError('Explicit screen consent required')
        if source == 'screen' and self.screen is None:
            raise PipelineError('No screen capture backend')
        if not self._guard.acquire(blocking=False):
            raise PipelineError('Previous audio/vision turn still running')
        self._active = True
        try:
            if not self.ready():
                raise PipelineError('Initialize real Whisper, Vision and Silero models first')
            samples = self.microphone(seconds) if audio_samples is None else np.asarray(audio_samples)
            transcript = self.recognizer.transcribe(samples, sample_rate=sample_rate).strip()
            if not transcript:
                return CycleResult(transcript='', answer='', camera_used=False, source=source)
            grabber = self.camera if source == 'camera' else self.screen
            jpeg = grabber.capture_jpeg()
            answer = self.vision.describe(transcript, jpeg)
            if play_audio:
                self.synthesizer.play(answer)
            else:
                self.synthesizer.synthesize(answer)
            return CycleResult(transcript=transcript, answer=answer,
                               camera_used=source == 'camera', source=source)
        except Exception as exc:
            raise PipelineError(f'Vision-voice cycle failed: {exc}') from exc
        finally:
            self._active = False
            self._guard.release()
