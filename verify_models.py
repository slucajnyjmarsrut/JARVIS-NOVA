"""Run real offline model load/inference checks on the Windows build runner.

This intentionally fails packaging when a model is missing or incompatible.
No microphone or audio output is required during these checks.
"""
from pathlib import Path
import hashlib
import os
import sys

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / 'assets' / 'models'
WHISPER_BASE_SHA256 = 'ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e'


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def main():
    import numpy as np
    import torch
    import whisper
    from vosk import Model as VoskModel, KaldiRecognizer, SetLogLevel

    torch.set_num_threads(2)
    silero = MODELS / 'v5_ru.pt'
    wh = MODELS / 'base.pt'
    vosk = MODELS / 'vosk'
    if not silero.is_file(): raise RuntimeError('Silero model absent')
    if not wh.is_file(): raise RuntimeError('Whisper model absent')
    if hash_file(wh) != WHISPER_BASE_SHA256:
        raise RuntimeError('Whisper base checkpoint checksum does not match official manifest')

    print('Loading Silero v5_ru model...', flush=True)
    voice = torch.package.PackageImporter(str(silero)).load_pickle('tts_models','model')
    voice.to('cpu')
    audio = voice.apply_tts(text='Привет! Проверка русского голоса.', speaker='xenia',sample_rate=48000)
    if audio.numel() < 2000: raise RuntimeError('Silero produced empty audio')
    print('Silero generated',audio.numel(),'samples',flush=True)

    print('Loading Whisper base model...',flush=True)
    model = whisper.load_model(str(wh),device='cpu')
    if model is None: raise RuntimeError('Whisper failed to load')
    del model
    print('Whisper loaded; SHA256 OK',flush=True)

    print('Loading Vosk model...',flush=True)
    SetLogLevel(-1)
    model = VoskModel(str(vosk))
    rec = KaldiRecognizer(model, 16000)
    if not rec.AcceptWaveform(bytes(16000 * 2)):
        rec.FinalResult()
    print('Vosk model verified',flush=True)


if __name__ == '__main__':
    main()
