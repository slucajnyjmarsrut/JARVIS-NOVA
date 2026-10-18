# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file Windows GUI bundle with models embedded."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

project=Path(SPECPATH)
assets=project/"assets"
required=[assets/"models"/"vosk"/"am"/"final.mdl",
          assets/"models"/"base.pt",assets/"models"/"v5_ru.pt"]
for item in required:
    if not item.is_file():
        raise RuntimeError("Missing bundled model: %s. Run build_models.py first" % item)
binaries=[]
datas=[(str(assets),"assets")]
hiddenimports=["win32com.client","win32com.server","pythoncom","pywintypes",
               "tiktoken_ext.openai_public","PIL.ImageGrab","sounddevice",
               "pygetwindow","pyautogui","pyttsx3"]
for library in ("vosk","whisper","torch","sounddevice","_sounddevice_data","pyttsx3"):
    try:
        d,b,h=collect_all(library)
    except Exception as exc:
        if library=="_sounddevice_data":
            continue  # some sounddevice wheels bundle PortAudio differently
        raise
    datas+=d
    binaries+=b
    hiddenimports+=h
a=Analysis(
    ["bootstrap.py"], pathex=[str(project)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=["torch.testing","torch._dynamo.test_case",
        "pytest","matplotlib","IPython","jupyter","notebook","tensorflow"],
    noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(
    pyz,a.scripts,a.binaries,a.datas,[],
    name="JARVIS-NOVA-PYAGENT",debug=False,bootloader_ignore_signals=False,
    strip=False,upx=False,console=False,
    icon=str(assets/"jarvis.ico"),disable_windowed_traceback=False)
