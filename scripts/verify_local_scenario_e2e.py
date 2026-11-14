# -*- coding: utf-8 -*-
"""REAL optional Gemma3:4b screenplay acceptance, not a Qwen-Vision proxy.

Run manually after installing Gemma3:4b into an already-running LOCAL Ollama.
No automatic downloads, cloud APIs, publishing, user-file deletion or speech.
A deterministic fallback is always a failure for this real-model acceptance.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_ai_registry import get_specialist, specialist_available
from video_scenario_autonomy import create_checked_scenario
from viral_studio import save_brief, load_brief


TOPICS = (
    "Безопасная организация компьютерного рабочего места",
    "Приготовление овощного салата дома",
    "Как построить небольшой дом в Minecraft",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify an installed Gemma3 screenwriter, never Qwen Vision.")
    parser.add_argument("--topics", type=int, choices=(1, 3), default=1)
    args = parser.parse_args()
    for out in (sys.stdout, sys.stderr):
        if out is not None and hasattr(out, "reconfigure"):
            out.reconfigure(encoding="utf-8", errors="backslashreplace")
    model = get_specialist("scenario").model
    try:
        if not specialist_available("scenario"):
            raise RuntimeError(
                f"{model} not installed in running local Ollama. "
                f"Consent to installation separately: ollama pull {model}")
    except Exception as exc:
        print("REAL GEMMA SCENARIO NOT RUN: " + str(exc),
              file=sys.stderr, flush=True)
        return 2
    failures = 0
    for index, topic in enumerate(TOPICS[:args.topics], 1):
        try:
            brief, note, report, attempts = create_checked_scenario(
                topic, mode="deep", max_revisions=2)
            if not report.passed:
                raise RuntimeError("Scenario failed checks: " +
                                   "; ".join(report.issues))
            if brief.generator != "локальная Gemma3:4b":
                raise RuntimeError(
                    "Real Gemma generation FAILED (non-AI fallback): " + note)
            if not 20 <= report.seconds <= 50:
                raise RuntimeError("Invalid scene duration: " +
                                   str(report.seconds))
            with tempfile.TemporaryDirectory(prefix="nova-gemma-script-") as tmp:
                project = Path(tmp) / "scenario"
                filename = save_brief(brief, project)
                if load_brief(filename) != brief:
                    raise RuntimeError("Scenario did not survive JSON roundtrip")
                plan = project / "WHAT_TO_FILM_RU.md"
                if not plan.is_file() or "Что снять" not in plan.read_text("utf-8"):
                    raise RuntimeError("Shooting plan missing")
            print(f"REAL GEMMA SCENARIO PASS {index}/{args.topics}: "
                  f"{attempts} attempts, {report.seconds:.1f} sec; "
                  "structural checks only, facts and artistic quality unverified.",
                  flush=True)
        except Exception as exc:
            failures += 1
            print(f"REAL GEMMA SCENARIO FAIL {index}/{args.topics}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    print(f"REAL GEMMA SCORE: {args.topics - failures}/{args.topics}",
          flush=True)
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
