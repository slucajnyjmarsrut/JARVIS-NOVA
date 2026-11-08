"""Verify text-only Windows bundle, model integrity and absence of speech assets."""
from pathlib import Path
import argparse
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bundled_vision_runtime import validate_offline_model_store

def is_windows_64_executable(path):
    path=Path(path)
    if not path.is_file():
        return False
    with path.open('rb') as f:
        head=f.read(4096)
    if len(head)<128 or head[:2]!=b'MZ':
        return False
    pe_offset=struct.unpack_from('<I',head,0x3c)[0]
    if pe_offset+26>len(head) or head[pe_offset:pe_offset+4]!=b'PE\0\0':
        return False
    machine=struct.unpack_from('<H',head,pe_offset+4)[0]
    magic=struct.unpack_from('<H',head,pe_offset+24)[0]
    return machine==0x8664 and magic==0x20b

def verify(root):
    root=Path(root)
    app=root/'JarvisNova.exe'
    if not is_windows_64_executable(app):
        raise RuntimeError('Missing bundled Windows x64 app: '+str(app))
    assets=root/'_internal'/'assets'
    if not assets.is_dir():
        raise RuntimeError('Missing PyInstaller _internal/assets')
    models=assets/'models'
    for name in ('vosk','base.pt','small.pt','v5_ru.pt'):
        if (models/name).exists():
            raise RuntimeError('Text-only installer contains forbidden speech model: '+name)
    # PyInstaller's binary tree must not silently include old ML or audio
    # runtimes. These names are package names; FFmpeg audio codecs stay.
    internal=root/'_internal'
    for name in ('torch','torchaudio','torchvision','whisper','vosk',
                 'sounddevice','_sounddevice_data','pyttsx3','scipy'):
        if (internal/name).exists():
            raise RuntimeError('Forbidden voice library packaged: '+name)
    if not is_windows_64_executable(assets/'ollama'/'ollama.exe'):
        raise RuntimeError('Missing x64 portable Ollama')
    # Video Studio must work with no system FFmpeg/Python installation.
    for tool in ('ffmpeg.exe','ffprobe.exe'):
        bundled=assets/'bin'/tool
        if not is_windows_64_executable(bundled):
            raise RuntimeError('Missing offline Windows x64 video editing engine: '+tool)
    from model_storage import installed_edition
    edition=installed_edition(assets)
    if edition=='lite':
        if (assets/'models'/'ollama').exists():
            raise RuntimeError('LITE installer unexpectedly carries Qwen model weights')
    else:
        validate_offline_model_store(assets,verify_hashes=True)
    partial=list(root.rglob('*.partial'))
    if partial:
        raise RuntimeError('Incomplete model download included: '+str(partial[0]))
    print('VERIFIED:',edition,'x64 app, FFmpeg, portable Ollama, speech-free')
    if edition=='lite':
        print('Qwen is intentionally excluded; install only after explicit user consent')
    print('IMPORTANT: this file audit is NOT model inference or a live hardware test')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dir',default='dist/JarvisNova')
    args=parser.parse_args()
    try:
        verify(Path(args.dir))
        return 0
    except Exception as exc:
        print('PAYLOAD FAILED:',exc,file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
