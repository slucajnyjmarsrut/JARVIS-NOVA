# -*- coding: utf-8 -*-
"""Report text-only Windows bundle size and reject old speech files."""
from pathlib import Path
import argparse
import json

FORBIDDEN=("vosk","whisper","silero","torch","torchaudio","sounddevice",
           "pyttsx3","_sounddevice_data","speech_capture","voice_engine")


def report(root: Path) -> dict:
    root=Path(root)
    if not (root/"JarvisNova.exe").is_file():
        raise RuntimeError("Missing text-only JarvisNova.exe")
    all_files=[p for p in root.rglob("*") if p.is_file()]
    offenders=[]
    # Check package parts by exact directory/file stem, not substrings of
    # unrelated legal media filenames or Qwen model identifiers.
    for path in all_files:
        relative=path.relative_to(root)
        parts=[x.casefold() for x in relative.parts]
        if any(x in FORBIDDEN for x in parts):
            offenders.append(str(relative))
        if len(parts)>=3 and parts[-3:] in (
                ["assets","models","base.pt"],
                ["assets","models","small.pt"],
                ["assets","models","v5_ru.pt"]):
            offenders.append(str(relative))
    if offenders:
        raise RuntimeError("Speech content was bundled: "+", ".join(offenders[:12]))
    sizes=sorted(((p.stat().st_size,str(p.relative_to(root)))
                  for p in all_files),reverse=True)
    return {"file_count":len(all_files),
            "uncompressed_bytes":sum(length for length,_ in sizes),
            "top_8_files":[{"file":p,"bytes":n} for n,p in sizes[:8]],
            "speech_artifacts_found":0}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--dir",type=Path,default=Path("dist/JarvisNova"))
    parser.add_argument("--out",type=Path,default=Path("dist/installer/TEXT_ONLY_SIZE_REPORT.json"))
    opt=parser.parse_args(argv)
    data=report(opt.dir)
    opt.out.parent.mkdir(parents=True,exist_ok=True)
    opt.out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("TEXT-ONLY onedir:",data["uncompressed_bytes"],"bytes (",
          round(data["uncompressed_bytes"]/1_000_000_000,2),"GB )")
    files=sorted((p for p in opt.dir.rglob("*") if p.is_file()),
                 key=lambda p:p.stat().st_size,reverse=True)
    print("LARGEST PACKAGED FILES:",flush=True)
    for path in files[:35]:
        print(f"  {path.stat().st_size / 1_000_000:7.2f} MB  {path.relative_to(opt.dir)}",flush=True)
    print("DIRECTORY TOTALS:",flush=True)
    directories={}
    for path in files:
        rel=path.relative_to(opt.dir)
        group=str(rel.parts[0]) if len(rel.parts)<2 else "/".join(rel.parts[:3])
        directories[group]=directories.get(group,0)+path.stat().st_size
    for group,length in sorted(directories.items(),key=lambda item:-item[1])[:20]:
        print(f"  {length/1_000_000:7.2f} MB  {group}",flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
