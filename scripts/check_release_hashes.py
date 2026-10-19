"""Verify one published Windows installer against GitHub CI SHA256SUMS.

No network, Defender exclusions, smart-screen bypasses or signature spoofing.
Hash equality verifies integrity, not the publisher's identity.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path


def verify_release_hashes(folder: Path) -> tuple[str, str]:
    folder=Path(folder)
    sums=folder/"SHA256SUMS.txt"
    if not sums.is_file():
        raise ValueError("SHA256SUMS.txt is missing")
    lines=[line.strip() for line in sums.read_text(encoding="utf-8-sig").splitlines()
           if line.strip()]
    if len(lines)!=1:
        raise ValueError("Expected exactly ONE official installer hash line")
    data=lines[0].split(None,1)
    if len(data)!=2 or len(data[0])!=64 or any(c not in "0123456789abcdefABCDEF" for c in data[0]):
        raise ValueError("Invalid SHA256 digest")
    digest,filename=data
    filename=filename.lstrip("*")
    # Never follow path segments from downloaded checksum metadata.
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise ValueError("Unsafe installer filename")
    if not filename.lower().endswith(".exe"):
        raise ValueError("Expected EXE installer")
    installers=sorted(folder.glob("*.exe"))
    if len(installers)!=1 or installers[0].name!=filename:
        raise ValueError("Installer file mismatch")
    path=installers[0]
    hasher=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b""):
            hasher.update(block)
    actual=hasher.hexdigest()
    if actual.lower()!=digest.lower():
        raise ValueError("Installer SHA256 mismatch — file changed or corrupted")
    return filename,actual


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--folder",type=Path,default=Path("dist/installer"))
    args=parser.parse_args()
    try:
        name,digest=verify_release_hashes(args.folder)
    except (OSError,ValueError) as exc:
        parser.exit(1,"SECURITY CHECK FAILED: "+str(exc)+"\n")
    print("VERIFIED: "+name+" SHA256 "+digest)
    print("NOTE: SHA256 alone does not certify the publisher or establish SmartScreen reputation")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
