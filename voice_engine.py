# -*- coding: utf-8 -*-
"""Vosk continuous wake word and optional Whisper fallback, no saved recordings."""
from __future__ import annotations
import json, queue, threading, time, re
from collections import deque
from typing import Callable

from agent_core import WAKE, strip_wake
from speaker import assets


class Voice:
    def __init__(self,on_heard:Callable[[str],None],on_status:Callable[[str],None],speaking:Callable[[],bool],
                 on_vision_audio: Callable[[bytes, str], None] | None = None,
                 on_audio_level: Callable[[float], None] | None = None):
        self.on_heard=on_heard
        self.on_status=on_status
        self.speaking=speaking
        self.on_vision_audio=on_vision_audio
        self.on_audio_level=on_audio_level  # RMS fraction, never raw audio
        self.running=False
        self.stopping=False
        self.thread=None
        self.until=0
        self.last_text=""
        self.last_at=0
        self.pending=""
        self.whisper_model=None
        self.whisper_busy=False
        self.whisper_queue=deque(maxlen=2)  # keep short follow-up utterances in RAM
        self.whisper_last_at=0.0
        self.lock=threading.RLock()
        self._generation=0
        self.input_device=None

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
                self.until=now+12  # brief conversational follow-up window
        if command.strip(): self.on_heard(command.strip())
        else: self.on_status("Слушаю команду…")

    def start(self):
        with self.lock:
            if self.running:return
            self._generation+=1
            generation=self._generation
            self.stopping=False
            self.running=True
            self.until=0
            self.pending=""
            self.last_text=""
            self.last_at=0
            self.whisper_last_at=0.0
            self.whisper_busy=False
            self.whisper_queue.clear()
            self.thread=threading.Thread(
                target=self._run,args=(generation,),daemon=True,name="vosk-mic")
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stopping=True
            self.running=False
            self.until=0
            self.pending=""
            self.whisper_queue.clear()
            self._generation+=1
            worker=self.thread
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=3)

    def set_input_device(self, device):
        """Select a device index (or None for Windows default) while mic is stopped."""
        with self.lock:
            if self.running:raise RuntimeError("Выключи микрофон перед выбором устройства")
            if device is not None and (isinstance(device,bool) or
                    not isinstance(device,int) or device<0):
                raise ValueError("Неверный индекс микрофона")
            self.input_device=device

    def _try_whisper(self, pcm: bytes, did_wake: bool, fallback_text: str = "", force: bool = False):
        """Whisper is authoritative for completed speech; Vosk supplies wake detection.

        Vosk text is used ONLY if a real Whisper model is unavailable or fails.
        An explicit wake/manual activation bypasses cooldown, so a quiet command
        is not discarded after a recognition mistake. Audio stays in RAM.
        """
        now=time.monotonic()
        with self.lock:
            active = did_wake or force or now < self.until
            if self.stopping or self.speaking() or len(pcm)<16000:
                return
            if self.whisper_busy:
                # Never drop an explicitly awakened/manual follow-up just
                # because the previous Whisper inference is still running.
                # Bounded to two (max 11s each) and cleared on Stop/restart.
                if active:
                    if len(self.whisper_queue)>=self.whisper_queue.maxlen:
                        self.on_status("Whisper: очередь полна — повтори последнюю фразу.")
                    else:
                        self.whisper_queue.append((pcm,did_wake,fallback_text))
                        self.on_status(
                            f"Whisper: команда в очереди ({len(self.whisper_queue)}/2)")
                return
            if not active and now-self.whisper_last_at < 3.0:
                return
            path=assets()/"base.pt"
            if not path.is_file():
                if fallback_text:
                    self.accept_text(fallback_text)
                else:
                    self.on_status("Whisper отсутствует: проверь встроенные модели")
                return
            self.whisper_busy=True
            self.whisper_last_at=now
            generation=self._generation
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
                    temperature=0,beam_size=3,no_speech_threshold=0.55)
                text=str(result.get("text","") or "").strip()
                with self.lock:
                    if self.stopping or generation!=self._generation:
                        return  # Stale Whisper result after Stop/restart.
                # Only a Whisper-confirmed Vision phrase can use the original PCM;
                # a noisy Vosk guess must never trigger camera/screen access.
                if text:
                    # Authorized queued speech must not be silently discarded
                    # by accept_text() while Silero is speaking the previous
                    # response. Only a bounded wait, never interrupt playback.
                    if force and self.speaking():
                        deadline=time.monotonic()+12
                        while self.speaking() and time.monotonic()<deadline:
                            with self.lock:
                                if self.stopping or generation!=self._generation:
                                    return
                            time.sleep(.05)
                        if self.speaking():
                            self.on_status("JARVIS ещё говорит — повтори команду.")
                            return
                    with self.lock:
                        if self.stopping or generation!=self._generation:
                            return
                        if active:
                            self.until=max(self.until,time.monotonic()+5)
                    source=self.vision_source(text)
                    if source and self.on_vision_audio and (active or WAKE.match(text)):
                        self.on_vision_audio(pcm,source)
                    else:
                        self.accept_text(text)
                elif active:
                    self.on_status("Не расслышал. Попробуй повторить немного громче.")
            except Exception as exc:
                with self.lock:
                    valid=not self.stopping and generation==self._generation
                if valid:self.on_status("Whisper: "+str(exc)[:90])
                if fallback_text and valid:
                    if did_wake or force:
                        with self.lock: self.until=time.monotonic()+5
                    self.accept_text(fallback_text)
            finally:
                with self.lock:
                    valid=not self.stopping and generation==self._generation
                    if valid:
                        self.whisper_busy=False
                        queued=self.whisper_queue.popleft() if self.whisper_queue else None
                    else:
                        queued=None
                if queued is not None:
                    # It was authorized by an active wake/listening window at
                    # capture time; process it even if that window now expired.
                    self._try_whisper(queued[0],queued[1],
                                      fallback_text=queued[2],force=True)
        threading.Thread(target=work,daemon=True,name="whisper-command").start()

    @staticmethod
    def normalize_mic_packet(packet: bytes, source_rate: int) -> bytes:
        """Return 16 kHz PCM16. Resample native 44.1/48 kHz microphones in RAM.

        Many Bluetooth/headset drivers cannot open a 16 kHz PortAudio stream.
        Keep microphone callback cheap; conversion runs in the voice worker.
        """
        if not (8000 <= source_rate <= 192000):
            raise ValueError("Unsupported microphone sample rate")
        if source_rate==16000:return packet
        import numpy as np
        from audio_io import prepare_audio
        samples=np.frombuffer(packet,dtype="<i2")
        normalized=prepare_audio(samples,source_rate,target_rate=16000)
        return np.clip(normalized*32768,-32768,32767).astype("<i2").tobytes()

    @staticmethod
    def vision_source(text: str) -> str | None:
        """Local-only intent classification; never infer permissions from audio."""
        norm=text.casefold().replace('ё','е')
        if not re.search(r'что (?:ты )?видишь|посмотри (?:на экран|в камеру)|опиши (?:экран|камеру)|что на экране|что перед камерой', norm):
            return None
        return 'camera' if re.search(r'камер|перед тобой', norm) else 'screen'

    def _run(self, generation: int):
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
            pre_roll=deque(maxlen=4)  # 400 ms before speech onset, in RAM only.
            silent=0
            max_segment=16000*2*11
            vosk_parts=[]
            # Adaptive PCM16 noise floor: retains quiet speech while avoiding
            # a fixed threshold that fails between laptops/headsets.
            noise_floor=8.0
            segment_vosk_wake=False
            was_speaking=False
            last_level_report=0.0
            device_info=sd.query_devices(self.input_device,kind="input")
            native_rate=int(round(device_info["default_samplerate"]))
            if not 8000<=native_rate<=192000:
                raise ValueError("Микрофон сообщает неверную частоту дискретизации")
            self.on_status(
                f"Vosk готов · микрофон {native_rate} Гц → 16000 Гц · жду «Джарвис»")
            def callback(indata,frames,tm,status):
                try:audio_queue.put_nowait(bytes(indata))
                except queue.Full:
                    try:audio_queue.get_nowait()
                    except queue.Empty:pass
                    try:audio_queue.put_nowait(bytes(indata))
                    except queue.Full:pass
            # Model initialization may finish after the application was closed.
            if not self.running or generation!=self._generation:return
            # Try 16 kHz first; PortAudio can convert native Bluetooth/HFP rates.
            with sd.RawInputStream(samplerate=native_rate,
                                   blocksize=max(256,int(native_rate/10)),channels=1,
                                   dtype="int16",callback=callback,
                                   device=self.input_device):
                while self.running and generation==self._generation:
                    try: packet=audio_queue.get(timeout=0.2)
                    except queue.Empty:continue
                    if self.speaking():
                        if not was_speaking:
                            segment.clear();pre_roll.clear();silent=0;segment_vosk_wake=False
                            vosk_parts.clear()
                            recognizer=KaldiRecognizer(model,16000)
                        was_speaking=True
                        continue
                    was_speaking=False
                    packet=self.normalize_mic_packet(packet,native_rate)
                    data=np.frombuffer(packet,dtype="<i2")
                    rms=float(np.sqrt(np.mean(data.astype(np.float64)**2))) if data.size else 0
                    # Bounded UI telemetry: 5 readings/s, no microphone audio
                    # leaves this thread and no levels are saved to disk.
                    stamp=time.monotonic()
                    if self.on_audio_level and stamp-last_level_report>=0.18:
                        last_level_report=stamp
                        if self.running and generation==self._generation:
                            try:self.on_audio_level(min(1.0,rms/32768.0))
                            except Exception:pass  # UI errors cannot stop speech
                    speech_threshold=max(24.0,min(200.0,noise_floor*2.6+12))
                    if rms>speech_threshold:
                        if not segment:
                            segment.extend(b"".join(pre_roll))
                            pre_roll.clear()
                        segment.extend(packet)
                        silent=0
                    elif segment:
                        segment.extend(packet)
                        silent+=1
                    else:
                        pre_roll.append(packet)
                        noise_floor=0.98*noise_floor+0.02*rms
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
                    if segment and (silent>=7 or len(segment)>=max_segment):
                        utterance=bytes(segment)
                        segment.clear();silent=0
                        text=json.loads(recognizer.FinalResult()).get("text","").strip()
                        combined=" ".join([*vosk_parts, text]).strip()
                        vosk_parts.clear()
                        pre_roll.clear()
                        recognizer=KaldiRecognizer(model,16000)
                        recognizer.SetWords(True)
                        has_wake=segment_vosk_wake or bool(WAKE.match(combined))
                        segment_vosk_wake=False
                        # Never dispatch raw Vosk command text before the more
                        # accurate Whisper pass has had a chance to recognize it.
                        self._try_whisper(utterance,has_wake,combined)
        except Exception as exc:
            self.on_status("Ошибка микрофона: "+str(exc)[:180])
        finally:
            with self.lock:
                if generation==self._generation:
                    self.running=False
