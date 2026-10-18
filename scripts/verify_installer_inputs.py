"""Refuse incomplete Windows installer payloads. Not an inference test."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]/'dist'/'JarvisNova'
REQUIRED=[
 'JarvisNova.exe',
 'assets/models/base.pt',
 'assets/models/v5_ru.pt',
 'assets/ollama/ollama.exe',
 'assets/models/ollama/manifests/registry.ollama.ai/library/qwen3-vl/2b',
 'assets/models/vosk/am/final.mdl',
]
def audit(root=ROOT):
    issues=[f'MISSING {p}' for p in REQUIRED if not (root/p).is_file()]
    for name,min_bytes in [('assets/models/base.pt',30_000_000),('assets/models/v5_ru.pt',1_000_000),('assets/models/vosk/am/final.mdl',1_000_000)]:
        f=root/name
        if f.exists() and f.stat().st_size<min_bytes: issues.append(f'INVALID {name}')
    blobs=root/'assets/models/ollama/blobs'
    if not blobs.is_dir() or not any(f.is_file() and f.stat().st_size>100_000_000 for f in blobs.glob('sha256-*')):
        issues.append('MISSING real Vision weights in assets/models/ollama/blobs')
    return issues
if __name__=='__main__':
    errors=audit()
    for error in errors:print(error,file=sys.stderr)
    if errors:sys.exit(2)
    print('Offline files present; real inference must be tested independently.')
