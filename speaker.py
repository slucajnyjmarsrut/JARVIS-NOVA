# -*- coding: utf-8 -*-
"""Silero v5_ru offline when bundled, Windows TTS fallback."""
from pathlib import Path
import sys, threading
from whisper_mode import normalize_style
from speech_output import split_for_tts

def assets():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"assets"/"models"

class Speaker:
    def __init__(self):
        self.model=None
        self.mode="windows"
        self.busy=False
        self.lock=threading.RLock()
        self._closing=threading.Event()
        self.last_error=""

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

    @staticmethod
    def clean_playback(audio, style="normal", sample_rate=48000):
        """Soften whispers, prevent clipping, and ramp chunk edges to avoid clicks."""
        import numpy as np
        result=Speaker.soften_audio(audio,style).copy()
        if not result.size:
            raise ValueError("Пустой аудиофрагмент Silero")
        # Do not pass NaNs / infinities to the system audio driver.
        result=np.nan_to_num(result,nan=0.0,posinf=0.0,neginf=0.0)
        result=np.clip(result,-.98,.98)
        # Six milliseconds fade at most, never longer than 1/4 of a chunk.
        fade=min(round(.006*sample_rate),result.size//4)
        if fade>=2:
            ramp=np.linspace(0.0,1.0,fade,endpoint=True,dtype=np.float32)
            result[:fade]*=ramp
            result[-fade:]*=ramp[::-1]
        return result

    def say(self,text,style="normal"):
        if self._closing.is_set():
            return False
        chunks=split_for_tts(text)
        if not chunks:
            return False
        # The entire response holds one lock and busy state, so Vosk ignores
        # Silero output even between generated sentences.
        with self.lock:
            if self._closing.is_set():
                return False
            self.busy=True
            self.last_error=""
            try:
                if self.mode=="silero" and self.model is not None:
                    import sounddevice as sd
                    for phrase in chunks:
                        if self._closing.is_set():
                            return False
                        audio=self.model.apply_tts(
                            text=phrase,speaker="xenia",sample_rate=48000)
                        sd.play(self.clean_playback(audio.cpu().numpy(),style),48000)
                        sd.wait()
                    return True
                elif sys.platform=="win32":
                    import pyttsx3
                    engine=pyttsx3.init()
                    try:
                        if normalize_style(style)=="whisper":
                            engine.setProperty("volume",.25)
                            engine.setProperty("rate",max(90,int(engine.getProperty("rate") or 180)-12))
                        else:
                            engine.setProperty("volume",1.0)
                        for phrase in chunks:
                            if self._closing.is_set():
                                return False
                            engine.say(phrase)
                        engine.runAndWait()
                    finally:
                        engine.stop()
                    return True
                else:
                    self.last_error="В этой системе нет доступного TTS-движка"
                    return False
            except Exception as exc:
                self.last_error=f"{type(exc).__name__}: {str(exc)[:125]}"
                return False
            finally:
                self.busy=False

    def shutdown(self):
        """No more TTS after X. Interrupt active PortAudio playback if present."""
        self._closing.set()
        import sys
        if "sounddevice" in sys.modules:
            try:sys.modules["sounddevice"].stop()
            except Exception:pass
