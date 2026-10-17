"""Build-machine distributable bill of materials. Does NOT replace real E2E."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys


def file_hash(path: Path) -> str:
    sha=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            sha.update(block)
    return sha.hexdigest()


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--root',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    root=Path(args.root).resolve()
    if not root.is_dir():raise RuntimeError(f'Directory absent: {root}')
    contents=[]
    for f in sorted(root.rglob('*')):
        if f.is_file():
            contents.append({'path':f.relative_to(root).as_posix(),
                             'size_bytes':f.stat().st_size,'sha256':file_hash(f)})
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'verified_files':contents,
               'note':'This file inventory is not a hardware test or model quality result'},
                ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Wrote {len(contents)} hashed files to {out}')
    return 0


if __name__=='__main__':
    sys.exit(main())
