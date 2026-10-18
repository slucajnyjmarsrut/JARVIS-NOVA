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


VOSK_RU_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
# Independent published SHA256 of this official Vosk small Russian archive.
VOSK_RU_SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"


def download_vosk():
    import tempfile
    import zipfile
    import shutil
    model_dir = models / "vosk"
    if (model_dir / "am" / "final.mdl").is_file():
        return model_dir
    with tempfile.TemporaryDirectory(prefix="jarvis-vosk-") as tmp:
        archive = Path(tmp) / "ru.zip"
        sha = hashlib.sha256()
        with urllib.request.urlopen(VOSK_RU_URL, timeout=180) as stream, archive.open("wb") as out:
            for part in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(part)
                out.write(part)
        if sha.hexdigest() != VOSK_RU_SHA256:
            raise RuntimeError("Official Vosk archive SHA256 mismatch")
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            prefix = "vosk-model-small-ru-0.22/"
            for member in members:
                name = member.filename.replace("\\\\", "/")
                if not name.startswith(prefix) or ".." in name.split("/") or name.startswith("/"):
                    raise RuntimeError("Untrusted path in Vosk archive")
                if member.is_dir():
                    continue
                target = Path(tmp) / "model" / name[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        extracted = Path(tmp) / "model"
        if not (extracted / "am" / "final.mdl").is_file():
            raise RuntimeError("Vosk archive extraction failed")
        shutil.move(str(extracted), str(model_dir))
    return model_dir

def main():
    download_vosk()
    for path in [download_silero(), download_whisper()]:
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        print(path.name,path.stat().st_size,"SHA256:",digest)
    required=["am/final.mdl","graph/Gr.fst","graph/HCLr.fst",
              "graph/disambig_tid.int","graph/phones/word_boundary.int"]
    for rel in required:
        if not (models/"vosk"/rel).is_file(): raise RuntimeError("Vosk missing: "+rel)
    print("All model prerequisites present.")
if __name__=="__main__":main()
