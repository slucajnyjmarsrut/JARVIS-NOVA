"""Restore only known safe text-source paths from the checked-in source bundle."""
from pathlib import Path
import base64, io, lzma, tarfile

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'source'/'jarvis-python-src.tar.xz.base64'
PERMITTED={'.py','.txt','.md','.yml','.yaml','.cmd','.iss','.spec'}
def main():
    payload=base64.b64decode(''.join(SOURCE.read_text(encoding='ascii').split()),validate=True)
    plain=lzma.decompress(payload)
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as archive:
        members=archive.getmembers()
        if len(members)>100 or sum(m.size for m in members)>2_000_000:
            raise RuntimeError('Untrusted source bundle size')
        for member in members:
            name=member.name.replace('\\','/')
            path=Path(name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts or path.suffix.lower() not in PERMITTED or member.size>500_000:
                raise RuntimeError('Unexpected source bundle entry: '+name)
            out=ROOT/path
            out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists():
                raise RuntimeError('Refuse to overwrite checked-in file: '+name)
            with archive.extractfile(member) as inp, out.open('wb') as dst:
                dst.write(inp.read())
    print(f'Restored {len(members)} source files (without model weights)')
if __name__=='__main__':main()
