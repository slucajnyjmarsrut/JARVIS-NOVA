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

multiprocessing.freeze_support()  # BEFORE importing torch/whisper/tkinter

def smoke_test():
    # Return an error code to GitHub Actions without opening UI/microphone.
    from speaker import assets
    from bundled_vision_runtime import validate_offline_model_store
    import importlib.util
    root=assets()
    files={"Vosk":root/"vosk"/"am"/"final.mdl",
           "Whisper":root/"base.pt",
           "Silero":root/"v5_ru.pt"}
    for label,path in files.items():
        if not path.is_file() or path.stat().st_size<1024:
            print("Missing embedded",label,path,flush=True)
            return 2
    if not (root.parent / 'ollama' / 'ollama.exe').is_file():
        print('Missing bundled portable Ollama runtime',flush=True)
        return 4
    try:
        validate_offline_model_store(root.parent)
    except Exception as exc:
        print('Missing or incomplete Vision weights:',exc,flush=True)
        return 5
    for module in ["vosk","whisper","torch","sounddevice","pyautogui","cv2","scipy"]:
        if importlib.util.find_spec(module) is None:
            print("Missing bundled Python library",module,flush=True)
            return 3
    print("JARVIS bundled dependencies present; this is NOT a real inference test",flush=True)
    return 0

def _acquire_windows_single_instance():
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
    handle = api.CreateMutexW(None, False, "JarvisNovaRuntime")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot create JARVIS mutex")
    if ctypes.get_last_error() == 183:
        api.CloseHandle(handle)
        return False
    return api, handle


def main():
    import sys
    if "--self-test" in sys.argv:
        return smoke_test()
    if "--real-e2e" in sys.argv:
        from offline_e2e_test import main as real_test
        return real_test()
    guard = _acquire_windows_single_instance()
    if guard is False:
        return 10  # No second microphone/UI/vision server.
    try:
        from main import Jarvis
        Jarvis().mainloop()
        return 0
    finally:
        if guard is not None:
            api, handle = guard
            api.CloseHandle(handle)

if __name__=="__main__":
    raise SystemExit(main())
