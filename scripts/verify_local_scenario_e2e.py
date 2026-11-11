# -*- coding: utf-8 -*-
"""REAL offline Qwen scenario generation, approval-independent test artifacts.

Runs only on CI that already downloaded verified Qwen weights. A template
fallback is a FAIL: it cannot be represented as real autonomous AI work.
No external HTTP, no source footage, no voice, and no publishing.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from video_scenario_autonomy import create_checked_scenario
from viral_studio import load_brief, save_brief


def main() -> int:
    parser=argparse.ArgumentParser(description="Verify real Qwen, never a template.")
    parser.add_argument("--topics",type=int,choices=(1,3),default=1,
                        help="1 standard topic or 3 diverse independent topics")
    args=parser.parse_args()
    for out in (sys.stdout,sys.stderr):
        if out is not None and hasattr(out,"reconfigure"):
            out.reconfigure(encoding="utf-8",errors="backslashreplace")
    assets=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))/"assets"
    runtime=BundledVisionRuntime(BundledRuntimeConfig(
        root=assets,startup_seconds=90))
    topics=(
        "Безопасная организация компьютерного рабочего места",
        "Приготовление овощного салата дома",
        "Как построить небольшой дом в Minecraft",
    )[:args.topics]
    failures=0
    try:
        for index,topic in enumerate(topics,1):
            try:
                brief,note,report,attempts=create_checked_scenario(
                    topic,mode="deep",runtime=runtime,max_revisions=2)
                if not report.passed:
                    raise RuntimeError("Сценарий не прошёл структуру: "
                                       +"; ".join(report.issues))
                if "локальная Qwen" not in brief.generator:
                    raise RuntimeError(
                        "ИИ не справился: получен шаблон, а не сценарий Qwen. "+note)
                if not 20<=report.seconds<=65:
                    raise RuntimeError("Фактическая длительность сценария неверна: "
                                       +str(report.seconds))
                with tempfile.TemporaryDirectory(prefix="nova-real-scenario-") as tmp:
                    project=Path(tmp)/"scenario"
                    file=save_brief(brief,project)
                    if load_brief(file)!=brief:
                        raise RuntimeError("Сценарий не восстановился из JSON.")
                    notes=project/"WHAT_TO_FILM_RU.md"
                    if not notes.is_file() or "Что снять" not in notes.read_text("utf-8"):
                        raise RuntimeError("Отсутствует текстовый план съёмки.")
                print("REAL QWEN SCENARIO PASS: "+str(index)+"/"+str(len(topics))
                      +" topic="+topic+"; "+str(attempts)
                      +" attempts, "+str(round(report.seconds,1))
                      +" sec, all checks valid; no audio/network/cloud",flush=True)
            except Exception as exc:
                failures+=1
                print("REAL QWEN SCENARIO FAILED: "+str(index)+"/"+str(len(topics))
                      +" topic="+topic+"; "+type(exc).__name__+": "+str(exc),
                      file=sys.stderr,flush=True)
        print("REAL QWEN SCENARIO SCORE: "
              +str(len(topics)-failures)+"/"+str(len(topics)),flush=True)
        return 1 if failures else 0
    finally:
        runtime.stop()


if __name__=="__main__":
    raise SystemExit(main())
