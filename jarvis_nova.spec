# -*- mode: python ; coding: utf-8 -*-
"""Text-only Windows onedir, with Qwen Vision and FFmpeg but no speech assets."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project=Path(SPECPATH)
assets=project/'assets'
critical=[
    assets/'ollama'/'ollama.exe',
    assets/'models'/'ollama'/'manifests'/'registry.ollama.ai'/'library'/'qwen3-vl'/'2b-instruct',
    assets/'bin'/'ffmpeg.exe',
    assets/'bin'/'ffprobe.exe',
]
for item in critical:
    if not item.is_file():
        raise RuntimeError(f'Cannot bundle text-only JARVIS; missing: {item}')
# Never ship ASR/TTS checkpoints even if the CI runner has legacy test models.
# Explicitly include ONLY Ollama's audited model store, not assets/models.
datas=[]
for path in assets.iterdir():
    if path.name=='models':
        datas.append((str(path/'ollama'), 'assets/models/ollama'))
    else:
        datas.append((str(path), 'assets'))
binaries=[]
hiddenimports=[
    'win32com.client','pythoncom','pywintypes','PIL.ImageGrab',
    'pyautogui','pygetwindow','text_only_main','text_only_ui',
    'text_only_overlay','nova_command_palette','studio_theme','quick_video_brief',
    'freellm_client','pro_montage','filmcraft_bridge',
    'filmcraft_installer','code_gui','code_agent','code_autopilot',
    'code_project_engine','code_languages','code_checks',
    'roblox_world_builder','roblox_asset_pipeline','code_workspace',
    'code_edits','coding_intent','scripts.verify_text_vision_e2e',
]
# PIL is needed for screenshots, thumbnails and generated installer art.
d,b,h=collect_all('PIL')
datas+=d
binaries+=b
hiddenimports+=h
# These modules remain in the SOURCE repository only for historical tests.
# No ASR/TTS, PyTorch or microphone runtime is allowed inside the EXE.
legacy_voice=[
    'torch','torchaudio','torchvision','whisper','vosk','sounddevice',
    '_sounddevice_data','pyttsx3','speech_capture','speech_output',
    'speaker','voice_engine','microphone','audio_io','silero_engine',
    'whisper_engine','whisper_mode','trimodal_service','trimodal_pipeline',
    'offline_e2e_test','asr_quality','build_models','verify_models',
    'scipy','numba','llvmlite','tiktoken',
]
analysis=Analysis(['bootstrap.py'],pathex=[str(project)],binaries=binaries,
    datas=datas,hiddenimports=hiddenimports,hookspath=[],hooksconfig={},
    runtime_hooks=[],excludes=legacy_voice+[
        'cv2','pytest','matplotlib','IPython','tensorflow',
        'jupyter','notebook',
    ],noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,
        name='JarvisNova',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,icon=str(assets/'jarvis.ico'))
coll=COLLECT(exe,analysis.binaries,analysis.datas,
             strip=False,upx=False,name='JarvisNova')
