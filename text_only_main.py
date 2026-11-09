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
from model_storage import active_model_store, local_model_available, installed_edition


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
        self._asset_root=assets
        self._model_download_busy=False
        self._model_download_queue=queue.Queue()
        self._model_download_cancel=threading.Event()
        self.runtime = BundledVisionRuntime(BundledRuntimeConfig(
            root=assets,model_store=active_model_store(assets)))
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
        if not self._local_model_ready:
            self.log("Система", "Qwen не установлена. Для полноценного чата открой ⚙ → "
                     "«Проверить локальную модель». Загрузка только с твоего разрешения.")
        self.after(100, self.pump)
        self.after(3500, self._check_auto_update)
        self.after(150, self.entry.focus_set)
        self.after(250,self._pump_model_download)

    def check_models(self):
        """No speech asset imports. Offer Lite users a consent-gated Qwen pull."""
        from bundled_vision_runtime import validate_offline_model_store
        try:
            validate_offline_model_store(
                self._asset_root,model_store=self.runtime.config.model_store)
        except Exception:
            self._local_model_ready=False
            if self._model_download_busy:
                messagebox.showinfo("Локальная Qwen",
                    "Загрузка модели уже идёт. Прогресс отображается в чате.",
                    parent=self)
                return
            if messagebox.askyesno("Скачать локальную Qwen?",
                "Локальная Qwen ещё не установлена.\n\n"
                "Скачать приблизительно 1,9 ГБ с официального реестра Ollama?\n"
                "Потребуется интернет и не менее 3 ГБ свободного места.\n"
                "JARVIS сохранит модель отдельно от программы, "
                "чтобы обновления не загружали её повторно.\n\n"
                "Начать загрузку?",parent=self):
                self.download_local_model()
            return
        self._local_model_ready=True
        messagebox.showinfo("Локальная модель готова",
            "Qwen установлена и может отвечать без интернета. "
            "Модель находится в "+str(self.runtime.config.model_store),parent=self)

    def download_local_model(self):
        if self._model_download_busy or self._closing:
            return
        self._model_download_busy=True
        self.log("Система","Скачиваю Qwen после твоего разрешения. "
                 "Прогресс указан ниже. Текстовая программа остаётся открытой.")
        self.status.set("Загрузка Qwen: подключение к официальной Ollama…")
        self._model_download_cancel.clear()
        def worker():
            try:
                from optional_model_downloader import download_qwen
                store=download_qwen(
                    self._asset_root,target=self.runtime.config.model_store,
                    confirm=True,cancel=self._model_download_cancel,
                    progress=lambda size:self._model_download_queue.put(
                        ("progress",int(size))))
                self._model_download_queue.put(("done",str(store)))
            except Exception as exc:
                self._model_download_queue.put(
                    ("error",type(exc).__name__+": "+str(exc)[:170]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-consented-qwen-download").start()

    def _pump_model_download(self):
        if self._closing:
            return
        try:
            while True:
                kind,value=self._model_download_queue.get_nowait()
                if kind=="progress":
                    self.status.set("Скачивание локальной Qwen: "+
                        f"{value/1_000_000_000:.2f} ГБ загружено")
                elif kind=="done":
                    self._model_download_busy=False
                    self._local_model_ready=True
                    self.hud_engine.configure(text="QWEN · ЛОКАЛЬНО",fg="#6CDEAF")
                    self.log("Система","Локальная Qwen установлена и проверена. "
                             "Теперь чат и анализ экрана работают офлайн.")
                    self.status.set("Локальная Qwen установлена и готова")
                elif kind=="error":
                    self._model_download_busy=False
                    self._local_model_ready=False
                    self.log("Система","Модель не установлена: "+str(value))
                    self.status.set("Не удалось скачать Qwen — можно повторить через ⚙")
        except queue.Empty:
            pass
        self.after(250,self._pump_model_download)

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
        if engine == "bundled" and not local_model_available(self._asset_root):
            self.status.set("Локальная Qwen ещё не установлена: ⚙ → Проверить локальную модель")
            self.check_models()
            return
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

    def open_screenshot_review(self):
        """User selects and marks an image; nothing is captured automatically."""
        if self._closing:
            return None
        old = getattr(self, "_screenshot_review", None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        from screenshot_review import ScreenshotReview
        self._screenshot_review = ScreenshotReview(self)
        return self._screenshot_review

    def screenshot_ready(self):
        """Never send an image to FreeLLM or any external provider."""
        return (not self._closing and self.engine == "bundled"
                and bool(getattr(self, "_local_model_ready", False)))

    def submit_screenshot(self, question, jpeg):
        """Request a read-only local Vision explanation, never edit application code."""
        if not self.screenshot_ready() or self.executing:
            return False
        if not isinstance(jpeg, bytes) or not 32 <= len(jpeg) <= 4_000_000:
            return False
        question = str(question or "").strip()
        if not 1 <= len(question) <= 900:
            return False
        self.executing = True
        self.log("Вы", "[Размеченный скриншот] " + question)
        self.status.set("Анализирую красные отметки локальной Qwen…")

        def work():
            try:
                from vision_engine import LocalOllamaVision, VisionConfig
                endpoint = self.runtime.start()
                vision = LocalOllamaVision(VisionConfig(endpoint=endpoint))
                vision.initialize()
                answer = vision.describe(
                    "Это скриншот приложения. Красным пользователь отметил "
                    "проблемные области. Опиши, что видно, какие возможны "
                    "ошибки и что стоит проверить в коде. Не утверждай, что "
                    "исправления уже сделаны. Задача: " + question, jpeg)
                result = (True, answer, "normal")
            except Exception as exc:
                from local_chat import explain_local_model_failure
                result = (False, explain_local_model_failure(exc), "normal")
            if not self._shutdown.is_set():
                self.q.put(("chat_result", result))
        threading.Thread(target=work, daemon=True,
                         name="jarvis-local-screenshot-review").start()
        return True

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
        self._model_download_cancel.set()
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
