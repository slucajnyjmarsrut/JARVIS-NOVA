# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir application; Inno Setup wraps it as ONE install EXE.

Using onedir prevents PyInstaller decompressing 3+ GiB of GGUF every startup.
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project=Path(SPECPATH)
assets=project/'assets'
critical=[assets/'models'/'vosk'/'am'/'final.mdl',
          assets/'models'/'base.pt',assets/'models'/'v5_ru.pt',
          assets/'ollama'/'ollama.exe',
          assets/'models'/'ollama'/'manifests'/'registry.ollama.ai'/'library'/'qwen3-vl'/'2b-instruct']
for item in critical:
    if not item.is_file():
        raise RuntimeError(f'Cannot build incomplete offline release. Missing: {item}')

# Exclude developer-only PyTorch C++ headers from frozen runtime.
# They are bundled by broad collect_all("torch") but neither Whisper nor
# Silero needs them for inference. Keep every DLL and checkpoint.
def development_header(entry):
    # PyInstaller datas: (source, destination); analysis TOC: (dest, source, type).
    destination = str(entry[1] if len(entry) == 2 else entry[0]).replace('\\', '/').lower()
    return destination == 'torch/include' or destination.startswith('torch/include/')

binaries=[]
datas=[(str(assets),'assets')]
hiddenimports=['win32com.client','pythoncom','pywintypes','PIL.ImageGrab',
               'sounddevice','_sounddevice_data','tiktoken_ext.openai_public',
               'pyautogui','pygetwindow','cv2']
for library in ('vosk','whisper','torch','sounddevice','_sounddevice_data',
                'PIL','cv2','scipy','pyttsx3'):
    try:
        d,b,h=collect_all(library)
    except Exception:
        if library=='_sounddevice_data':continue
        raise
    # PyTorch wheels contain large static import libraries (.lib) and debug
    # artifacts that are never loaded by Windows Python inference. Including
    # them needlessly pushes Inno Setup past its ~4.2 GB one-file limit.
    # Keep all runtime DLLs and Python modules; fail closed on E2E testing.
    def runtime_files(entries):
        ignored=('.lib', '.pdb', '.exp', '.ilk', '.pyi', '.pyc')
        return [item for item in entries
                if not str(item[0]).lower().endswith(ignored)]
    datas += [item for item in runtime_files(d) if not development_header(item)]
    binaries += runtime_files(b)
    hiddenimports += h

analysis=Analysis(['bootstrap.py'],pathex=[str(project)],binaries=binaries,
    datas=datas,hiddenimports=hiddenimports,hookspath=[],hooksconfig={},
    runtime_hooks=[],excludes=['torch.testing','pytest','matplotlib','IPython',
    'tensorflow','jupyter','notebook'],noarchive=False)
# PyInstaller torch hooks may append headers after collect_all processing.
# Explicitly remove them from the final data TOC, after all hooks have run.
analysis.datas = [entry for entry in analysis.datas if not development_header(entry)]
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,
        name='JarvisNova',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,icon=str(assets/'jarvis.ico'))
coll=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='JarvisNova')
