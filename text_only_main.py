# -*- coding: utf-8 -*-
"""Production JARVIS NOVA controller: keyboard and text replies only.

No voice/microphone/speaker/ASR/TTS engine is ever created.
Older modules are retained for legacy test coverage, not for app use.
"""
from __future__ import annotations
import os
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
from chat_first_intent import route_chat_request
from intuitive_start import initial_guidance, clarification
from semantic_intent_router import (
    classify_local_intent, suitable_for_semantic_routing,
)
from agent_core import parse_local


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
        self._debate_mode = False
        # The legacy mode dispatcher updates this variable even when the
        # visible mode buttons are removed from the chat-only screen.
        self._selected_mode = tk.StringVar(master=self, value="neutral")
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
        self._model_scan_busy=False
        self._model_scan_queue=queue.Queue()
        self._model_scan_cancel=threading.Event()
        self._semantic_queue=queue.Queue()
        self._semantic_busy=False
        self._semantic_epoch=0  # Invalidates old model actions after new input.
        self._model_download_last_size=0
        self._model_download_last_change=time.monotonic()
        self._last_screenshot_report=""
        self._self_development_window=None
        self.runtime = BundledVisionRuntime(BundledRuntimeConfig(
            root=assets,model_store=active_model_store(assets)))
        self.trimodal.runtime = self.runtime
        self.local_chat = LocalChat(self.runtime)
        # Do not opt into the separate Qwen3 chat before a user selects it.
        # TaskAIHub enables Qwen3 only after its explicit model setup.
        # Once selected, missing Qwen3 never silently falls back to Vision.
        self.freellm_chat = FreeLLMChat()
        self._freellm_consent = False
        self.desktop = Desktop(
            lambda: self.control_allowed, lambda: self.vision_allowed,
            learning=self.learning)

        build_text_interface(self)
        self._restore_startup_permissions()
        # The current-user Supervisor monitors approved tasks from startup,
        # even when the queue is initially empty. Frozen builds start a
        # separate headless process that survives closing this UI.
        from night_autorecovery import start_always_on
        self.after(1200, start_always_on)
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

        # First-use guidance is in the chat and on the screen: no blocking
        # modal and no need to remember a special command.
        self.log("Система", "JARVIS готов. "+
                 initial_guidance(self._local_model_ready))
        self.after(100, self.pump)
        self.after(3500, self._check_auto_update)
        self.after(150, self.entry.focus_set)
        self.after(250,self._pump_model_download)
        self.after(300,self._pump_model_scan)

    def check_models(self, *, offer_scan=True):
        """Explicit download skips disk scan but still asks for UI permission."""
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
            if (offer_scan and not self._model_scan_busy and
                    messagebox.askyesno(
                        "Сначала найти уже скачанные модели?",
                        "JARVIS проверяет только свой кеш. Возможно, Qwen "
                        "или другие модели находятся на других дисках. "
                        "Разрешить однократный локальный поиск по всем "
                        "фиксированным дискам Windows? "
                        "Системные папки и содержимое документов не читаются; "
                        "в сеть ничего не отправляется.",
                        parent=self)):
                self.scan_models_on_pc(confirmed=True)
                return
            if messagebox.askyesno("Скачать локальную Qwen?",
                "JARVIS пока не обнаружил совместимую Qwen.\n\n"
                "Скачать приблизительно 1,9 ГБ с официального реестра Ollama?\n"
                "Потребуется интернет и не менее 3 ГБ свободного места.\n"
                "JARVIS сохранит модель отдельно от программы, "
                "чтобы обновления не загружали её повторно.\n\n"
                "Начать загрузку?",parent=self):
                self.download_local_model()
            return
        self._local_model_ready=True
        messagebox.showinfo("Qwen готова к работе",
            "Qwen подключена и может отвечать без интернета.\n\n"
            "Что дальше: напиши вопрос в чат или нажми "
            "«РАЗОБРАТЬ СНИМОК», чтобы выбрать изображение. "
            "Доступ к экрану не включается автоматически.\n\n"
            "Модель находится в "+str(self.runtime.config.model_store),
            parent=self)

    def scan_models_on_pc(self, *, confirmed=False):
        """Explicit read-only inventory across all fixed local Windows disks."""
        if self._model_scan_busy:
            self.reply("Поиск моделей уже идёт. Для отмены напиши «останови поиск моделей».")
            return
        if os.name!="nt":
            self.reply("Поиск по всем локальным дискам доступен в Windows-сборке.")
            return
        if not confirmed and not messagebox.askyesno(
            "Искать модели на всём компьютере?",
            "Проверить ВСЕ локальные жёсткие диски, включая папки вне JARVIS?\n\n"
            "Будут читаться имена, пути и размеры файлов моделей, а также "
            "служебный манифест совместимой Qwen. Личные документы "
            "не открываются, программы не "
            "запускаются, в сеть ничего не отправляется. Системные папки "
            "пропускаются. Поиск ограничен 100 секундами, его можно отменить.\n\n"
            "Разрешить однократный поиск?",
            parent=self):
            self.reply("Поиск моделей не запускался.")
            return
        self._model_scan_cancel.clear()
        self._model_scan_busy=True
        self.reply("Ищу локальные модели на всех доступных дисках. "
                   "Для отмены напиши «останови поиск моделей».")
        def worker():
            try:
                from local_model_inventory import scan_local_models
                result=scan_local_models(
                    confirmed=True,cancel=self._model_scan_cancel,
                    progress=lambda folders,files,found:
                        self._model_scan_queue.put(
                            ("progress",(folders,files,found))))
                self._model_scan_queue.put(("result",result))
            except Exception as exc:
                self._model_scan_queue.put(("error",str(exc)[:220]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-local-model-inventory").start()

    def cancel_model_scan(self):
        if self._model_scan_busy:
            self._model_scan_cancel.set()
            self.reply("Останавливаю поиск моделей; ничего не изменено.")

    def _pump_model_scan(self):
        if self._closing:
            return
        try:
            while True:
                event,data=self._model_scan_queue.get_nowait()
                if event=="progress":
                    if self._model_scan_busy:
                        directories,files,count=data
                        self.status.set(
                            f"Модели: {directories} папок, {files} файлов, "
                            f"найдено {count}")
                elif event=="result":
                    from local_model_inventory import summarize_inventory
                    self._model_scan_busy=False
                    self.log("Система",summarize_inventory(data))
                    compatible=[m for m in data.models if m.jarvis_compatible]
                    if compatible and not data.cancelled:
                        store=compatible[0].location
                        if messagebox.askyesno(
                            "Использовать уже установленную Qwen?",
                            "Найдена совместимая Qwen в папке:\n"
                            +str(store)+"\n\n"
                            "Проверить SHA256 файлов и запомнить путь? "
                            "Большая модель НЕ копируется, НЕ загружается "
                            "из сети и НЕ запускается до обычного запроса.",
                            parent=self):
                            self._model_scan_busy=True
                            self.status.set("Проверяю SHA256 найденной модели…")
                            def adopt():
                                try:
                                    from model_storage import remember_existing_model_store
                                    validated=remember_existing_model_store(
                                        store,confirmed=True,
                                        cancel=self._model_scan_cancel)
                                    self._model_scan_queue.put(("adopted",validated))
                                except Exception as exc:
                                    self._model_scan_queue.put(("error",str(exc)[:240]))
                            threading.Thread(target=adopt,daemon=True,
                                name="jarvis-existing-model-verification").start()
                elif event=="adopted":
                    from dataclasses import replace
                    self._model_scan_busy=False
                    self.runtime.config=replace(
                        self.runtime.config,model_store=data)
                    self._local_model_ready=True
                    self.hud_engine.configure(
                        text="QWEN · ЛОКАЛЬНО",fg="#6CDEAF")
                    self.reply("Нашёл и подключил Qwen из прежней папки. "
                               "Можно задавать вопросы в чате или нажать "
                               "«РАЗОБРАТЬ СНИМОК», чтобы выбрать файл. "
                               "Экран не просматривается без разрешения.")
                elif event=="error":
                    self._model_scan_busy=False
                    self.reply("Поиск или подключение модели не завершены: "+str(data))
        except queue.Empty:
            pass
        self.after(300,self._pump_model_scan)

    def download_local_model(self):
        if self._model_download_busy or self._closing:
            return
        self._model_download_busy=True
        self._model_download_last_size=0
        self._model_download_last_change=time.monotonic()
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
                        ("progress",int(size))),
                    stage=lambda text:self._model_download_queue.put(
                        ("stage",str(text)[:240])))
                self._model_download_queue.put(("done",str(store)))
            except Exception as exc:
                self._model_download_queue.put(
                    ("error",type(exc).__name__+": "+str(exc)[:170]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-consented-qwen-download").start()

    def cancel_local_model_download(self):
        """User-initiated cancel; Ollama partial data remains in user cache."""
        if not self._model_download_busy:
            self.status.set("Загрузка Qwen сейчас не выполняется.")
            return
        self._model_download_cancel.set()
        self.status.set("Останавливаю скачивание Qwen. Загруженные части сохраняются.")

    def _pump_model_download(self):
        if self._closing:
            return
        try:
            while True:
                kind,value=self._model_download_queue.get_nowait()
                if kind=="progress":
                    if self._model_download_cancel.is_set():
                        continue
                    now=time.monotonic()
                    bytes_received=max(0,int(value))
                    if bytes_received!=self._model_download_last_size:
                        self._model_download_last_size=bytes_received
                        self._model_download_last_change=now
                    idle=int(now-self._model_download_last_change)
                    if idle>=60:
                        self.status.set(
                            "Qwen: "+f"{bytes_received/1_000_000_000:.2f} ГБ; "
                            +f"нет новых данных {idle//60} мин. "
                            "Отмена через видимую кнопку «СТОП QWEN».")
                    else:
                        self.status.set("Скачивание локальной Qwen: "+
                            f"{bytes_received/1_000_000_000:.2f} ГБ загружено")
                elif kind=="stage":
                    if not self._model_download_cancel.is_set():
                        self.log("Система",str(value)[:240])
                        self.status.set(str(value)[:240])
                elif kind=="done":
                    self._model_download_busy=False
                    self._local_model_ready=True
                    self.hud_engine.configure(text="QWEN · ЛОКАЛЬНО",fg="#6CDEAF")
                    self.log("Система","Qwen установлена и проверена. "
                             "Следующий шаг: напиши вопрос JARVIS или нажми "
                             "«РАЗОБРАТЬ СНИМОК», чтобы выбрать изображение. "
                             "Для прямого просмотра экрана нужно отдельное разрешение.")
                    self.status.set("Qwen готова · Напиши вопрос или выбери снимок")
                elif kind=="error":
                    self._model_download_busy=False
                    self._local_model_ready=False
                    self.log("Система","Модель не установлена: "+str(value))
                    self.status.set(
                        "Qwen: "+str(value)[:195])
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
            self.status.set("Локальная Qwen пока не подключена: найди модели на всех дисках")
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
        # Inert legacy compatibility; no UI entry point or device activation.
        return None

    def f9(self, event=None):
        self.entry.focus_set()
        return "break"

    def show_capabilities(self):
        messagebox.showinfo(
            "Что можно сделать в JARVIS",
            "Выбери задачу в главном окне:\n"
            "• СОЗДАТЬ ВИДЕО — сценарии и ролики.\n"
            "• СМОНТИРОВАТЬ — работа с готовыми файлами.\n"
            "• НАПИСАТЬ КОД — откроется редактор проекта.\n"
            "• РАЗОБРАТЬ СНИМОК — выбрать скриншот с компьютера.\n\n"
            "Можно просто написать просьбу своими словами.\n"
            "Для беседы с Qwen и анализа изображений нужна Qwen3-VL.\n"
            "Доступ к экрану, скачивание и запись файлов "
            "требуют отдельного подтверждения.",
            parent=self)

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
        # Video soundtracks are media-editing data, not assistant speech.
        self._viral_window = ViralStudioWindow(self, speaker=None)
        self._viral_window.focus_stage(stage)
        return self._viral_window

    def open_task_ai_hub(self, role="scenario"):
        """Task AI setup is separate from bundled Qwen and opt-in only."""
        if self._closing:
            return None
        old=getattr(self,"_task_ai_hub",None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        from task_ai_hub import TaskAIHub
        self._task_ai_hub=TaskAIHub(self,role=role)
        return self._task_ai_hub

    def open_night_supervisor(self):
        """Open the approval-scoped overnight queue; no automatic startup."""
        if self._closing:
            return None
        old = getattr(self, "_night_window", None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        from night_supervisor_ui import NightSupervisorWindow
        from night_supervisor import SupervisorError
        try:
            self._night_window = NightSupervisorWindow(self)
        except (SupervisorError, OSError) as exc:
            messagebox.showerror("Ночной Supervisor недоступен", str(exc),
                                 parent=self)
            return None
        return self._night_window

    def open_self_development(self, task=""):
        """Guided, review-first source fixes. Installed EXE is never modified."""
        if self._closing:
            return None
        from self_development_ui import SelfDevelopmentWindow
        report=task or getattr(self, "_last_screenshot_report", "")
        old=getattr(self, "_self_development_window", None)
        if old is not None and old.winfo_exists():
            old.prefill(report)
            return old
        self._self_development_window=SelfDevelopmentWindow(self, task=report)
        return self._self_development_window

    def _dispatch_chat_first(self, intent, text):
        """Run only the predefined, permission-preserving user-facing actions."""
        kind, value = intent.kind, intent.value
        self.log("Вы", text)
        if kind == "help":
            self.reply(initial_guidance(
                bool(getattr(self, "_local_model_ready", False))))
        elif kind in ("clarify_video", "clarify_model",
                      "clarify_screen", "clarify_code"):
            self.reply(clarification(kind))
        elif kind == "manual_delete":
            self.show_manual_delete_location(folder=value=="folder")
        elif kind == "clarify_workflow":
            self.reply("Могу работать по плану: сначала разделить задачу, "
                       "затем проверять каждый этап и проверить всё вместе. "
                       "Для кода напиши «сделай по шагам программу ...». "
                       "Для видео: «создай сценарий по шагам про ...». "
                       "Неизвестные действия и доступ к ПК не запускаю автоматически.")
        elif kind == "settings":
            self.reply("Открываю настройки JARVIS.")
            self.show_settings_menu()
        elif kind == "updates":
            self.show_update_center()
        elif kind == "model":
            self.check_models()  # Search optional; download needs consent.
        elif kind == "model_download":
            self.check_models(offer_scan=False)  # Direct consent dialog.
        elif kind == "model_scan":
            self.scan_models_on_pc()
        elif kind == "cancel_model_scan":
            self.cancel_model_scan()
        elif kind == "cancel_model":
            self.cancel_local_model_download()
        elif kind == "engine":
            self.set_engine(value)  # FreeLLM retains external-data consent.
        elif kind == "permission_control":
            self.grant_control()  # Uses existing right; asks only if revoked.
        elif kind == "permission_screen":
            # Already-active startup access needs no repeated prompt.
            # After revocation, grant_vision requires explicit confirmation.
            self.grant_vision()
            if bool(getattr(self, "vision_allowed", False)):
                self.reply(
                    "Доступ к экрану разрешён. "
                    "Для анализа изображения открой «ПОКАЗАТЬ СКРИНШОТ». "
                    "Это не включает постоянное наблюдение за экраном.")
            else:
                self.reply(
                    "Доступ к экрану не предоставлен. "
                    "Включить его можно через кнопку «РАЗРЕШИТЬ ЭКРАН» "
                    "с отдельным подтверждением.")
        elif kind == "revoke":
            self.revoke()
            self.reply("Доступ к компьютеру и экрану отключён.")
        elif kind == "minimize":
            self.hide_main()
        elif kind == "screenshot":
            self.open_screenshot_review()  # User selects image manually.
        elif kind == "gaming":
            self.handle_mode_command(self.modes.set_mode("gaming"))
            self.reply("Игровой режим включён. Напиши «игра Portal 2» "
                       "или название своей игры — никаких кнопок не требуется.")
        elif kind == "open_desktop":
            self.execute_plan(parse_local("открой " + value))
        elif kind == "code_steps":
            self.open_code_assistant("python", value, auto_start=False)
            self.reply("Открыл редактор кода с задачей. Здесь виден план "
                       "из этапов; нажми «Составить план → выполнить и проверить». "
                       "Каждый этап проверяется отдельно, затем весь проект "
                       "вместе. Запись в твою папку — только после подтверждения.")
        elif kind == "scenario_steps":
            studio=self.open_viral_studio(stage="script")
            if studio is not None and value:
                studio.topic.set(value)
                studio.scenario_mode.set("deep")
            self.reply("Открыл отдельный ИИ-сценарист Gemma3:4b: тема, пять кадров, "
                       "проверка каждого кадра, затем проверка всего сценария. "
                       "Запусти генерацию в студии после проверки темы. "
                       "Если Gemma3 не подключена, выбери «ПОДКЛЮЧИТЬ ИИ-СЦЕНАРИСТА».")
        elif kind == "code_start":
            self.open_code_assistant("python", "", auto_start=False)
            self.reply("Открыл редактор кода. Выбери папку и опиши, "
                       "какую программу хочешь получить. "
                       "Запись файлов и запуск потребуют подтверждения.")
        elif kind == "code":
            if not value:
                self.reply("Назови один язык программирования — например "
                           "Python, Java, JavaScript или Roblox Luau.")
                return
            self.open_code_assistant(value, text, auto_start=True)
            self.reply("Запустил создание полноценного проекта с внутренней проверкой. "
                       "Файлы будут сохранены только после подтверждения. "
                       "Запуск и запись файлов "
                       "только после проверки и подтверждения.")
        elif kind == "scenario":
            studio=self.open_viral_studio(stage="script")
            if studio is not None:
                if value:
                    studio.topic.set(value)
                    studio.scenario_mode.set("deep")
                    # Entire request creates a script; no second button.
                    studio.after(70,studio.generate)
                    self.reply("Сценарий создаёт отдельная Gemma3:4b. "
                               "Если она не установлена, нажми в студии "
                               "«ПОДКЛЮЧИТЬ ИИ-СЦЕНАРИСТА».")
                else:
                    self.reply("Напиши тему сценария.")
        elif kind == "studio":
            self.open_viral_studio(stage="audience")
        elif kind == "filmcraft":
            self.open_filmcraft()
        elif kind == "timeline":
            self.open_timeline()
        elif kind == "longform":
            window=self.open_timeline()
            if window is not None:
                window.after(
                    80,lambda w=window:w.prepare_longform(auto_export=True))
            self.reply("Готовлю черновой 15-минутный монтаж из длинных исходников. "
                       "Выбери локальные видео: смогу сам экспортировать монтаж "
                       "после одного подтверждения. Оригиналы сохранятся.")
        elif kind == "multitrack":
            self.open_multitrack()
        elif kind == "edits":
            self.open_viral_studio(stage="edits")
        elif kind == "publish":
            self.open_publish_preparation()
            self.reply("Подготовка публикации открыта. Загрузка в соцсети "
                       "не выполняется автоматически.")
        elif kind == "accounts":
            self.open_creator_accounts()
            self.reply("Открыл помощник регистрации. Личные данные и "
                       "проверочные коды вводишь на официальном сайте.")

    def handle_text(self, text):
        from self_development import is_self_fix_command
        if self._closing:
            return
        if getattr(self, "_semantic_busy", False) is True:
            # A newer message cancels the previous proposed action. The
            # worker may finish, but its stale answer cannot reach the UI.
            self._semantic_epoch += 1
            self._semantic_busy=False
        chat_intent=route_chat_request(text)
        if chat_intent is not None:
            self._dispatch_chat_first(chat_intent, text)
            return
        if is_self_fix_command(text):
            self.log("Вы", text)
            previous=getattr(self, "_last_screenshot_report", "")
            task=(str(text).strip() + ("\n" + previous if previous else ""))[:2600]
            self.open_self_development(task=task)
            self.reply("Открыл самоисправление. Выбери исходники в ветке jarvis, "
                       "проверь предложенный код и подтверди запись. "
                       "Обновление EXE выполняется только через проверенный релиз.")
            return
        from video_timeline import is_timeline_request
        if is_timeline_request(text):
            self.log("Вы",text)
            self.open_timeline()
            self.reply("Открыл редактор таймлайна: порядок клипов, точная "
                       "обрезка, скорость, титры, музыка и переходы. "
                       "Экспорт начнётся только после твоего подтверждения.")
            return
        from multitrack_composer import is_multitrack_request
        from creator_publish import is_publish_prep_request
        if is_multitrack_request(text):
            self.log("Вы",text)
            self.open_multitrack()
            self.reply("Открыл многодорожечный монтаж: наложения, титры, "
                       "музыка и озвучка. Твои файлы не будут изменены, "
                       "пока ты не подтвердил экспорт.")
            return
        if is_publish_prep_request(text):
            self.log("Вы",text)
            self.open_publish_preparation()
            self.reply("Открыл подготовку публикации. Черновик останется "
                       "на компьютере; MP4 загружаешь через официальный "
                       "сайт самостоятельно. Автопубликация не включена.")
            return
        from popular_edits import is_popular_edit_request
        from creator_accounts import is_creator_signup_request
        if is_popular_edit_request(text):
            self.log("Вы", text)
            self.open_viral_studio(stage="edits")
            self.reply("Открыл 16 стилей эдитов. Выбери стиль, папку "
                       "с собственными клипами и новый MP4. "
                       "Монтаж начнётся только после твоего подтверждения.")
            return
        if is_creator_signup_request(text):
            self.log("Вы", text)
            self.open_creator_accounts()
            self.reply("Открыл помощник регистрации YouTube, TikTok и Instagram. "
                       "Пароль, дату рождения и проверочные коды вводи "
                       "самостоятельно на официальном сайте.")
            return
        if (getattr(self, "engine", None) == "bundled"
                and bool(getattr(self, "_local_model_ready", False))
                and not getattr(self, "executing", False)
                and suitable_for_semantic_routing(text)):
            if getattr(self, "_semantic_busy", False) is True:
                self.log("Вы", text)
                self.reply("Обрабатываю предыдущую команду. Повтори запрос позже.")
                return
            self._semantic_busy=True
            self._semantic_epoch += 1
            epoch=self._semantic_epoch
            self.status.set("Локальная Qwen определяет действие…")
            def semantic_worker():
                try:
                    intent=classify_local_intent(text, self.runtime)
                except Exception:
                    intent=None  # Fail closed; ordinary chat still works.
                if not self._shutdown.is_set():
                    self._semantic_queue.put((epoch,text,intent))
            threading.Thread(target=semantic_worker,daemon=True,
                             name="jarvis-local-intent").start()
            return
        return BaseJarvis.handle_text(self,text)

    def _complete_semantic_request(self, text, intent):
        """Called on the Tk thread only; never trust model-provided arguments."""
        self._semantic_busy=False
        if self._closing:
            return
        if intent is not None:
            self._dispatch_chat_first(intent,text)
        else:
            # No fabricated success: use the original chat/plan handling.
            BaseJarvis.handle_text(self,text)

    def pump(self):
        # BaseJarvis.pump owns the ordinary chat and OS-action queues; this
        # separate queue only carries inert, validated semantic classifications.
        if self._closing:
            return
        try:
            while True:
                epoch,text,intent=self._semantic_queue.get_nowait()
                if epoch == self._semantic_epoch:
                    self._complete_semantic_request(text,intent)
        except queue.Empty:
            pass
        return BaseJarvis.pump(self)

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
                self._last_screenshot_report=(
                    "Задача пользователя: " + question + "\n"
                    "Результат анализа изображения (может содержать ошибки): " + answer)[:2600]
                result = (True, answer + "\n\nДля подготовки исправления напиши "
                          "«исправь себя» или открой «Самоисправление» в меню ⚙.", "normal")
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
        # Active Windows startup vision permission covers user-requested
        # one-shot screenshots. Never capture automatically at startup.
        if not self.vision_allowed and not messagebox.askyesno(
            "Разрешение на экран",
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
        # Reply only through the visible transcript and status line.

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
        self._model_scan_cancel.set()
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
