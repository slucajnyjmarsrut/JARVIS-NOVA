# -*- coding: utf-8 -*-
"""Vosk continuous wake word and optional Whisper fallback, no saved recordings."""
from __future__ import annotations
import json, queue, threading, time, re
from typing import Callable

from agent_core import WAKE, strip_wake
from speaker import assets


class Voice:
    def __init__(self,on_heard:Callable[[str],None],on_status:Callable[[str],None],speaking:Callable[[],bool],
                 on_vision_audio: Callable[[bytes, str], None] | None = None):
        self.on_heard=on_heard
        self.on_status=on_status
        self.speaking=speaking
        self.on_vision_audio=on_vision_audio
        self.running=False
        self.stopping=False
        self.thread=None
        self.until=0
        self.last_text=""
        self.last_at=0
        self.pending=""
        self.whisper_model=None
        self.whisper_busy=False
        self.whisper_last_at=0.0
        self.lock=threading.RLock()

    def activate(self):
        with self.lock: self.until=time.monotonic()+8
        self.on_status("Слушаю команду…")

    def accept_text(self,text:str):
        if self.stopping or self.speaking(): return
        text=text.strip()
        if not text:return
        now=time.monotonic()
        with self.lock:
            # Suppress duplicate engine events, not deliberate repeated commands after 900 ms.
            if text==self.last_text and now-self.last_at<0.9:return
            self.last_text=text;self.last_at=now
            if WAKE.match(text):
                self.until=now+8
                command=strip_wake(text)
            elif now<self.until:
                command=text
            else:
                return
            if self.pending:
                command=self.pending+" "+command
                self.pending=""
            if command.strip().casefold() in {"открой","запусти","включи"}:
                self.pending=command.strip()
                self.until=now+6
                self.on_status("Что открыть?")
                return
            if command.strip():
                self.until=0
        if command.strip(): self.on_heard(command.strip())
        else: self.on_status("Слушаю команду…")

    def start(self):
        if self.running:return
        self.stopping=False
        self.running=True
        self.thread=threading.Thread(target=self._run,daemon=True,name="vosk-mic")
        self.thread.start()

    def stop(self):
        self.stopping=True
        self.running=False
        if self.thread and self.thread.is_alive(): self.thread.join(timeout=3)

    def _try_whisper(self, pcm: bytes, did_wake: bool, vosk_text: str = "", force: bool = False):
        """Whisper is authoritative for completed speech; Vosk supplies wake detection.

        Vosk text is used ONLY if a real Whisper model is unavailable or fails.
        An explicit wake/manual activation bypasses cooldown, so a quiet command
        is not discarded after a recognition mistake. Audio stays in RAM.
        """
        now=time.monotonic()
        with self.lock:
            active = did_wake or force or now < self.until
            if self.stopping or self.whisper_busy or self.speaking() or len(pcm) < 16000:
                return
            if not active and now-self.whisper_last_at < 3.0:
                return
            path=assets()/"base.pt"
            if not path.is_file():
                if vosk_text:
                    self.accept_text(vosk_text)
                else:
                    self.on_status("Whisper отсутствует: проверь встроенные модели")
                return
            self.whisper_busy=True
            self.whisper_last_at=now
        def work():
            try:
                self.on_status("Whisper распознаёт фразу…")
                if self.whisper_model is None:
                    import whisper
                    self.whisper_model=whisper.load_model(str(path),device="cpu")
                import numpy as np
                samples=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768.0
                result=self.whisper_model.transcribe(
                    samples,language="ru",fp16=False,condition_on_previous_text=False,
                    temperature=0,beam_size=3)
                text=str(result.get("text","") or "").strip()
                # Hallucinations during silence are a real Whisper failure mode.
                if text:
                    if active:
                        with self.lock:
                            self.until=max(self.until,time.monotonic()+5)
                    self.accept_text(text)
                elif active:
                    self.on_status("Не расслышал. Попробуй повторить немного громче.")
            except Exception as exc:
                self.on_status("Whisper: "+str(exc)[:90])
                if vosk_text and not self.stopping:
                    if did_wake or force:
                        with self.lock: self.until=time.monotonic()+5
                    self.accept_text(vosk_text)
            finally:
                with self.lock: self.whisper_busy=False
        threading.Thread(target=work,daemon=True,name="whisper-command").start()

    @staticmethod
    def vision_source(text: str) -> str | None:
        """Local-only intent classification; never infer permissions from audio."""
        norm=text.casefold().replace('ё','е')
        if not re.search(r'что (?:ты )?видишь|посмотри (?:на экран|в камеру)|опиши (?:экран|камеру)|что на экране|что перед камерой', norm):
            return None
        return 'camera' if re.search(r'камер|перед тобой', norm) else 'screen'

    def _run(self):
        try:
            import numpy as np, sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model_path=assets()/"vosk"
            if not (model_path/"am"/"final.mdl").is_file():
                raise FileNotFoundError("Модель Vosk не встроена")
            model=Model(str(model_path))
            recognizer=KaldiRecognizer(model,16000)
            recognizer.SetWords(True)
            audio_queue=queue.Queue(maxsize=60)
            segment=bytearray()
            silent=0
            max_segment=16000*2*11
            vosk_parts=[]
            # Lower gate for quiet speech; Whisper filters recognized text.
            speech_threshold=55
            segment_vosk_wake=False
            vision_pending=None
            was_speaking=False
            self.on_status("Vosk готов · жду «Джарвис»")
            def callback(indata,frames,tm,status):
                try:audio_queue.put_nowait(bytes(indata))
                except queue.Full:
                    try:audio_queue.get_nowait()
                    except queue.Empty:pass
                    try:audio_queue.put_nowait(bytes(indata))
                    except queue.Full:pass
            # Model initialization may finish after the application was closed.
            if not self.running:return
            # Try 16 kHz first; PortAudio can convert native Bluetooth/HFP rates.
            with sd.RawInputStream(samplerate=16000,blocksize=1600,channels=1,
                                   dtype="int16",callback=callback):
                while self.running:
                    try: packet=audio_queue.get(timeout=0.2)
                    except queue.Empty:continue
                    if self.speaking():
                        if not was_speaking:
                            segment.clear();silent=0;segment_vosk_wake=False;vision_pending=None
                            vosk_parts.clear()
                            recognizer=KaldiRecognizer(model,16000)
                        was_speaking=True
                        continue
                    was_speaking=False
                    data=np.frombuffer(packet,dtype="<i2")
                    rms=float(np.sqrt(np.mean(data.astype(np.float64)**2))) if data.size else 0
                    if rms>speech_threshold or segment:
                        segment.extend(packet)
                        silent=0 if rms>speech_threshold else silent+1
                        if len(segment)>max_segment:
                            # Avoid unbounded RAM on constant noise.
                            segment=segment[-max_segment:]
                    if recognizer.AcceptWaveform(packet):
                        result=json.loads(recognizer.Result())
                        text=result.get("text","").strip()
                        if text:
                            vosk_parts.append(text)
                            if WAKE.match(text):
                                segment_vosk_wake=True
                                # Wake word alone should open the command window,
                                # but Vosk's potentially wrong words are NEVER executed yet.
                                with self.lock: self.until=time.monotonic()+10
                                self.on_status("Слышу «Джарвис». Уточняю через Whisper…")
                            candidate=self.vision_source(text)
                            if candidate and self.on_vision_audio and (WAKE.match(text) or time.monotonic()<self.until):
                                vision_pending=candidate
                    if segment and (silent>=10 or len(segment)>=max_segment):
                        utterance=bytes(segment)
                        segment.clear();silent=0
                        text=json.loads(recognizer.FinalResult()).get("text","").strip()
                        combined=" ".join([*vosk_parts, text]).strip()
                        vosk_parts.clear()
                        recognizer=KaldiRecognizer(model,16000)
                        recognizer.SetWords(True)
                        has_wake=segment_vosk_wake or bool(WAKE.match(combined))
                        segment_vosk_wake=False
                        candidate=self.vision_source(combined)
                        if (candidate and self.on_vision_audio and
                                (has_wake or time.monotonic()<self.until)):
                            vision_pending=candidate
                        if vision_pending and self.on_vision_audio and not self.stopping:
                            self.on_vision_audio(utterance,vision_pending)
                            vision_pending=None
                            continue
                        # Never dispatch raw Vosk command text before the more
                        # accurate Whisper pass has had a chance to recognize it.
                        self._try_whisper(utterance,has_wake,combined)
        except Exception as exc:
            self.on_status("Ошибка микрофона: "+str(exc)[:180])
        finally:
            self.running=False
