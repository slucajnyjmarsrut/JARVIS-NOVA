# -*- coding: utf-8 -*-
"""JARVIS NOVA Python Agent — one-window desktop assistant."""
import os, queue, sys, threading, time, math, re, tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from agent_core import Plan, parse_local, validate_plan, ask_ai_for_plan
from desktop import Desktop, AppSuggestion
from speaker import Speaker
from self_improve import LearningStore, safe_name
from self_repair import repair_configs, inspect_configs
from auto_update import installed_application, check_and_download, stage_helper
from trimodal_service import TrimodalService
from work_modes import ModeManager, ModeCommand, MODES, VIDEO_STAGES
from game_catalog import GameCatalog
from voice_engine import Voice as RC4Voice
from local_chat import LocalChat
from nova_compact_ui import build_interface, compact_geometry
from nova_window_state import load_layout, save_layout, safe_window_geometry
from nova_overlay import NovaOverlay, dock_geometry
from overlay_commands import overlay_intent, preview_line
from whisper_mode import normalize_style

class Jarvis(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS NOVA")
        self._ui_layout=load_layout()
        default=compact_geometry(self.winfo_screenwidth(),self.winfo_screenheight())
        initial_geometry=safe_window_geometry(
            self._ui_layout.get("main"),default,
            self.winfo_screenwidth(),self.winfo_screenheight())
        self.geometry(initial_geometry)
        self.minsize(min(385,self.winfo_screenwidth()),
                     min(600,self.winfo_screenheight()))
        self._last_normal_geometry=initial_geometry
        self.configure(bg="#070D17")
        # Keep Windows' real minimize/maximize/close buttons, but request
        # a dark native titlebar so it doesn't clash with NOVA's dark HUD.
        self.after(60,self._set_native_dark_titlebar)
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.q=queue.Queue()
        self.voice_enabled=False
        self._answer_style="normal"
        # The user asked for a conversational mini-panel; text can still
        # be hidden instantly with its dedicated privacy toggle.
        self.overlay_show_text=True
        self.overlay_last_user=""
        self.overlay_last_answer=""
        self._closing=False
        self._shutdown=threading.Event()
        self.executing=False
        self.control_allowed=False
        self.vision_allowed=False
        self.engine="bundled"
        self.learning=LearningStore()
        self.modes=ModeManager()
        self.games=GameCatalog()
        self._focus_deadline=None
        self._focus_epoch=0
        self._pending_alias=None
        self._auto_update_busy=False
        self._auto_update_pending=None
        self._auto_update_first_seen=0.0
        self.speaker=Speaker()
        self.trimodal=TrimodalService()
        self.local_chat=LocalChat(self.trimodal.runtime)
        self.desktop=Desktop(lambda:self.control_allowed,lambda:self.vision_allowed,
                             learning=self.learning)
        self.voice=RC4Voice(lambda s:self.q.put(("heard",s)),
                            lambda s:self.q.put(("status",s)),
                            lambda:self.speaker.busy or self.trimodal.speaking,
                            on_vision_audio=lambda pcm,src:self.q.put(("vision_audio",(pcm,src))),
                            on_audio_level=lambda level:self.q.put(("audio_level",level)),
                            on_heard_styled=lambda text,style:self.q.put(("heard",(text,style))),
                            on_transcript=lambda text:self.q.put(("transcript",text)))
        build_interface(self)
        # Keep the assistant active when the main window is minimized/hidden.
        # The small overlay is another local Tk window, not a second app.
        self.overlay=NovaOverlay(self)
        # A withdrawn Toplevel may report 1x1 before its first Map event:
        # use a validated pure default instead of querying Tk's pending size.
        mini_default=dock_geometry(self.winfo_screenwidth(),self.winfo_screenheight())
        miniature=safe_window_geometry(
            self._ui_layout.get("mini"),mini_default,
            self.winfo_screenwidth(),self.winfo_screenheight(),fixed=True)
        if self._ui_layout.get("mini"):
            self.overlay.geometry(miniature)
            self.overlay._manual_position=True
        self.bind("<Configure>",self._remember_main_geometry,add="+")
        self.bind("<Unmap>",self._main_unmapped,add="+")
        self.bind("<Map>",self._main_mapped,add="+")
        self.bind("<Control-Shift-O>",lambda event:(self.toggle_overlay(),"break")[1])
        # Permissions, engine configuration and stop live in native menus,
        # not as an extra control panel on the main screen.
        menu=tk.Menu(self)
        permissions=tk.Menu(menu,tearoff=False)
        permissions.add_command(label="Разрешить управление компьютером",command=self.grant_control)
        permissions.add_command(label="Разрешить зрение для старых команд (только локально)",command=self.grant_vision)
        permissions.add_command(label="Отозвать все разрешения",command=self.revoke)
        menu.add_cascade(label="Разрешения",menu=permissions)
        vision_menu=tk.Menu(menu,tearoff=False)
        vision_menu.add_command(label="Спросить голосом об экране (Whisper → Vision → Silero)",
                                command=lambda:self.request_trimodal("screen"))
        menu.add_cascade(label="Зрение",menu=vision_menu)
        modes_menu=tk.Menu(menu,tearoff=False)
        self._selected_mode=tk.StringVar(value='neutral')
        for key,label in [('neutral','Обычный'),('gaming','Игры'),('work','Работа'),
                          ('office','Офис'),('study','Учёба')]:
            modes_menu.add_radiobutton(label=label,variable=self._selected_mode,value=key,
                command=lambda value=key:self.activate_mode(value))
        video_menu=tk.Menu(modes_menu,tearoff=False)
        for key,label in [('videos','Ролики — идея и аудитория'),('video_shoot','Ролики — съёмка'),
                          ('video_edit','Ролики — монтаж'),('video_review','Ролики — оценка')]:
            video_menu.add_radiobutton(label=label,variable=self._selected_mode,value=key,
                command=lambda value=key:self.activate_mode(value))
        modes_menu.add_cascade(label='Ролики',menu=video_menu)
        modes_menu.add_separator()
        modes_menu.add_command(label='Начать действие режима',command=self.start_mode_apps)
        modes_menu.add_command(label='Выбрать игру…',command=self.ask_game)
        modes_menu.add_command(label='Настроить приложения…',command=self.configure_mode_apps)
        modes_menu.add_command(label='Команды текущего режима',command=lambda:self.reply(self.modes.help()))
        modes_menu.add_command(label='Фокус-таймер 25 минут',command=lambda:self.handle_mode_command(
            ModeCommand('timer_start','Фокус-таймер на 25 минут.',minutes=25)))
        modes_menu.add_command(label='Остановить таймер',command=self.stop_focus_timer)
        menu.add_cascade(label='Режимы',menu=modes_menu)
        recognition_menu=tk.Menu(menu,tearoff=False)
        self._recognition_mode=tk.StringVar(value="balanced")
        for label,mode in (
            ("Сбалансировано · быстро, уточнять сложные слова", "balanced"),
            ("Точнее русский · Whisper small", "accurate"),
            ("Быстрее · Whisper base", "fast"),
        ):
            recognition_menu.add_radiobutton(
                label=label,variable=self._recognition_mode,value=mode,
                command=lambda selected=mode:self.voice.set_recognition_mode(selected))
        recognition_menu.add_separator()
        recognition_menu.add_command(label="Выбрать микрофон…",command=self.select_microphone)
        recognition_menu.add_command(label="Тест сигнала…",command=self.test_microphone)
        recognition_menu.add_command(label="Чувствительность голоса…",
                                     command=self.adjust_sensitivity)
        menu.add_cascade(label="Распознавание речи",menu=recognition_menu)
        ai=tk.Menu(menu,tearoff=False)
        for title,choice in [("Свободный разговор (встроенная Qwen, офлайн)","bundled"),
                             ("Только офлайн-команды","none"),("Внешняя Ollama","ollama"),
                             ("OpenAI API (нужен ключ)","openai"),
                             ("Claude API (нужен ключ)","anthropic")]:
            ai.add_command(label=title,command=lambda v=choice:self.set_engine(v))
        menu.add_cascade(label="AI",menu=ai)
        interface_menu=tk.Menu(menu,tearoff=False)
        interface_menu.add_checkbutton(label="Анимация ядра NOVA",variable=self.hud_animate)
        interface_menu.add_command(label="Свернуть → мини-диалог справа (Ctrl+Shift+O)",
                                   command=self.hide_main)
        interface_menu.add_command(label="Вернуть главное окно",command=self.show_main)
        interface_menu.add_command(label="Размер компактной панели по умолчанию",
                                   command=self.reset_compact_geometry)
        menu.add_cascade(label="Интерфейс",menu=interface_menu)
        learning_menu=tk.Menu(menu,tearoff=False)
        learning_menu.add_command(label="Научить названию программы…",command=self.teach_alias)
        learning_menu.add_command(label="Показать результаты обучения",command=self.learning_report)
        learning_menu.add_command(label="Удалить выученное название…",command=self.remove_alias)
        learning_menu.add_command(label="Сбросить обучение",command=self.reset_learning)
        learning_menu.add_command(label="Проверить офлайн-модели",command=self.check_models)
        learning_menu.add_separator()
        learning_menu.add_command(label="Самовосстановление: проверить и исправить настройки…",
                                  command=self.self_repair_now)
        menu.add_cascade(label="Самоулучшение",menu=learning_menu)
        menu.add_command(label="Возможности JARVIS NOVA",command=self.show_capabilities)
        menu.add_command(label="Стоп/Выключить микрофон",command=self.toggle_voice)
        # The native Tk menu bar is bright on Windows and duplicates the
        # LEFT control rail. Keep every command in a pop-up from the sidebar.
        self.nova_settings_menu=menu
        if hasattr(self,"hud_settings_button"):
            self.hud_settings_button.configure(command=self.show_settings_menu)
        self.bind("<F10>",lambda event:self.show_settings_menu())
        self.log("Система","Управление голосом: «Джарвис, открой Chrome». F9 — ручная активация.")
        self.after(100,self.pump)
        # No update check on developer Python runs. For installed EXEs,
        # read-only network discovery begins after startup, off the UI thread.
        self.after(20000,self._check_auto_update)
        threading.Thread(target=self.init_voice,daemon=True).start()

    def _set_native_dark_titlebar(self):
        """Windows 10/11: dark caption and native controls; safe fallback."""
        try:
            import ctypes
            if __import__("sys").platform!="win32" or not self.winfo_exists():
                return
            handle=ctypes.windll.user32.GetParent(self.winfo_id())
            flag=ctypes.c_int(1)
            dwm=ctypes.windll.dwmapi.DwmSetWindowAttribute
            if dwm(handle,20,ctypes.byref(flag),ctypes.sizeof(flag))!=0:
                dwm(handle,19,ctypes.byref(flag),ctypes.sizeof(flag))
        except (OSError,AttributeError,ValueError):
            pass  # older Windows builds keep normal titlebar

    def show_settings_menu(self,event=None):
        """All formerly top-bar menus stay available from the LEFT rail."""
        menu=getattr(self,"nova_settings_menu",None)
        if menu is None:
            return
        try:
            if hasattr(self,"hud_settings_button"):
                widget=self.hud_settings_button
                x=widget.winfo_rootx()+8
                y=widget.winfo_rooty()+widget.winfo_height()
            else:
                x=self.winfo_rootx()+28
                y=self.winfo_rooty()+60
            menu.tk_popup(x,y)
        finally:
            menu.grab_release()

    def _remember_main_geometry(self,event):
        if (event.widget is self and not self._closing and
                self.state()=="normal"):
            self._last_normal_geometry=self.geometry()

    def reset_compact_geometry(self):
        default=compact_geometry(self.winfo_screenwidth(),self.winfo_screenheight())
        self.geometry(default)
        self._last_normal_geometry=default

    def save_window_layout(self):
        """Only positions/sizes; never store conversation or mic audio."""
        overlay=getattr(self,"overlay",None)
        mini=overlay.geometry() if overlay is not None and overlay.winfo_exists() else None
        main=(self.geometry() if self.state()=="normal"
              else getattr(self,"_last_normal_geometry",None))
        return save_layout(main,mini)

    def _main_unmapped(self,event):
        """Tk also sends Unmap for child widgets: ignore those events."""
        if event.widget is self and not self._closing:
            # Wait until Windows/Tk has applied iconify/withdraw.
            self.after(50,self._show_overlay_if_hidden)

    def _show_overlay_if_hidden(self):
        if self._closing:return
        if self.state() in {"iconic","withdrawn"}:
            self.overlay.show()

    def _main_mapped(self,event):
        if event.widget is self and not self._closing and self.state()=="normal":
            self.overlay.hide()

    def hide_main(self):
        if self._closing:return
        if self.state()=="normal":
            self._last_normal_geometry=self.geometry()
        self.save_window_layout()
        self.withdraw()
        self.overlay.show()

    def show_main(self):
        if self._closing:return
        self.overlay.hide()
        self.deiconify()
        self.lift()
        self.focus_force()

    def toggle_overlay(self):
        if self._closing:return
        if self.state()=="normal":
            self.hide_main()
        else:
            self.show_main()

    def show_capabilities(self):
        messagebox.showinfo("Что умеет JARVIS NOVA",
            "Голосовые команды: «Джарвис, открой блокнот» (микрофон должен быть включён).\n\n"
            "Свободный разговор: локальная Qwen включена по умолчанию, без интернета.\n"
            "Анализ экрана: кнопка «ЭКРАН» — каждый раз спрашивает разрешение.\n"
            "Видео: кнопка «РОЛИКИ» — сначала CSV статистики канала, потом сценарий и монтаж.\n"
            "Режимы: Игры, Работа, Офис, Учёба и этапы роликов в верхнем меню.\n\n"
            "Whisper: распознавание речи; Vision: ответы о кадре; Silero: синтез речи. "
            "Все модели проверены автоматически, но качество микрофона зависит от устройства.",
            parent=self)

    def log(self,person,message):
        self.history.configure(state="normal")
        tag=person if person in {"JARVIS","Вы","Система","Whisper","Профиль"} else "error" if "ошиб" in person.casefold() else "Система"
        self.history.insert("end",f"{person}: ",tag)
        self.history.insert("end",f"{message}\n\n")
        self.history.see("end")
        self.history.configure(state="disabled")
        if getattr(self,"overlay_show_text",False):
            if person=="Вы":
                self.overlay_last_user=preview_line("Вы",message)
            elif person=="JARVIS":
                self.overlay_last_answer=preview_line("NOVA",message)

    def set_overlay_preview(self, enabled):
        """Only show new dialogue while preview is explicitly enabled."""
        self.overlay_show_text=bool(enabled)
        if not self.overlay_show_text:
            self.overlay_last_user=""
            self.overlay_last_answer=""

    def init_voice(self):
        # Microphone starts independently of slow PyTorch/Silero loading.
        if self._shutdown.is_set():
            return
        self.voice.start()
        if self._shutdown.is_set():
            self.voice.stop()
            return
        self.voice_enabled=True
        self.q.put(("status","Микрофон запускается · жду «Джарвис»"))
        message=self.speaker.load()
        if not self._shutdown.is_set():
            self.q.put(("status",message))

    def f9(self,event=None):
        if self.voice_enabled:
            self.voice.activate()
            self.mic_state.set("Микрофон: жду команду (8 секунд)" if getattr(self.voice,"mic_ready",False)
                               else "Микрофон: подключается — F9 ожидает устройство…")
        else:
            self.status.set("Сначала включи микрофон кнопкой выше")
        return "break"

    def toggle_voice(self):
        if self._closing:return
        if self.voice_enabled:
            self.voice.stop();self.voice_enabled=False
            self.status.set("Микрофон выключен")
            self.mic_state.set("Микрофон: выключен")
            self.hud_level_value=0.0
            self.hud_level_at=0.0
        else:
            self.voice.start();self.voice_enabled=True
            self.status.set("Включаю микрофон…")
            self.mic_state.set("Микрофон: подключается…")

    def adjust_sensitivity(self):
        """Keep advanced microphone gain reachable from compact UI's F10."""
        if self._closing:return
        current=float(getattr(self.voice,"sensitivity",1.2))
        level=simpledialog.askfloat(
            "Голос JARVIS", "Чувствительность (0.75–2.0):",
            initialvalue=current,minvalue=.75,maxvalue=2.0,parent=self)
        if level is not None:
            self.voice.set_sensitivity(level)
            self.status.set(f"Чувствительность микрофона: {level:.2f}×")

    def select_microphone(self):
        """Allow Windows users to choose the actual input, not only OS default."""
        if self._closing:return
        if self.voice.running:
            messagebox.showinfo("Микрофон", "Сначала выключи микрофон кнопкой в главном окне.", parent=self)
            return
        try:
            import sounddevice as sd
            choices=[(index,device) for index,device in enumerate(sd.query_devices())
                     if device.get("max_input_channels",0)>0]
        except Exception as exc:
            messagebox.showerror("Микрофон", "Не могу получить устройства: "+str(exc)[:140],parent=self)
            return
        if not choices:
            messagebox.showerror("Микрофон", "Windows не показывает входных устройств.",parent=self)
            return
        labels=["0. Системный микрофон по умолчанию"]
        for index,(device_id,info) in enumerate(choices,1):
            labels.append(f"{index}. {info['name']} ({round(info['default_samplerate'])} Гц)")
        selected=simpledialog.askinteger("Выбрать микрофон",
            "Выбери номер устройства (не системный индекс):\n"+
            "\n".join(labels[:35])+
            ("\nПоказаны первые 34 устройства." if len(labels)>35 else ""),
            parent=self,minvalue=0,maxvalue=min(len(choices),34))
        if selected is None:return
        device=None if selected==0 else choices[selected-1][0]
        try:
            self.voice.set_input_device(device)
        except (ValueError,RuntimeError) as exc:
            messagebox.showerror("Микрофон",str(exc),parent=self)
            return
        self.mic_state.set("Микрофон: выбран, включи кнопкой")
        self.status.set("Выбрано: "+labels[selected][:140])

    def test_microphone(self):
        """Two-second signal-level diagnostic. Never persists microphone recordings."""
        if self._closing:return
        if self.voice.running:
            messagebox.showinfo("Проверка", "Сначала выключи основной микрофон, затем повтори тест.",parent=self)
            return
        self.status.set("Проверка 2 секунды: говори обычным и тихим голосом…")
        device=self.voice.input_device
        def worker():
            try:
                import numpy as np
                import sounddevice as sd
                info=sd.query_devices(device,kind="input")
                rate=int(round(info["default_samplerate"]))
                if not 8000<=rate<=192000:raise ValueError("Неверная частота устройства")
                data=sd.rec(int(rate*2),samplerate=rate,channels=1,dtype="float32",
                            device=device,blocking=True)
                signal=np.asarray(data).reshape(-1)
                rms=float(np.sqrt(np.mean(signal.astype(np.float64)**2)))
                peak=float(np.max(np.abs(signal))) if signal.size else 0.0
                self.q.put(("mic_level",(True,rms,peak,rate)))
            except Exception as exc:
                self.q.put(("mic_level",(False,str(exc)[:180],0.0,0)))
        threading.Thread(target=worker,daemon=True,name="jarvis-mic-diagnostic").start()

    def grant_control(self):
        if messagebox.askyesno("Разрешение","Разрешить JARVIS управлять мышью, клавиатурой и окнами до закрытия приложения?"):
            self.control_allowed=True
            self.status.set("Управление разрешено до закрытия JARVIS")

    def grant_vision(self):
        if messagebox.askyesno("Разрешение","Разрешить захватывать текущий экран в оперативную память и отправлять кадры только в локальную Ollama?"):
            self.vision_allowed=True
            self.status.set("Локальное зрение разрешено до закрытия JARVIS")

    def revoke(self):
        self.control_allowed=False;self.vision_allowed=False
        self.status.set("Все разрешения отозваны")

    def teach_alias(self):
        spoken=simpledialog.askstring("Обучение JARVIS", "Как ты называешь программу голосом?",parent=self)
        if spoken is None:return
        if not safe_name(spoken):
            messagebox.showerror("Ошибка", "Название содержит недопустимые символы.",parent=self)
            return
        official=simpledialog.askstring("Обучение JARVIS",
            "Какое ТОЧНОЕ имя этой программы в меню Пуск?\nНапример: Google Chrome",parent=self)
        if official is None:return
        if not self.desktop.is_installed(official):
            messagebox.showwarning("Программа не найдена",
                "В меню Пуск нет программы с таким точным названием. Обучение отменено.",parent=self)
            return
        if not messagebox.askyesno("Подтверждение",
            f"Запомнить, что «{spoken}» означает «{official}»?",parent=self):
            return
        try:
            self.learning.learn(spoken,official,verified=True)
            self.log("JARVIS",f"Запомнил: «{spoken}» → «{official}».")
        except Exception as exc:
            messagebox.showerror("Ошибка обучения",str(exc),parent=self)

    def remove_alias(self):
        spoken=simpledialog.askstring("Забыть название", "Какое выученное название удалить?",parent=self)
        if spoken is not None:
            if self.learning.unlearn(spoken):
                self.log("JARVIS","Выученное название удалено.")
            else:
                self.log("JARVIS","Такого выученного названия нет.")

    def learning_report(self):
        messagebox.showinfo("Самоулучшение JARVIS",self.learning.summary(),parent=self)

    def reset_learning(self):
        if messagebox.askyesno("Сброс обучения",
            "Удалить все выученные названия и счётчики ошибок?",parent=self):
            self.learning.reset()
            self.log("JARVIS","Локальное обучение сброшено.")

    def check_models(self):
        from speaker import assets
        root=assets()
        models={"Vosk":root/"vosk"/"am"/"final.mdl",
                "Whisper":root/"base.pt","Silero":root/"v5_ru.pt"}
        lines=[f"{name}: {'файлы найдены' if path.is_file() else 'не встроен'}"
               for name,path in models.items()]
        from bundled_vision_runtime import validate_offline_model_store
        try:
            validate_offline_model_store(root.parent)
            if not (root.parent/"ollama"/"ollama.exe").is_file():
                raise FileNotFoundError("нет переносимого ollama.exe")
            lines.append("Vision: локальные файлы найдены (инференс не проверен)")
        except Exception as exc:
            lines.append("Vision: автономная модель/движок отсутствует ("+str(exc)[:80]+")")
        lines.append("Это проверка файлов, а не реальный запуск нейросетей.")
        messagebox.showinfo("Проверка движков","\n".join(lines),parent=self)

    def open_viral_studio(self,stage="audience"):
        """One in-app window for trend research, a shot list and local video editing."""
        if self._closing:return
        from viral_studio_ui import ViralStudioWindow
        previous=getattr(self,'_viral_window',None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            previous.focus_stage(stage)
            return previous
        self._viral_window=ViralStudioWindow(self,speaker=self.speaker)
        self._viral_window.focus_stage(stage)
        return self._viral_window

    def activate_mode(self,key):
        if key not in MODES and key!='neutral':
            return
        command=self.modes.set_mode(key)
        self.handle_mode_command(command)
        if key=='gaming':
            # Menu users get a native picker; voice users can answer the spoken question.
            self.after(50,self.ask_game)

    def ask_game(self):
        if self._closing:return
        if self.modes.mode!='gaming':
            self.reply('Сначала включи игровой режим.');return
        known=tuple(g for g in self.games.available(()) if g.source=='steam')
        examples=', '.join(g.label for g in known[:8]) or 'укажи игру по названию'
        chosen=simpledialog.askstring('Игровой режим',
            'В какую игру хочешь поиграть?\n'
            'Назови игру из меню Пуск или локальной библиотеки Steam.\n'
            'Примеры найденного: '+examples[:260],
            parent=self)
        if chosen is not None:
            self.handle_mode_command(self.modes.choose_game(chosen))

    def _launch_selected_game(self,name):
        choice=self.games.find(name,self.desktop.installed_names())
        if choice is None:
            self.modes.awaiting_game=True
            self.reply('Не нашёл такую установленную игру. Назови точное название из меню Пуск или библиотеки Steam.')
            return
        if choice.source=='start_menu':
            from agent_core import Plan, Step
            self.execute_plan(Plan(steps=[Step('open_app',choice.target)],
                                   need_confirmation=True,source='game'))
            return
        if not messagebox.askyesno('Подтвердить запуск игры',
            f'Запустить «{choice.label}» через локальный Steam?\nНикакие команды shell не выполняются.',parent=self):
            self.reply('Запуск игры отменён.');return
        if self.executing:
            self.reply('Другое действие ещё выполняется.');return
        self.executing=True
        def worker():
            try:
                # Revalidate immediately before opening the Steam URI.
                if not self.games.validate_steam(choice):
                    raise FileNotFoundError('Игра отсутствует в проверенной Steam-библиотеке')
                os.startfile('steam://rungameid/'+choice.target)
                result=(True,'Запускаю '+choice.label,('steam_game',))
            except Exception as exc:
                result=(False,'Не удалось запустить игру: '+str(exc)[:160],('steam_game',))
            self.q.put(('action_result',result))
        threading.Thread(target=worker,daemon=True,name='jarvis-steam-launch').start()

    def configure_mode_apps(self):
        key=self.modes.mode
        if key=='neutral' or key=='gaming' or key in VIDEO_STAGES:
            messagebox.showinfo('Режимы','Настройка пакетов программ доступна в режимах Работа, Офис и Учёба. Для игр выбери игру, для роликов используй Видео-студию.',parent=self)
            return
        existing=', '.join(self.modes.apps(key))
        answer=simpledialog.askstring('Приложения режима '+MODES[key].label,
              'Введи до трёх ТОЧНЫХ названий из меню Пуск через запятую.\n'
              'Команды и пути к EXE запрещены.\n'
              'Перед записью JARVIS проверит все программы.',
              initialvalue=existing,parent=self)
        if answer is None:return
        items=[x.strip() for x in answer.split(',')]
        try:
            if not messagebox.askyesno('Проверка запуска',
                'Разрешить сохранить в этом режиме следующие программы?\n'+
                '\n'.join(items)+'\nОни будут запускаться только по команде с подтверждением.',parent=self):
                return
            self.modes.configure(key,items,self.desktop.is_installed)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Недопустимые приложения',str(exc),parent=self)
            return
        self.reply('Приложения режима сохранены. Ничего не запускаю без команды.')

    def start_mode_apps(self):
        if self.modes.mode=='neutral':
            self.reply('Выбери один из режимов в меню.');return
        if self.modes.mode=='gaming':
            self.handle_mode_command(self.modes.parse('начни сессию',self.desktop.is_installed))
            return
        if self.modes.mode in VIDEO_STAGES:
            self.open_viral_studio(VIDEO_STAGES[self.modes.mode])
            return
        self.handle_mode_command(self.modes.build_launch(self.modes.mode,self.desktop.is_installed))

    def _focus_tick(self,epoch):
        if self._closing or epoch!=self._focus_epoch or self._focus_deadline is None:
            return
        remaining=self._focus_deadline-time.monotonic()
        if remaining<=0:
            self._focus_deadline=None
            self.reply('Фокус-сессия завершилась. Сделай перерыв.')
            return
        self.after(min(1000,max(100,int(remaining*1000))),lambda:self._focus_tick(epoch))

    def start_focus_timer(self,minutes:int):
        if self.modes.mode not in {'work','office','study'}:
            self.reply('Фокус-таймер доступен в режимах Работа, Офис, Учёба.')
            return
        if not isinstance(minutes,int) or not 1<=minutes<=120:
            self.reply('Фокус-таймер должен быть от 1 до 120 минут.')
            return
        if self._focus_deadline and self._focus_deadline>time.monotonic():
            if not messagebox.askyesno('Фокус-таймер','Заменить уже работающий таймер?',parent=self):return
        self._focus_epoch+=1
        self._focus_deadline=time.monotonic()+60*minutes
        epoch=self._focus_epoch
        self.after(1000,lambda:self._focus_tick(epoch))
        self.reply(f'Начинаю фокус-сессию на {minutes} минут.')

    def stop_focus_timer(self):
        self._focus_epoch+=1
        if self._focus_deadline is not None:
            self._focus_deadline=None
            self.reply('Фокус-таймер остановлен.')
        else:self.reply('Фокус-таймер не запущен.')

    def focus_status(self):
        if self._focus_deadline is None:return 'Сейчас нет активного таймера.'
        remaining=max(0,math.ceil(self._focus_deadline-time.monotonic()))
        if remaining==0:return 'Фокус-сессия завершилась.'
        return f'Осталось {remaining//60} минут {remaining%60} секунд.'

    def handle_mode_command(self,command:ModeCommand):
        if command is None:return
        if command.kind in {'switch','game_prompt','video_stage'}:
            self._selected_mode.set(command.mode)
            self.reply(command.message)
            if command.kind=='video_stage':
                studio=self.open_viral_studio(stage=command.stage)
                if command.action and studio is not None:
                    operations={
                        'audience':'import_audience',
                        'script':'generate',
                        'shoot':'read_shots',
                        'edit':'montage',
                        'review':'review',
                    }
                    name=operations.get(command.action)
                    if name:
                        self.after(40,getattr(studio,name))
        elif command.kind=='game_launch':
            self._launch_selected_game(command.game)
        elif command.kind=='launch':
            self.log('Профиль',command.message)
            self.execute_plan(command.plan)
        elif command.kind=='timer_start':
            self.start_focus_timer(command.minutes)
        elif command.kind=='timer_status':
            self.reply(self.focus_status())
        elif command.kind=='timer_stop':
            self.stop_focus_timer()
        else:self.reply(command.message)

    def set_engine(self,engine):
        self.engine=engine
        self.status.set({"bundled":"Разговор: встроенная Qwen (без интернета)",
                         "none":"Только команды","ollama":"AI: внешняя Ollama",
                         "openai":"AI: OpenAI API (ключ из окружения)",
                         "anthropic":"AI: Claude API (ключ из окружения)"}[engine])

    def enter(self,event=None):
        s=self.entry.get().strip()
        self.entry.delete(0,"end")
        if s:
            self._answer_style="normal"  # typed requests do not inherit voice volume
            self.handle_text(s)

    def _check_auto_update(self):
        """Unattended stable-release detection; no internet on developer runs."""
        if self._closing or self._auto_update_busy or self._auto_update_pending:
            return
        installed=installed_application()
        if installed is None:
            return
        self._auto_update_busy=True
        def worker():
            try:
                result=check_and_download(cancel=self._shutdown)
                if result is not None and not self._shutdown.is_set():
                    self.q.put(("update_ready",result))
            except Exception as exc:
                # Only error *class* is displayed. No arbitrary remote payload,
                # URL, token, user footage or local paths are logged.
                if not self._shutdown.is_set():
                    self.q.put(("update_error",type(exc).__name__))
            finally:
                self.q.put(("update_check_done",None))
        threading.Thread(target=worker,daemon=True,name="jarvis-update-check").start()

    def _finish_auto_update(self):
        if self._closing or not self._auto_update_pending:
            return
        release,installer=self._auto_update_pending
        studio=getattr(self,"_viral_window",None)
        # Do not discard an unsent typed message when applying an update.
        input_widget=getattr(self,"entry",None)
        unsent=bool(input_widget is not None and input_widget.get().strip())
        busy=(self.executing or getattr(studio,"running",False) or
              self.speaker.busy or self.trimodal.speaking or
              getattr(self.voice,"whisper_busy",False) or unsent)
        # Never interrupt an active video export or spoken answer. When idle,
        # the local helper takes over and restarts the installed app.
        if busy or time.monotonic()-self._auto_update_first_seen<12:
            self.after(6000,self._finish_auto_update)
            return
        installed=installed_application()
        if installed is None:
            self._auto_update_pending=None
            return
        try:
            stage_helper(release,installer,installed,installer.parent)
        except Exception as exc:
            self.status.set("Обновление отложено: "+type(exc).__name__)
            self._auto_update_pending=None
            return
        self.status.set("Устанавливаю проверенное обновление, JARVIS перезапустится.")
        self.close()

    def self_repair_now(self):
        """Safely repair ONLY local settings after asking the user.

        Full source changes or installing software are deliberately excluded.
        """
        findings=inspect_configs()
        problems=[f for f in findings if f.status in ("corrupt","too_large")]
        manual=[f for f in findings if f.status in ("unsafe","unsupported")]
        if not problems:
            if manual:
                names=", ".join(f.name for f in manual)
                self.reply("Самодиагностика обнаружила настройки, требующие ручной "
                           "проверки: "+names+". Файлы не изменены.")
            else:
                self.reply("Самодиагностика: повреждённых настроек не найдено. "
                           "Исправление программного кода выполняется отдельно, через тесты.")
            return
        names=", ".join(item.name for item in problems)
        if not messagebox.askyesno(
            "Самовосстановление JARVIS",
            "Обнаружены повреждённые локальные настройки: "+names+
            "\n\nСделать резервную копию каждого файла и создать чистые настройки? "
            "Личные файлы, видео, модели и исходный код не затрагиваются.",
            parent=self):
            self.reply("Самовосстановление отменено. Оригиналы не изменены.")
            return
        report=repair_configs(consent=True)
        # Reload only after successful on-disk verification. Previously learned
        # application aliases and profiles are preserved in .bak backups.
        if report.repaired:
            self.learning=LearningStore()
            self.desktop.learning=self.learning
            self.modes=ModeManager()
        self.reply(report.say())

    def handle_text(self,text):
        if self._closing:return
        self.log("Вы",text)
        if text.casefold().strip(" .!?,") in {
            "проверь и исправь ошибки", "джарвис проверь и исправь ошибки",
            "самовосстановление", "исправь ошибки джарвис"}:
            self.self_repair_now()
            return
        # These are exact, local window controls, not desktop automation.
        # A conversational mention of the overlay is never interpreted as one.
        overlay_action=overlay_intent(text)
        if overlay_action=="show":
            self.show_main()
            self.reply("Главное окно JARVIS открыто.")
            return
        if overlay_action=="hide":
            self.hide_main()
            self.reply("Мини-панель разговора справа. Нажми «РАЗВЕРНУТЬ», чтобы вернуться.")
            return
        mode_command=self.modes.parse(text,self.desktop.is_installed)
        if mode_command is not None:
            self.handle_mode_command(mode_command)
            return
        # Voice/text can open the fully automatic studio, but must never
        # silently grant network/media download permission.
        auto_request=re.fullmatch(
            r'(?:джарвис[,!]?\s+)?(?:сделай|создай|смонтируй)\s+'
            r'(?:мне\s+)?(?:качественный\s+)?(?:ролик|видео)\s+'
            r'(?:сам\s+)?(?:про|об)\s+(.{2,100})',
            text.strip(),flags=re.I)
        auto_short=text.casefold().strip(' .!?,') in {
            'сделай ролик сам','создай ролик автоматически',
            'автомонтаж','автоматический монтаж'}
        if auto_request or auto_short:
            window=self.open_viral_studio('auto')
            if auto_request and window is not None:
                window.topic.set(auto_request.group(1).strip(' .!?,'))
            self.status.set('Автомонтаж: проверь тему и дай отдельное разрешение на интернет.')
            return
        if any(token in text.casefold() for token in (
            'смонтируй ролик', 'вирусный ролик', 'вирусное видео',
            'сценарий для рилс', 'сценарий для шортс', 'снять тикток')):
            self.open_viral_studio('audience')
            self.status.set('Видео-студия: сначала анализ аудитории; интернет только с разрешения.')
            return
        # A webcam cannot be opened by JARVIS, including via legacy voice
        # phrases which would otherwise fall through to desktop app launching.
        normalized=text.casefold().replace("ё","е")
        if (re.search(r"(?:камер|вебкамер|webcam|camera)",normalized) and
                re.search(r"(?:включи|открой|покажи|посмотри|сними|сфотографируй|что перед|опиши)",normalized)):
            self.reply("Веб-камера полностью удалена из JARVIS. Можно анализировать только экран.")
            return
        source=self.voice.vision_source(text)
        if source:
            # A typed vision request starts one five-second spoken Whisper question.
            # Wake-word audio uses the same original PCM via on_vision_audio.
            self.request_trimodal(source)
            return
        if text.casefold().strip() in {"стоп","отмена","прекрати"}:
            self.status.set("Остановлено")
            return
        local=parse_local(text)
        if self.engine=="none" or local.steps or local.answer or text.casefold().strip() in {"открой","запусти","включи"}:
            self.execute_plan(local)
        elif self.engine=="bundled":
            if self.executing:
                self.reply("Подожди, пока я закончу предыдущий запрос.")
                return
            self.executing=True
            request_style=normalize_style(getattr(self,"_answer_style","normal"))
            self._answer_style="normal"
            self.status.set("Думаю локально — первый ответ может занять время…")
            def chat_worker():
                try:
                    result=(True,self.local_chat.ask(text))
                except Exception as exc:
                    result=(False,"Локальный разговор недоступен: "+str(exc)[:200])
                self.q.put(("chat_result",(*result,request_style)))
            threading.Thread(target=chat_worker,daemon=True,name="jarvis-local-chat").start()
        else:
            request_style=normalize_style(getattr(self,"_answer_style","normal"))
            self._answer_style="normal"
            self.status.set("Обдумываю запрос…")
            def worker():
                plan=ask_ai_for_plan(text,self.engine)
                self.q.put(("plan",(plan,request_style)))
            threading.Thread(target=worker,daemon=True).start()

    def request_trimodal(self, source: str, audio_pcm: bytes | None = None):
        if self._closing or self.executing:return
        if source!="screen":
            self.status.set("Веб-камера удалена. Доступен только анализ экрана.")
            return
        noun="экрана"
        if not messagebox.askyesno("Разрешение на изображение",
            f"Разрешить JARVIS захватить ОДИН кадр {noun} и обработать его локально? "
            "Изображение не будет отправлено в облако.",parent=self):
            self.status.set("Анализ изображения отменён")
            return
        self.executing=True
        self.status.set("Подготавливаю реальные Whisper, Vision и Silero…")
        def worker():
            restart=self.voice_enabled
            try:
                # Release microphone before Stage 2 opens it (PortAudio cannot
                # reliably host overlapping streams on Bluetooth headsets).
                if restart:self.voice.stop()
                self.trimodal.initialize()
                if self._shutdown.is_set():return
                if audio_pcm is None:
                    self.q.put(("status","Скажите вопрос вслух: запись 5 секунд…"))
                    samples=None
                else:
                    import numpy as np
                    samples=np.frombuffer(audio_pcm,dtype="<i2").astype(np.float32)/32768.0
                result=self.trimodal.run_once(
                    source="screen", screen_consent=True, seconds=5.0,
                    audio_samples=samples, sample_rate=16000)
                if not self._shutdown.is_set():
                    self.q.put(("trimodal_result",(True,result)))
            except Exception as exc:
                if not self._shutdown.is_set():
                    self.q.put(("trimodal_result",(False,f"{type(exc).__name__}: {exc}")))
            finally:
                if restart and not self._shutdown.is_set():
                    self.voice.start()
                if not self._shutdown.is_set():
                    self.q.put(("trimodal_complete",None))
        threading.Thread(target=worker,daemon=True,name="jarvis-trimodal").start()

    def execute_plan(self,plan):
        if self.executing:
            self.reply("Подожди, пока завершится предыдущая команда.")
            return
        try: plan=validate_plan(plan)
        except Exception as exc:
            self.reply("Команда отклонена: "+str(exc));return
        if plan.question:self.reply(plan.question);return
        if plan.answer:self.reply(plan.answer);return
        if not plan.steps:self.reply("Не понял, что требуется.");return
        if any(s.kind=="screen_describe" for s in plan.steps):
            if len(plan.steps)>1:
                self.reply("Анализ экрана выполняется отдельно от остальных действий.")
                return
            self.request_trimodal("screen")
            return
        if any(s.kind not in {"screen_describe","window_status","open_app","open_url"} for s in plan.steps):
            if not self.control_allowed:
                self.reply("Сначала разреши управление компьютером через меню «Разрешения».");return
        # AI plans always need human confirmation; risky deterministic commands too.
        # Preserve the intended target before the confirmation window steals focus.
        target=None
        if any(s.kind=="close_window" for s in plan.steps):
            try: target=self.desktop.active_window()
            except Exception as exc:
                self.reply("Не удалось определить окно: "+str(exc));return
        if plan.need_confirmation:
            actions=", ".join(s.kind+(" "+s.value[:45] if s.value else "") for s in plan.steps)
            if not messagebox.askyesno("Подтвердить действие",
                                        "JARVIS собирается выполнить:\n"+actions+"\n\nПродолжить?"):
                self.reply("Действие отменено.");return
        request_style=normalize_style(getattr(self,"_answer_style","normal"))
        self._answer_style="normal"
        self.executing=True
        self.status.set("Выполняю команду…")
        def worker():
            self.desktop._active_override=target
            try:
                results=[]
                for step in plan.steps:
                    results.append(self.desktop.run(step))
                self.q.put(("action_result", (True,". ".join(results),
                                                tuple(x.kind for x in plan.steps),request_style)))
            except AppSuggestion as suggestion:
                self.q.put(("app_suggestion", (suggestion.spoken,suggestion.installed)))
            except Exception as exc:
                self.q.put(("action_result", (False,"Не получилось: "+str(exc)[:250],
                                                tuple(x.kind for x in plan.steps),request_style)))
            finally:
                self.desktop._active_override=None
        threading.Thread(target=worker,daemon=True,name="jarvis-action").start()

    def reply(self,s):
        if self._closing:return
        self.log("JARVIS",s)
        self.status.set(s[:100])
        # Capture now; another voice message must not change this reply's
        # loudness after the TTS thread starts.
        delivery_style=normalize_style(getattr(self,"_answer_style","normal"))
        self._current_playback_style=delivery_style
        self._answer_style="normal"  # never leak a quiet voice into a later GUI action
        def speak_and_rearm():
            spoken=self.speaker.say(s,style=delivery_style)
            if spoken is False and not self._shutdown.is_set():
                self.q.put(("tts_error",getattr(self.speaker,"last_error","Ошибка TTS")))
            # The follow-up window starts AFTER speech playback, not before.
            # The mic deliberately ignores its own TTS echo while Speaker.busy.
            if (spoken is not False and not self._shutdown.is_set()
                    and self.voice_enabled and self.engine=="bundled" and not self._closing):
                self.voice.activate()
        threading.Thread(target=speak_and_rearm,daemon=True,name="jarvis-speak-rearm").start()

    def pump(self):
        if self._closing:return
        try:
            while True:
                op,val=self.q.get_nowait()
                if op=="heard":
                    if isinstance(val,tuple) and len(val)==2:
                        sentence,voice_style=val
                        self._answer_style=normalize_style(voice_style)
                        self.handle_text(sentence)
                    else:
                        self._answer_style="normal"
                        self.handle_text(val)
                elif op=="vision_audio":
                    pcm,src=val
                    self.request_trimodal(src,audio_pcm=pcm)
                elif op=="trimodal_result":
                    success,result=val
                    if success:
                        if result.transcript:self.log("Whisper",result.transcript)
                        self.log("JARVIS",result.answer or "Whisper не обнаружил речи")
                        self.status.set("Трёхмодельный цикл завершён" if result.answer else "Речь не обнаружена")
                    else:
                        self.log("Ошибка трёхмодельного цикла",result)
                        self.status.set("Ошибка Whisper/Vision/Silero — подробности в журнале")
                elif op=="update_ready":
                    self._auto_update_pending=val
                    self._auto_update_first_seen=time.monotonic()
                    self.status.set("Проверенное обновление загружено. Автоматическая установка при простое.")
                    self.after(3000,self._finish_auto_update)
                elif op=="update_error":
                    self.status.set("Не удалось проверить обновления: "+str(val)[:60])
                elif op=="update_check_done":
                    self._auto_update_busy=False
                    # Check again periodically while JARVIS remains open.
                    self.after(12*60*60*1000,self._check_auto_update)
                elif op=="trimodal_complete":
                    self.executing=False
                elif op=="chat_result":
                    self.executing=False
                    success,answer=val[:2]
                    if len(val)>=3:
                        self._answer_style=normalize_style(val[2])
                    if success:self.reply(answer)
                    else:self.reply(answer+" Проверь установку моделей.")
                elif op=="tts_error":
                    self.status.set("Ошибка озвучивания: "+str(val)[:140])
                elif op=="transcript":
                    if self.voice_enabled and not self._closing:
                        self.hud_transcript.set("РАСПОЗНАНО: "+str(val)[:155])
                elif op=="status":
                    # Do not allow a queued event from an old mic worker to
                    # incorrectly display an active microphone after Stop.
                    if "микрофон" in val.casefold() or "Vosk" in val or "Whisper" in val:
                        if not self.voice_enabled:continue
                        if val.startswith("Ошибка микрофона:"):
                            self.mic_state.set("Микрофон: ошибка устройства")
                            self.voice_enabled=False
                        elif val.startswith("Vosk готов"):
                            self.mic_state.set("Микрофон: включён, жду «Джарвис»")
                        elif val.startswith("Микрофон: переподключение"):
                            self.mic_state.set("Микрофон: переподключается…")
                            self.hud_level_value=0.0
                            self.hud_level_at=0.0
                    self.status.set(val)
                elif op=="audio_level":
                    if self.voice_enabled:
                        self.hud_level_value=max(0.0,min(1.0,float(val)))
                        self.hud_level_at=time.monotonic()
                elif op=="mic_level":
                    success,rms,peak,rate=val
                    if success:
                        self.status.set(
                            f"Тест микрофона: RMS {rms:.4f}, пик {peak:.3f}, {rate} Гц. "
                            +("Очень тихий сигнал: проверь усиление в Windows." if rms<0.002
                              else "Сигнал обнаружен; это не проверка точности Whisper."))
                    else:
                        self.status.set("Не могу проверить микрофон: "+rms)
                elif op=="plan":
                    if isinstance(val,tuple) and len(val)==2:
                        plan,requested_style=val
                        self._answer_style=normalize_style(requested_style)
                        self.execute_plan(plan)
                    else:
                        self.execute_plan(val)
                elif op=="action_result":
                    self.executing=False
                    success,text,kinds=val[:3]
                    if len(val)>=4:
                        self._answer_style=normalize_style(val[3])
                    for kind in kinds:
                        self.learning.feedback(kind,success)
                    if self._pending_alias:
                        spoken,official=self._pending_alias
                        self._pending_alias=None
                        if success and self.desktop.is_installed(official):
                            try:
                                self.learning.learn(spoken,official,verified=True)
                                text+=f". Запомнил название «{spoken}» на будущее."
                            except Exception as exc:
                                text+=f". Не смог сохранить название: {exc}"
                    self.reply(text)
                elif op=="app_suggestion":
                    self.executing=False
                    spoken,installed=val
                    if self.desktop.is_installed(installed) and messagebox.askyesno(
                        "Самоулучшение JARVIS",
                        f"Я не нашёл «{spoken}».\nВозможно, ты имел в виду «{installed}»?\n\n"
                        "Если программа запустится, я запомню название для следующего раза.",parent=self):
                        self._pending_alias=(spoken,installed)
                        from agent_core import Step, Plan
                        self.execute_plan(Plan(steps=[Step("open_app",installed)]))
                    else:
                        self.reply("Не запускаю программу без подтверждения. Можно научить меня через меню «Самоулучшение».")
        except queue.Empty:pass
        self.after(100,self.pump)

    def close(self):
        # WM_DELETE_WINDOW is a *complete exit*, never "hide to tray".
        if self._closing:return
        # Also safe when close() is invoked by a lightweight test controller.
        saver=getattr(self,"save_window_layout",None)
        if callable(saver):saver()
        self._closing=True
        self._shutdown.set()  # prevent slow model initialization reopening the mic
        overlay=getattr(self,"overlay",None)
        if overlay is not None:
            try:overlay.shutdown()
            except tk.TclError:pass
        studio=getattr(self,'_viral_window',None)
        if studio is not None:
            try: studio.cancel()
            except Exception:pass
        self.voice_enabled=False
        chat=getattr(self,'local_chat',None)
        if chat is not None:chat.close()
        self._focus_epoch=getattr(self,'_focus_epoch',0)+1
        self._focus_deadline=None
        self.control_allowed=False;self.vision_allowed=False
        self.voice.stopping=True
        self.voice.running=False
        # Stop resources without freezing the GUI on PortAudio or Vosk teardown.
        def stop_resources():
            try:self.voice.stop()
            except Exception:pass
            try:self.speaker.shutdown()
            except Exception:pass
            try:self.trimodal.shutdown()
            except Exception:pass
        threading.Thread(target=stop_resources,daemon=True,name="jarvis-exit-cleanup").start()
        # Bounded fail-safe: GPU/audio native libraries may leave non-daemon threads.
        # This fires only if the interpreter is still running 5s after closing.
        watchdog=threading.Timer(5.0,lambda:os._exit(0))
        watchdog.daemon=True
        watchdog.start()
        self.destroy()

if __name__=="__main__":
    if sys.platform!="win32":
        print("Это приложение предназначено для Windows.")
    Jarvis().mainloop()
