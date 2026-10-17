# -*- coding: utf-8 -*-
"""Build-time model fetch. End users never download models."""
from pathlib import Path
import hashlib, urllib.request, os

ROOT=Path(__file__).resolve().parent
models=ROOT/"assets"/"models"
models.mkdir(exist_ok=True,parents=True)

def download_silero():
    path=models/"v5_ru.pt"
    if not path.is_file() or path.stat().st_size < 1_000_000:
        url="https://models.silero.ai/models/tts/ru/v5_ru.pt"
        temp=path.with_suffix(".partial")
        with urllib.request.urlopen(url,timeout=90) as response, temp.open("wb") as out:
            while True:
                block=response.read(1024*1024)
                if not block:break
                out.write(block)
        if temp.stat().st_size<1_000_000:raise RuntimeError("Silero model incomplete")
        temp.replace(path)
    return path

def download_whisper():
    # Whisper library validates the published checkpoint digest during download.
    import whisper
    path=models/"base.pt"
    if not path.is_file():
        whisper.load_model("base",device="cpu",download_root=str(models))
    if not path.is_file() or path.stat().st_size<10_000_000:
        raise RuntimeError("Whisper model incomplete")
    from verify_models import WHISPER_BASE_SHA256, hash_file
    if hash_file(path)!=WHISPER_BASE_SHA256:
        raise RuntimeError("Whisper model checksum mismatch")
    return path

def main():
    for path in [download_silero(), download_whisper()]:
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        print(path.name,path.stat().st_size,"SHA256:",digest)
    required=["am/final.mdl","graph/Gr.fst","graph/HCLr.fst",
              "graph/disambig_tid.int","graph/phones/word_boundary.int"]
    for rel in required:
        if not (models/"vosk"/rel).is_file(): raise RuntimeError("Vosk missing: "+rel)
    print("All model prerequisites present.")
if __name__=="__main__":main()
