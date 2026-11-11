# -*- coding: utf-8 -*-
"""Actual local Qwen classifies natural JARVIS commands; no shell or devices."""
from __future__ import annotations
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from semantic_intent_router import classify_local_intent


def main() -> int:
    for stream in (sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="backslashreplace")
    root=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))
    runtime=BundledVisionRuntime(BundledRuntimeConfig(
        root=root/"assets",startup_seconds=90))
    cases=(
        ("можешь показать параметры приложения", "settings"),
        ("хочу перейти в видеостудию и заняться роликом", "studio"),
        ("давай откроем редактор монтажных дорожек", "timeline"),
    )
    passed=0
    try:
        for idx,(phrase,expected) in enumerate(cases,1):
            try:
                decision=classify_local_intent(phrase,runtime)
                actual=decision.kind if decision is not None else "none"
                ok=actual==expected
                print("REAL QWEN INTENT "+("PASS" if ok else "FAIL")
                      +f" {idx}/{len(cases)} expected={expected} got={actual}",
                      flush=True)
                passed+=int(ok)
            except Exception as exc:
                print("REAL QWEN INTENT ERROR: "+type(exc).__name__+": "
                      +str(exc)[:250],file=sys.stderr,flush=True)
        print(f"REAL QWEN INTENT SCORE: {passed}/{len(cases)}",flush=True)
        return 0 if passed==len(cases) else 1
    finally:
        runtime.stop()


if __name__=="__main__":
    raise SystemExit(main())
