"""REQUIRES REAL BUNDLED MODELS. Hardware-free semantic E2E, NO model mocks.

Generates Russian speech with REAL Silero -> transcribes with REAL Whisper ->
asks REAL local Gemma3 Vision about an in-memory red square -> generates the
REAL Vision response speech with Silero. It is not a microphone/camera test.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import sys

import numpy as np
from PIL import Image, ImageDraw

from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from speaker import assets
from silero_engine import SileroConfig, SileroSynthesizer
from vision_engine import LocalOllamaVision, VisionConfig
from whisper_engine import WhisperConfig, WhisperRecognizer


def main() -> int:
    # Windows PowerShell and GUI-subsystem EXEs may have a legacy output codepage
    # or no stdout stream at all. Never break a REAL inference test when the
    # generated Russian transcript contains non-ASCII characters.
    for out in (sys.stdout, sys.stderr):
        if out is not None and hasattr(out, "reconfigure"):
            out.reconfigure(encoding="utf-8", errors="backslashreplace")
    root=assets().parent
    models=root/'models'
    runtime=BundledVisionRuntime(BundledRuntimeConfig(root=root,startup_seconds=90))
    try:
        print('REAL-E2E: load verified Whisper and real Silero',flush=True)
        asr=WhisperRecognizer(WhisperConfig(models/'base.pt'))
        tts=SileroSynthesizer(SileroConfig(models/'v5_ru.pt'))
        asr.initialize()
        tts.initialize()
        # Use genuinely synthesized speech rather than a fabricated transcript.
        question='Джарвис, какого цвета квадрат на картинке?'
        russian_audio=tts.synthesize(question)
        if russian_audio.size < 16000 or float(np.max(np.abs(russian_audio))) < 0.01:
            raise RuntimeError('Silero did not produce meaningful audio')
        transcript=asr.transcribe(russian_audio,sample_rate=48000)
        print('REAL-E2E Whisper transcript:',transcript,flush=True)
        lowered=transcript.casefold().replace('ё','е')
        if 'цвет' not in lowered or 'квадрат' not in lowered:
            raise RuntimeError('Whisper did not understand the Russian utterance')
        image=Image.new('RGB',(512,512),'white')
        ImageDraw.Draw(image).rectangle((90,90,420,420),fill=(235,24,30))
        memory=BytesIO(); image.save(memory,format='JPEG',quality=92)
        print('REAL-E2E: start bundled offline Vision and answer about pixels',flush=True)
        endpoint=runtime.start()
        vision=LocalOllamaVision(VisionConfig(endpoint=endpoint,timeout_seconds=240))
        vision.initialize()
        answer=vision.describe(transcript,memory.getvalue())
        print('REAL-E2E Vision answer:',answer,flush=True)
        if 'красн' not in answer.casefold():
            raise RuntimeError('Vision did not correctly identify the RED square')
        spoken_answer=tts.synthesize(answer)
        if spoken_answer.size < 5000 or float(np.max(np.abs(spoken_answer))) < 0.01:
            raise RuntimeError('Silero output response contains no meaningful speech PCM')
        print(f'REAL-E2E PASS: three real engines; response samples={spoken_answer.size}',flush=True)
        print('LIMITS: synthetic image and synthetic spoken question; live Windows mic/camera/playback NOT tested',flush=True)
        return 0
    except Exception as exc:
        print(f'REAL-E2E FAILED: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        return 1
    finally:
        runtime.stop()


if __name__=='__main__':
    raise SystemExit(main())
