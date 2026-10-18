#!/usr/bin/env python3
"""Produce exact onedir size breakdown before Inno Setup compression.

Read-only inspection; never modify model weights, source files or user data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def category(path: Path) -> str:
    p = path.as_posix().lower()
    if p.startswith("_internal/assets/models/ollama/blobs/"):
        return "Vision model weights (Ollama blobs)"
    if p.startswith("_internal/assets/models/ollama/"):
        return "Vision manifests/metadata"
    if p in ("_internal/assets/models/base.pt", "_internal/assets/models/v5_ru.pt"):
        return "Whisper and Silero weights"
    if p.startswith("_internal/assets/models/vosk/"):
        return "Vosk speech activation model"
    if p.startswith("_internal/assets/ollama/"):
        return "Ollama inference runtime"
    if p.startswith("_internal/assets/bin/"):
        return "FFmpeg video editing"
    if p.startswith("_internal/torch/") or p.startswith("_internal/torch.libs/"):
        return "PyTorch runtime"
    if p.startswith("_internal/cv2/"):
        return "OpenCV runtime"
    if p.startswith("_internal/scipy/") or p.startswith("_internal/scipy.libs/"):
        return "SciPy runtime"
    if p == "jarvisnova.exe":
        return "Windows application EXE"
    return "Other Python/app runtime"


def summarize(root: Path, top_n: int = 20) -> dict:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError("Built onedir distribution not found: " + str(root))
    totals: dict[str, int] = {}
    largest: list[tuple[int, str]] = []
    size_total = 0
    count = 0
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(root)
        size = item.stat().st_size
        label = category(relative)
        totals[label] = totals.get(label, 0) + size
        size_total += size
        count += 1
        largest.append((size, relative.as_posix()))
    if count == 0:
        raise ValueError("Empty PyInstaller distribution")
    largest.sort(key=lambda x: x[0], reverse=True)
    return {
        "total_bytes": size_total,
        "files": count,
        "categories": [
            {"name": k, "bytes": v, "percent": round(v * 100 / size_total, 2)}
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
        ],
        "largest_files": [{"bytes": x, "path": p} for x, p in largest[:top_n]]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("dist/JarvisNova"))
    parser.add_argument("--output", type=Path, default=Path("dist/size-report.json"))
    parser.add_argument("--baseline-setup-bytes", type=int, default=2249565502)
    args = parser.parse_args()
    report = summarize(args.root)
    report["previous_setup_bytes"] = args.baseline_setup_bytes
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PyInstaller onedir total: {:,} bytes across {:,} files".format(
        report["total_bytes"], report["files"]))
    print("Earlier Inno installer baseline: {:,} bytes".format(args.baseline_setup_bytes))
    for group in report["categories"]:
        print(" {:6.2f}% | {:>14,} bytes | {}".format(
            group["percent"], group["bytes"], group["name"]))
    print("Top files (uncompressed):")
    for f in report["largest_files"][:15]:
        print(" {:>14,} | {}".format(f["bytes"], f["path"]))
    print("Report saved to " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
