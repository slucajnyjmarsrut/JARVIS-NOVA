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
          assets/'models'/'ollama'/'manifests'/'registry.ollama.ai'/'library'/'qwen3-vl'/'2b']
for item in critical:
    if not item.is_file():
        raise RuntimeError(f'Cannot build incomplete offline release. Missing: {item}')

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
    datas+=d; binaries+=b; hiddenimports+=h

analysis=Analysis(['bootstrap.py'],pathex=[str(project)],binaries=binaries,
    datas=datas,hiddenimports=hiddenimports,hookspath=[],hooksconfig={},
    runtime_hooks=[],excludes=['torch.testing','pytest','matplotlib','IPython',
    'tensorflow','jupyter','notebook'],noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,
        name='JarvisNova',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,icon=str(assets/'jarvis.ico'))
coll=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='JarvisNova')
