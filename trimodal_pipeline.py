"""Local Whisper -> screen snapshot -> Vision -> Silero. No webcam backend.

Camera capture is intentionally unsupported; live images can only come from
the explicitly consented screen-snapshot flow. No capture is performed before
source and permission validation. Image/audio remain RAM-only.
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
    source: str = 'screen'


class TriModalPipeline:
    def __init__(self, *, recognizer: Any, vision: Any, synthesizer: Any,
                 microphone: Any, screen: Any):
        self.recognizer=recognizer
        self.vision=vision
        self.synthesizer=synthesizer
        self.microphone=microphone
        self.screen=screen
        self._active=False
        self._guard=Lock()

    def ready(self) -> bool:
        return all((self.recognizer.ready,self.vision.ready,self.synthesizer.ready))

    def run_once(self, *, screen_consent: bool = False,
                 source: str = 'screen', seconds: float = 5.0,
                 play_audio: bool = True, audio_samples: Any = None,
                 sample_rate: int = 16_000) -> CycleResult:
        """Run one in-memory screen question; no camera or other source."""
        if source != 'screen':
            raise ValueError('Webcam disabled: only screen is supported')
        if not screen_consent:
            raise PermissionError('Explicit screen consent required')
        if self.screen is None:
            raise PipelineError('No screen capture backend')
        if not self._guard.acquire(blocking=False):
            raise PipelineError('Previous audio/vision turn still running')
        self._active=True
        try:
            if not self.ready():
                raise PipelineError('Initialize real Whisper, Vision and Silero models first')
            samples=(self.microphone(seconds) if audio_samples is None
                     else np.asarray(audio_samples))
            transcript=self.recognizer.transcribe(samples,sample_rate=sample_rate).strip()
            if not transcript:
                return CycleResult(transcript='',answer='')
            jpeg=self.screen.capture_jpeg()
            answer=self.vision.describe(transcript,jpeg)
            if play_audio:
                self.synthesizer.play(answer)
            else:
                self.synthesizer.synthesize(answer)
            return CycleResult(transcript=transcript,answer=answer)
        except Exception as exc:
            raise PipelineError(f'Vision-voice cycle failed: {exc}') from exc
        finally:
            self._active=False
            self._guard.release()
