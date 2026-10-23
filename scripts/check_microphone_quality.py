# -*- coding: utf-8 -*-
"""5-second local microphone diagnostic. No audio files, network or models.

Example: python -m scripts.check_microphone_quality --seconds 5
Speak normally while this runs. Only aggregate levels and error counts print.
"""
from __future__ import annotations
import argparse
import json
import math
import queue
import time

import numpy as np


def _dbfs(level: float) -> float:
    return round(20*math.log10(max(float(level),1.0)/32768.0),1)


def summarize_pcm_packets(packets, sample_rate: int, *, overflows=0, lost=0) -> dict:
    """Aggregate raw PCM16 frames; never return raw samples or transcripts."""
    if not 8000 <= sample_rate <= 192000:
        raise ValueError("Invalid input sample rate")
    rms=[]
    clipped=total=zeros=0
    for packet in packets:
        if len(packet)%2:
            raise ValueError("Odd PCM16 frame length")
        if not packet:
            continue
        pcm=np.frombuffer(packet,dtype="<i2")
        if not pcm.size:
            continue
        levels=pcm.astype(np.float64)
        value=float(np.sqrt(np.mean(levels*levels)))
        rms.append(value)
        zeros+=int(value<1.0)
        total+=len(pcm)
        clipped+=int(np.count_nonzero((pcm>=32760)|(pcm<=-32760)))
    if not rms:
        raise ValueError("No audio packets received")
    median=float(np.median(rms))
    high=float(np.percentile(rms,90))
    clipping=round(100.0*clipped/total,3)
    notes=[]
    if median<15 and high<35:
        notes.append("Очень тихий сигнал: проверь выбранный микрофон и уровень Windows.")
    if clipping>=0.5:
        notes.append("Перегрузка микрофона: убавь входной уровень Windows.")
    if overflows or lost:
        notes.append("Пропущены аудиоблоки: проверь нагрузку CPU и Bluetooth/драйвер.")
    if not notes:
        notes.append("Критических проблем по уровню не обнаружено; точность слов оцени отдельно.")
    return {
        "sample_rate_hz":int(sample_rate),
        "packets_received":len(rms),
        "median_level_dbfs":_dbfs(median),
        "p90_level_dbfs":_dbfs(high),
        "clipped_samples_percent":clipping,
        "near_silent_packets":zeros,
        "portaudio_overflows":int(overflows),
        "queue_dropped_packets":int(lost),
        "diagnostics":notes,
        "audio_recordings_saved":False,
    }


def inspect_live_microphone(*,seconds: float=5.0,device: int | None=None) -> dict:
    """Stream sounddevice input only into a small private RAM queue."""
    if not 1.0<=seconds<=15.0:
        raise ValueError("Choose from 1 to 15 seconds")
    import sounddevice as sd
    device_info=sd.query_devices(device,kind="input")
    rate=int(round(device_info["default_samplerate"]))
    if not 8000<=rate<=192000:
        raise ValueError("Unsupported mic sample rate")
    packets=queue.Queue(maxsize=200)
    overflows=[0]
    dropped=[0]

    def callback(indata,frames,tm,status):
        if bool(getattr(status,"input_overflow",False)):
            overflows[0]+=1
        try:
            packets.put_nowait(bytes(indata))
        except queue.Full:
            dropped[0]+=1

    print("Произнеси несколько русских фраз обычным и тихим голосом.")
    with sd.RawInputStream(samplerate=rate,blocksize=max(256,rate//10),
                           channels=1,dtype="int16",device=device,
                           callback=callback):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            time.sleep(min(.05,max(.0,deadline-time.monotonic())))
    frames=[]
    while not packets.empty():
        frames.append(packets.get_nowait())
    result=summarize_pcm_packets(
        frames,rate,overflows=overflows[0],lost=dropped[0])
    result["sampled_seconds"]=round(seconds,1)
    return result


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=float,default=5.0)
    parser.add_argument("--device",type=int,default=None,
                        help="Optional Windows sounddevice index")
    args=parser.parse_args(argv)
    report=inspect_live_microphone(seconds=args.seconds,device=args.device)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
