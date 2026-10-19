# -*- coding: utf-8 -*-
"""Silero v5_ru offline when bundled, Windows TTS fallback."""
from pathlib import Path
import sys, threading
from whisper_mode import normalize_style

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

    @staticmethod
    def soften_audio(audio,style):
        """Quiet, softened playback; does not pretend Silero supports true whisper timbre."""
        import numpy as np
        result=np.asarray(audio,dtype=np.float32).reshape(-1)
        if normalize_style(style)!="whisper":
            return result
        # Gentle 3-tap smoothing and bounded gain. Never boost quiet inputs.
        padded=np.pad(result,(1,1),mode="edge")
        soft=(padded[:-2]*.25+padded[1:-1]*.5+padded[2:]*.25)*.24
        return np.clip(soft,-1.,1.).astype(np.float32)

    def say(self,text,style="normal"):
        if self._closing.is_set():return
        # Serial: don't multiply multiple threads and leak audio into wake detection.
        with self.lock:
            if self._closing.is_set():return
            self.busy=True
            try:
                if self.mode=="silero" and self.model is not None:
                    import sounddevice as sd
                    audio=self.model.apply_tts(text=text,speaker="xenia",sample_rate=48000)
                    sd.play(self.soften_audio(audio.cpu().numpy(),style),48000)
                    sd.wait()
                elif sys.platform=="win32":
                    import pyttsx3
                    engine=pyttsx3.init()
                    if normalize_style(style)=="whisper":
                        engine.setProperty("volume",.25)
                        engine.setProperty("rate",max(90,int(engine.getProperty("rate") or 180)-12))
                    else:
                        engine.setProperty("volume",1.0)
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
