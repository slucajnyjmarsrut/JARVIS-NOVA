# -*- coding: utf-8 -*-
"""Production JARVIS NOVA controller: keyboard and text replies only.

No voice/microphone/speaker/ASR/TTS engine is ever created.
Older modules are retained for legacy test coverage, not for app use.
"""
from __future__ import annotations
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

from main import Jarvis as BaseJarvis
from main import LearningStore, ModeManager, GameCatalog, Desktop
from main import LocalChat, ModeCommand
from bundled_vision_runtime import BundledRuntimeConfig, BundledVisionRuntime
from nova_compact_ui import compact_geometry
from nova_window_state import load_layout, safe_window_geometry
from nova_overlay import dock_geometry
from text_only_ui import build_text_interface
from text_only_overlay import TextOverlay
from freellm_client import FreeLLMChat, FreeLLMError
from update_preferences import load_preferences


class NoAudio:
    """Inert compatibility object; owns no device and plays no sound."""
    busy = False
    speaking = False
    whisper_busy = False
    until = 0

    def vision_source(self, text):
        phrase = str(text).casefold().replace("ё", "е")
        return "screen" if any(s in phrase for s in (
            "посмотри на экран", "опиши экран", "что на экране",
            "что ты видишь", "что видишь на экране", "покажи экран",
            "анализ экрана")) else None


class TextJarvis(BaseJarvis):
    """Keep code, desktop, model and video capabilities; disable speech."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("JARVIS NOVA — Текст")
        self._ui_layout = load_layout()
        default = compact_geometry(self.winfo_screenwidth(), self.winfo_screenheight())
        geometry = safe_window_geometry(
            self._ui_layout.get("main"), default,
            self.winfo_screenwidth(), self.winfo_screenheight())
        self.geometry(geometry)
        self.minsize(min(385, self.winfo_screenwidth()), min(600, self.winfo_screenheight()))
        self._last_normal_geometry = geometry
        self.configure(bg="#070D17")
        self.after(60, self._set_native_dark_titlebar)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.q = queue.Queue()
        self.voice_enabled = False
        self._answer_style = "normal"
        self.overlay_show_text = True
        self.overlay_last_user = ""
        self.overlay_last_answer = ""
        self._closing = False
        self._shutdown = threading.Event()
        self.executing = False
        self.control_allowed = False
        self.vision_allowed = False
        self.engine = "bundled"
        self.learning = LearningStore()
        self.modes = ModeManager()
        self.games = GameCatalog()
        self._focus_deadline = None
        self._focus_epoch = 0
        self._pending_alias = None
        self._auto_update_busy = False
        self._auto_update_pending = None
        self._auto_update_first_seen = 0.0
        self._auto_update_state = "Готов к проверке обновлений."
        self._auto_update_progress = 0
        self._auto_update_snoozed = False
        self._update_center = None
        self._last_input_activity = time.monotonic()
        self.update_preferences = load_preferences()

        self.voice = NoAudio()
        self.speaker = NoAudio()
        self.trimodal = NoAudio()
        assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
        self.runtime = BundledVisionRuntime(BundledRuntimeConfig(root=assets))
        self.trimodal.runtime = self.runtime
        self.local_chat = LocalChat(self.runtime)
        self.freellm_chat = FreeLLMChat()
        self._freellm_consent = False
        self.desktop = Desktop(
            lambda: self.control_allowed, lambda: self.vision_allowed,
            learning=self.learning)

        build_text_interface(self)
        self.overlay = TextOverlay(self)
        mini_default = dock_geometry(self.winfo_screenwidth(), self.winfo_screenheight())
        mini = safe_window_geometry(self._ui_layout.get("mini"), mini_default,
            self.winfo_screenwidth(), self.winfo_screenheight(), fixed=True)
        if self._ui_layout.get("mini"):
            self.overlay.geometry(mini)
            self.overlay._manual_position = True
        self.bind("<Configure>", self._remember_main_geometry, add="+")
        self.bind("<Unmap>", self._main_unmapped, add="+")
        self.bind("<Map>", self._main_mapped, add="+")
        self.bind("<Control-Shift-O>", lambda e:(self.toggle_overlay(), "break")[1])
        # Keep track of activity in all Tk windows so updates cannot close a
        # half-written script or a user who is actively editing/reading.
        self.bind_all("<KeyPress>",self._record_interaction,add="+")
        self.bind_all("<ButtonPress>",self._record_interaction,add="+")

        # The stock Tk menu was light, clipped on compact displays and
        # inconsistent with the dark JARVIS design. Use a bounded dark palette.
        self._command_palette = None
        self.hud_settings_button.configure(command=self.show_settings_menu)
        self.bind("<F10>", self.show_settings_menu)

        self.log("Система", "Только текст: напиши сообщение и нажми Enter. Микрофон и озвучивание отключены.")
        self.after(100, self.pump)
        self.after(3500, self._check_auto_update)
        self.after(150, self.entry.focus_set)

    def _record_interaction(self, event=None):
        self._last_input_activity=time.monotonic()

    def show_update_center(self):
        from update_center import show_update_center
        return show_update_center(self)

    def show_settings_menu(self, event=None):
        from nova_command_palette import show_palette
        if not self._closing:
            show_palette(self)
        return "break"

    def _palette_start_focus_timer(self):
        self.handle_mode_command(
            ModeCommand("timer_start", "Таймер 25 минут", minutes=25))

    def set_engine(self, engine):
        if engine == "freellm":
            if not self._freellm_consent:
                if not messagebox.askyesno(
                    "FreeLLM — разрешить отправку текста?",
                    "FreeLLM может отправлять ваши сообщения внешним провайдерам ИИ. "
                    "При генерации кода содержимое проекта также может быть отправлено. "
                    "API-ключи хранятся на вашем компьютере, не в GitHub. "
                    "Разрешить использование FreeLLM в этой сессии?", parent=self):
                    return
                self._freellm_consent = True
            self.engine = "freellm"
            self.status.set("FreeLLM · несколько моделей · текстовый режим")
            return
        return super().set_engine(engine)

    def init_voice(self):
        return None

    def toggle_voice(self):
        self.status.set("Голосовой ввод и озвучивание отключены.")
        return None

    def f9(self, event=None):
        self.entry.focus_set()
        return "break"

    def show_capabilities(self):
        messagebox.showinfo("JARVIS NOVA — текст",
            "Пиши сообщения в чате, ответы появляются только текстом.\n\n"
            "Локальная Qwen, команды Windows, 20 языков, Roblox 3D, монтаж и "
            "анализ экрана с подтверждением доступны.\n"
            "Микрофон и синтез речи не запускаются.", parent=self)

    def check_models(self):
        from bundled_vision_runtime import validate_offline_model_store
        try:
            validate_offline_model_store(self.runtime.config.root)
            message="Локальная Qwen: файлы модели найдены. Это не тест инференса."
        except Exception as exc:
            message="Локальная Qwen недоступна: "+str(exc)[:160]
        messagebox.showinfo("Локальная модель", message, parent=self)

    def open_filmcraft(self):
        studio=self.open_viral_studio(stage="edit")
        if studio is not None:
            studio.open_filmcraft()

    def open_viral_studio(self, stage="audience"):
        if self._closing:
            return None
        from viral_studio_ui import ViralStudioWindow
        old = getattr(self, "_viral_window", None)
        if old is not None and old.winfo_exists():
            old.lift()
            old.focus_stage(stage)
            return old
        # No audio speaker is ever handed to the editor.
        self._viral_window = ViralStudioWindow(self, speaker=None)
        self._viral_window.focus_stage(stage)
        return self._viral_window

    def request_trimodal(self, source="screen", audio_pcm=None):
        """Text question + user-approved screenshot; never record audio."""
        if self._closing or self.executing:
            return
        if source != "screen":
            self.reply("Доступен только экран, не камера.")
            return
        question = simpledialog.askstring("Анализ экрана",
            "Напиши свой вопрос об экране:",
            initialvalue="Что сейчас на экране?", parent=self)
        if question is None:
            return
        question = question.strip()
        if not 1 <= len(question) <= 1200:
            self.reply("Вопрос должен содержать 1–1200 символов.")
            return
        if not messagebox.askyesno("Разрешение на экран",
            "Разрешить один снимок экрана и его обработку локальной моделью? "
            "Изображение не отправляется в облако.", parent=self):
            self.status.set("Снимок экрана отменён")
            return
        self.executing = True
        self.status.set("Анализирую экран локально…")
        def work():
            try:
                from screen_capture import ScreenFrameSource
                from vision_engine import LocalOllamaVision, VisionConfig
                endpoint = self.runtime.start()
                model = LocalOllamaVision(VisionConfig(endpoint=endpoint))
                model.initialize()
                answer = model.describe(question, ScreenFrameSource().capture_jpeg())
                if not self._shutdown.is_set():
                    self.q.put(("action_result", (True, answer, (), "normal")))
            except Exception as exc:
                if not self._shutdown.is_set():
                    self.q.put(("action_result", (
                        False, "Не могу проанализировать экран: "+str(exc)[:180], (), "normal")))
        threading.Thread(target=work, daemon=True, name="jarvis-text-vision").start()

    def reply(self, message):
        if self._closing:
            return
        self.log("JARVIS", str(message))
        self.status.set(str(message)[:130])
        # Absolutely no Speaker.say(), voice.activate(), or TTS threads.

    def close(self):
        if self._closing:
            return
        try:
            self.save_window_layout()
        except Exception:
            pass
        self._closing = True
        palette = getattr(self, "_command_palette", None)
        if palette is not None:
            palette.close()
        self._shutdown.set()
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            try:
                overlay.shutdown()
            except tk.TclError:
                pass
        studio = getattr(self, "_viral_window", None)
        if studio is not None:
            try:
                studio.cancel()
            except Exception:
                pass
        self.local_chat.close()
        self.freellm_chat.close()
        self._focus_epoch += 1
        self._focus_deadline = None
        self.control_allowed = False
        self.vision_allowed = False
        threading.Thread(target=self.runtime.stop, daemon=True,
                         name="jarvis-runtime-stop").start()
        self.destroy()


if __name__ == "__main__":
    TextJarvis().mainloop()
