# -*- coding: utf-8 -*-
"""Prepare a >2 GiB official Inno installer for GitHub Release multi-part assets.

This script DOES NOT upload, publish, merge or execute anything.
Run on a trusted release build machine only after approval.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

PART_BYTES = 1_500_000_000  # strictly below GitHub's 2 GiB / asset limit


def split_release(installer: Path, folder: Path, version: str, *,
                  part_bytes: int = PART_BYTES) -> tuple[Path, ...]:
    from auto_update import (GITHUB_ASSET_LIMIT, MAX_INSTALLER_BYTES,
                             MIN_INSTALLER_BYTES, version_tuple)
    version_tuple(version)
    if not 100_000 <= part_bytes < GITHUB_ASSET_LIMIT:
        raise ValueError("Размер части должен быть от 100 КБ до менее 2 ГиБ")
    installer=Path(installer)
    folder=Path(folder)
    if not installer.is_file() or installer.is_symlink():
        raise ValueError("Нужен локальный установщик EXE")
    size=installer.stat().st_size
    if not MIN_INSTALLER_BYTES <= size <= MAX_INSTALLER_BYTES:
        raise ValueError("Неподдерживаемый размер установщика")
    with installer.open("rb") as stream:
        if stream.read(2)!=b"MZ":
            raise ValueError("Не Windows EXE")
    if folder.exists():
        raise FileExistsError("Каталог для частей уже существует")
    folder.mkdir(parents=True,exist_ok=False)
    files=[]
    total=hashlib.sha256()
    read=0
    try:
        with installer.open("rb") as stream:
            index=0
            while read<size:
                index+=1
                if index>8:
                    raise ValueError("Требуется слишком много частей")
                name=f"JARVIS-NOVA-{version}-OFFLINE-SETUP.exe.part{index:02d}"
                part=folder/name
                chunk_written=0
                with part.open("xb") as out:
                    files.append(part)
                    while chunk_written<part_bytes and read<size:
                        block=stream.read(min(1024*1024,part_bytes-chunk_written,size-read))
                        if not block:
                            raise OSError("Неожиданный конец EXE")
                        out.write(block)
                        total.update(block)
                        read+=len(block)
                        chunk_written+=len(block)
        if len(files)<2:
            raise ValueError("Деление не требуется: отдельный EXE меньше лимита")
        body=folder/"RELEASE_BODY_SHA256.txt"
        with body.open("x",encoding="utf-8") as file:
            file.write(
                f"JARVIS-NOVA-INSTALLER-SHA256: {total.hexdigest()}\n"
                f"JARVIS-NOVA-INSTALLER-SIZE: {size}\n"
                "Все .partNN должны быть прикреплены к одному стабильному GitHub Release.\n")
        files.append(body)
        return tuple(files)
    except Exception:
        for item in reversed(files):
            item.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--installer",type=Path,required=True)
    p.add_argument("--version",required=True)
    p.add_argument("--folder",type=Path,required=True)
    p.add_argument("--part-bytes",type=int,default=PART_BYTES)
    args=p.parse_args(argv)
    outputs=split_release(args.installer,args.folder,args.version,
                          part_bytes=args.part_bytes)
    for item in outputs:
        print(item)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
