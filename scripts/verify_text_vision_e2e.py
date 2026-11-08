# -*- coding: utf-8 -*-
"""Actual local Qwen Vision inference from synthetic JPEG; zero voice dependencies."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import sys

# Both `python scripts/verify_text_vision_e2e.py` and frozen EXE are supported.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from vision_engine import LocalOllamaVision, VisionConfig


def assets_root():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))/"assets"


def main() -> int:
    for out in (sys.stdout,sys.stderr):
        if out is not None and hasattr(out,"reconfigure"):
            out.reconfigure(encoding="utf-8", errors="backslashreplace")
    runtime=BundledVisionRuntime(BundledRuntimeConfig(root=assets_root(),startup_seconds=90))
    try:
        picture=Image.new("RGB",(512,512),"white")
        ImageDraw.Draw(picture).rectangle((80,80,430,430),fill=(240,24,30))
        memory=BytesIO()
        picture.save(memory,format="JPEG",quality=92)
        endpoint=runtime.start()
        vision=LocalOllamaVision(VisionConfig(endpoint=endpoint,timeout_seconds=240))
        vision.initialize()
        answer=vision.describe("Какого цвета квадрат на изображении?",memory.getvalue())
        if "красн" not in answer.casefold():
            raise RuntimeError("Local Qwen Vision could not identify the red square")
        print("REAL QWEN VISION E2E PASS: image processed offline, no speech/microphone",flush=True)
        return 0
    except Exception as exc:
        print("QWEN VISION E2E FAILED: "+type(exc).__name__+": "+str(exc),
              file=sys.stderr,flush=True)
        return 1
    finally:
        runtime.stop()


if __name__=="__main__":
    raise SystemExit(main())
