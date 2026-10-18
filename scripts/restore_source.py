"""Restore only known safe text-source paths from the checked-in source bundle."""
from pathlib import Path
import base64, io, lzma, tarfile

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'source'/'jarvis-python-src.tar.xz.base64'
PERMITTED={'.py','.txt','.md','.yml','.yaml','.cmd','.iss','.spec','.ps1'}
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
    # The transfer-text bundle intentionally excludes binary icon assets.
    # Generate a minimal valid offline ICO; Windows needs no external download.
    import struct, zlib
    assets=ROOT/'assets'
    assets.mkdir(parents=True,exist_ok=True)
    icon=assets/'jarvis.ico'
    if not icon.exists():
        width=32
        raw=b''.join(b'\\x00'+b'\\x18\\x28\\x44'*width for _ in range(width))
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png=(b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,width,8,2,0,0,0))+
             chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
        with icon.open('wb') as stream:
            stream.write(struct.pack('<HHH',0,1,1))
            stream.write(struct.pack('<BBBBHHII',width,width,0,0,1,32,len(png),22))
            stream.write(png)
    print(f'Restored {len(members)} source files (without model weights)')
if __name__=='__main__':main()
