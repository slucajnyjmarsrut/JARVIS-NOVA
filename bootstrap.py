# -*- coding: utf-8 -*-
"""Single entry point: protect PyInstaller child processes and support a headless smoke test."""
import multiprocessing
import os
import sys

# PyInstaller --windowed starts with stdout/stderr=None on Windows.
# Libraries (including real-model inference) may print diagnostics. A None
# stream would otherwise raise AttributeError and abort the whole application.
# Do not persist user utterances or camera descriptions as logs.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

multiprocessing.freeze_support()  # BEFORE importing tkinter

def _assets_root():
    from pathlib import Path
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent)) / "assets"

def smoke_test():
    """Validate the shipped TEXT/VISION runtime; no voice models required."""
    from bundled_vision_runtime import validate_offline_model_store
    import importlib.util
    root=_assets_root()
    if not (root / 'ollama' / 'ollama.exe').is_file():
        print('Missing bundled portable Ollama runtime',flush=True)
        return 4
    for tool in ('ffmpeg.exe','ffprobe.exe'):
        if not (root / 'bin' / tool).is_file():
            print('Missing bundled video tool:',tool,flush=True)
            return 6
    from model_storage import installed_edition, active_model_store
    edition=installed_edition(root)
    if edition=='offline':
        try:
            validate_offline_model_store(root)
        except Exception as exc:
            print('Missing or incomplete Qwen Vision weights:',exc,flush=True)
            return 5
    else:
        if (root/'models'/'ollama'/'blobs').exists():
            print('Lite installer must not contain embedded Qwen weights',flush=True)
            return 5
    for module in ('PIL','pyautogui'):
        if importlib.util.find_spec(module) is None:
            print('Missing text/visual dependency:',module,flush=True)
            return 3
    # A text-only release must not carry legacy speech assets.
    for rel in ('models/base.pt','models/small.pt','models/v5_ru.pt',
                'models/vosk/am/final.mdl'):
        if (root/rel).exists():
            print('Unexpected voice checkpoint in text-only EXE:',rel,flush=True)
            return 7
    print(('LITE package verified: portable Ollama + FFmpeg; '
           'Qwen is consent-gated and downloaded separately' if edition=='lite'
           else 'TEXT-ONLY full offline package: Qwen and FFmpeg present'),flush=True)
    return 0

def _acquire_windows_single_instance(name="JarvisNovaRuntime"):
    """Named mutex: installer refuses upgrading a running JARVIS."""
    import os
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateMutexW(None, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot create JARVIS mutex")
    if ctypes.get_last_error() == 183:
        api.CloseHandle(handle)
        return False
    return api, handle


def video_self_test():
    """Test bundled editing tools inside the frozen GUI EXE, offline and headless."""
    import json
    import subprocess
    import tempfile
    from pathlib import Path

    # Real imports must work from the PyInstaller bundle, not only on the build host.
    from viral_studio import ffmpeg_tools
    import viral_studio_ui
    import channel_audience
    import creator_experts
    import video_forecast
    import work_modes
    import game_catalog
    from main import Jarvis
    if not callable(Jarvis.open_viral_studio):
        raise RuntimeError("Video Studio GUI entry point unavailable")
    ffmpeg, ffprobe = ffmpeg_tools()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryDirectory(prefix="jarvis-video-check-") as tmp:
        out = Path(tmp) / "render.mp4"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=360x640:r=12:d=1",
                        "-t", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-y", str(out)], check=True, capture_output=True,
                       timeout=60, creationflags=flags)
        if not out.is_file() or out.stat().st_size < 1000:
            raise RuntimeError("Bundled FFmpeg failed to encode MP4")
        info = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", str(out)], check=True, capture_output=True,
            timeout=20, creationflags=flags)
        streams = json.loads(info.stdout).get("streams", [])
        if not any(s.get("codec_type") == "video" for s in streams):
            raise RuntimeError("Bundled FFprobe cannot read the generated MP4")
    print("Video Studio headless package test OK; real FFmpeg generated MP4", flush=True)
    return 0


def conversational_self_test():
    """Run the REAL bundled Qwen text path, from the frozen application."""
    from local_chat import LocalChat
    from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
    runtime=BundledVisionRuntime(BundledRuntimeConfig(root=_assets_root()))
    session=LocalChat(runtime)
    try:
        answer=session.ask("Привет, кто ты? Ответь одним кратким русским предложением.")
        if not answer or len(answer)>1600 or not any("а"<=char.casefold()<="я" for char in answer):
            raise RuntimeError("Local chat model did not produce a non-empty Russian reply")
        print("REAL bundled text-chat model answered successfully (no mocks, no cloud)",flush=True)
        return 0
    finally:
        session.close()
        runtime.stop()


def main():
    import sys
    if "--supervisor-daemon" in sys.argv:
        # Separate named mutex; the UI's "JarvisNovaRuntime" guard must
        # not block this deliberately headless per-user background service.
        if sys.argv != [sys.argv[0], "--supervisor-daemon"]:
            return 11
        guard = _acquire_windows_single_instance("JarvisNovaSupervisorDaemon")
        if guard is False:
            return 0
        try:
            from night_supervisor_service import run_forever
            run_forever()
            return 0
        finally:
            if guard is not None:
                api, handle = guard
                api.CloseHandle(handle)
    if "--self-test" in sys.argv:
        return smoke_test()
    if "--chat-self-test" in sys.argv:
        return conversational_self_test()
    if "--video-self-test" in sys.argv:
        return video_self_test()
    if "--real-e2e" in sys.argv:
        # Historical flag retained for installer compatibility, now verifies
        # real Qwen text + image processing, with NO Whisper/Silero.
        from scripts.verify_text_vision_e2e import main as text_vision_test
        return text_vision_test()
    guard = _acquire_windows_single_instance()
    if guard is False:
        return 10  # No second microphone/UI/vision server.
    try:
        from text_only_main import TextJarvis
        TextJarvis().mainloop()
        return 0
    finally:
        if guard is not None:
            api, handle = guard
            api.CloseHandle(handle)

if __name__=="__main__":
    raise SystemExit(main())
