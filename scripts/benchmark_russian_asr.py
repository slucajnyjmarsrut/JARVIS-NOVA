# -*- coding: utf-8 -*-
"""Offline Russian speech benchmark (WER/CER, wake detection and CPU latency).

Run against consented, locally held WAV recordings. No uploads, model
downloads, retained audio, or transcription logs; reports are aggregate-only.
Examples:
  python -m scripts.benchmark_russian_asr --manifest my_phrases.csv --model-path assets/base.pt
  python -m scripts.benchmark_russian_asr --manifest my_phrases.csv --model-path assets/small.pt

The manifest is a UTF-8 CSV with headers: audio,reference.
Audio paths are relative to the CSV. Record the SAME phrases, microphone
and ambient conditions when comparing models or another voice assistant.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
from pathlib import Path

from agent_core import WAKE


def words(value: str) -> list[str]:
    """Russian/cross-language normalization for word-level error metrics."""
    return re.findall(r"[а-яa-z0-9]+", str(value).casefold().replace("ё", "е"))


def edit_distance(expected, actual) -> int:
    """Levenshtein insertions/deletions/substitutions with bounded RAM."""
    previous=list(range(len(actual)+1))
    for row, left in enumerate(expected, 1):
        current=[row]
        for col, right in enumerate(actual, 1):
            current.append(min(
                current[col-1]+1,
                previous[col]+1,
                previous[col-1]+(left!=right)))
        previous=current
    return previous[-1]


def percentile_nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered=sorted(values)
    return round(ordered[max(0,math.ceil(fraction*len(ordered))-1)], 3)


def score_pairs(pairs) -> dict:
    """Each record is (expected_text, recognized_text, latency, audio_seconds).

    No individual transcript is returned or written; a local user can keep
    their own consented input CSV and compare aggregate WER/CER over time.
    """
    samples=word_total=word_errors=char_total=char_errors=0
    wake_expected=wake_found=nonwake_expected=false_wakes=0
    latencies=[]
    realtime=[]
    for expected,recognized,latency,duration in pairs:
        if latency<0 or duration<=0:
            raise ValueError("Speech benchmark timing must be non-negative")
        ref=words(expected)
        hyp=words(recognized)
        samples+=1
        word_total+=len(ref)
        word_errors+=edit_distance(ref,hyp)
        left=" ".join(ref)
        right=" ".join(hyp)
        char_total+=len(left)
        char_errors+=edit_distance(left,right)
        expected_wake=bool(WAKE.match(str(expected)))
        decoded_wake=bool(WAKE.match(str(recognized)))
        if expected_wake:
            wake_expected+=1
            wake_found+=int(decoded_wake)
        else:
            nonwake_expected+=1
            false_wakes+=int(decoded_wake)
        latencies.append(float(latency))
        realtime.append(float(latency)/float(duration))
    if not samples:
        raise ValueError("Speech benchmark must contain at least one phrase")
    return {
        "phrases":samples,
        "reference_words":word_total,
        "word_errors":word_errors,
        "wer":round(word_errors/word_total,4) if word_total else None,
        "cer":round(char_errors/char_total,4) if char_total else None,
        "wake_recall":round(wake_found/wake_expected,4) if wake_expected else None,
        "false_wake_rate":round(false_wakes/nonwake_expected,4) if nonwake_expected else None,
        "wake_phrases":wake_expected,
        "nonwake_phrases":nonwake_expected,
        "latency_p50_s":percentile_nearest_rank(latencies,.5),
        "latency_p95_s":percentile_nearest_rank(latencies,.95),
        "real_time_factor_p50":percentile_nearest_rank(realtime,.5),
        "recordings_uploaded":False,
    }


def benchmark_wavs(manifest: Path, model_path: Path, model_loader=None) -> dict:
    """Decode consented WAV files using locally installed, verified Whisper.

    Real recordings are kept only in memory during each decode. A summary
    never contains raw audio, individual transcripts or source file names.
    """
    manifest=Path(manifest)
    model_path=Path(model_path)
    if not manifest.is_file():
        raise FileNotFoundError("Manifest CSV not found")
    if not model_path.is_file():
        raise FileNotFoundError("Whisper model checkpoint not found locally")
    with manifest.open("r",encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if not {"audio","reference"}.issubset(reader.fieldnames or []):
            raise ValueError("Manifest needs audio,reference columns")
        rows=list(reader)
    if not rows:
        raise ValueError("Manifest is empty")
    # Avoid loading hundreds of MB of weights for a malformed manifest.
    sources=[]
    for item in rows:
        if not (item.get("audio") or "").strip() or not (item.get("reference") or "").strip():
            raise ValueError("Missing audio or reference text")
        path=(manifest.parent/item["audio"]).resolve()
        if path.suffix.casefold()!=".wav" or not path.is_file():
            raise ValueError("Input must be an existing PCM16 .wav file")
        sources.append((path,item["reference"]))

    from audio_io import prepare_audio, read_pcm16_wav
    from speech_capture import prepare_whisper_audio
    if model_loader is None:
        import whisper
        model_loader=whisper.load_model
    model=model_loader(str(model_path),device="cpu")

    def measured():
        for path,reference in sources:
            samples,rate=read_pcm16_wav(path)
            normalized=prepare_audio(samples,rate)
            pcm=(normalized*32767).clip(-32768,32767).astype("<i2").tobytes()
            speech=prepare_whisper_audio(pcm)
            started=time.perf_counter()
            result=model.transcribe(
                speech,language="ru",fp16=False,temperature=0,
                condition_on_previous_text=False,beam_size=2,best_of=1,
                no_speech_threshold=.65)
            latency=time.perf_counter()-started
            yield reference,str(result.get("text","") or ""),latency,len(normalized)/16000

    return score_pairs(measured())


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True,
                        help="Local audio,reference CSV. No audio is uploaded.")
    parser.add_argument("--model-path",type=Path,required=True,
                        help="Existing local base.pt or small.pt. Never downloaded.")
    parser.add_argument("--output-json",type=Path,
                        help="Optional local aggregate-only benchmark report")
    opts=parser.parse_args(argv)
    summary=benchmark_wavs(opts.manifest,opts.model_path)
    report=json.dumps(summary,ensure_ascii=False,indent=2)+"\n"
    print(report,end="")
    if opts.output_json is not None:
        opts.output_json.write_text(report,encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
