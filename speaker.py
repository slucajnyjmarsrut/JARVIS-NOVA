# -*- coding: utf-8 -*-
"""Silero v5_ru offline when bundled, Windows TTS fallback."""
from pathlib import Path
import sys, threading

def assets():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"assets"/"models"

class Speaker:
    def __init__(self):
        self.model=None
        self.mode="windows"
        self.busy=False
        self.lock=threading.RLock()
        self._closing=threading.Event()

    def load(self):
        if self._closing.is_set():return "Озвучка остановлена"
        path=assets()/"v5_ru.pt"
        if not path.is_file(): return "Silero отсутствует, используется системный голос."
        try:
            import torch
            self.model=torch.package.PackageImporter(str(path)).load_pickle("tts_models","model")
            self.model.to("cpu")
            if self._closing.is_set():return "Озвучка остановлена"
            self.mode="silero"
            return "Silero готов."
        except Exception as e:
            self.mode="windows"
            return "Silero не загрузился: "+str(e)[:100]

    def say(self,text):
        if self._closing.is_set():return
        # Serial: don't multiply multiple threads and leak audio into wake detection.
        with self.lock:
            if self._closing.is_set():return
            self.busy=True
            try:
                if self.mode=="silero" and self.model is not None:
                    import sounddevice as sd
                    audio=self.model.apply_tts(text=text,speaker="xenia",sample_rate=48000)
                    sd.play(audio.cpu().numpy(),48000)
                    sd.wait()
                elif sys.platform=="win32":
                    import pyttsx3
                    engine=pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
            except Exception:
                pass
            finally:
                self.busy=False

    def shutdown(self):
        """No more TTS after X. Interrupt active PortAudio playback if present."""
        self._closing.set()
        import sys
        if "sounddevice" in sys.modules:
            try:sys.modules["sounddevice"].stop()
            except Exception:pass
