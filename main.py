# -*- coding: utf-8 -*-
"""JARVIS NOVA Python Agent — one-window desktop assistant."""
import os, queue, sys, threading, time, math, tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from agent_core import Plan, parse_local, validate_plan, ask_ai_for_plan
from desktop import Desktop, AppSuggestion
from speaker import Speaker
from self_improve import LearningStore, safe_name
from trimodal_service import TrimodalService
from work_modes import ModeManager, ModeCommand, MODES, VIDEO_STAGES
from game_catalog import GameCatalog
from voice_engine import Voice as RC4Voice
from local_chat import LocalChat
from nova_ui import build_interface

class Jarvis(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS NOVA — Голос, зрение, видео и режимы")
        self.geometry("1060x720")
        self.minsize(760,590)
        self.configure(bg="#070D17")
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.q=queue.Queue()
        self.voice_enabled=False
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
        self.speaker=Speaker()
        self.trimodal=TrimodalService()
        self.local_chat=LocalChat(self.trimodal.runtime)
        self.desktop=Desktop(lambda:self.control_allowed,lambda:self.vision_allowed,
                             learning=self.learning)
        self.voice=RC4Voice(lambda s:self.q.put(("heard",s)),
                            lambda s:self.q.put(("status",s)),
                            lambda:self.speaker.busy or self.trimodal.speaking,
                            on_vision_audio=lambda pcm,src:self.q.put(("vision_audio",(pcm,src))))
        build_interface(self)
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
        vision_menu.add_command(label="Спросить голосом о камере (Whisper → Vision → Silero)",
                                command=lambda:self.request_trimodal("camera"))
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
        ai=tk.Menu(menu,tearoff=False)
        for title,choice in [("Свободный разговор (встроенная Qwen, офлайн)","bundled"),
                             ("Только офлайн-команды","none"),("Внешняя Ollama","ollama"),
                             ("OpenAI API (нужен ключ)","openai"),
                             ("Claude API (нужен ключ)","anthropic")]:
            ai.add_command(label=title,command=lambda v=choice:self.set_engine(v))
        menu.add_cascade(label="AI",menu=ai)
        learning_menu=tk.Menu(menu,tearoff=False)
        learning_menu.add_command(label="Научить названию программы…",command=self.teach_alias)
        learning_menu.add_command(label="Показать результаты обучения",command=self.learning_report)
        learning_menu.add_command(label="Удалить выученное название…",command=self.remove_alias)
        learning_menu.add_command(label="Сбросить обучение",command=self.reset_learning)
        learning_menu.add_command(label="Проверить офлайн-модели",command=self.check_models)
        menu.add_cascade(label="Самоулучшение",menu=learning_menu)
        menu.add_command(label="Стоп/Выключить микрофон",command=self.toggle_voice)
        self.config(menu=menu)
        self.log("Система","Управление голосом: «Джарвис, открой Chrome». F9 — ручная активация.")
        self.after(100,self.pump)
        threading.Thread(target=self.init_voice,daemon=True).start()

    def show_capabilities(self):
        messagebox.showinfo("Что умеет JARVIS NOVA",
            "Голосовые команды: «Джарвис, открой блокнот» (микрофон должен быть включён).\n\n"
            "Свободный разговор: локальная Qwen включена по умолчанию, без интернета.\n"
            "Зрение: кнопки «ЭКРАН» или «КАМЕРА» — каждый раз спрашивают разрешение.\n"
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
            self.mic_state.set("Микрофон: жду команду (8 секунд)")
        else:
            self.status.set("Сначала включи микрофон кнопкой выше")
        return "break"

    def toggle_voice(self):
        if self._closing:return
        if self.voice_enabled:
            self.voice.stop();self.voice_enabled=False
            self.status.set("Микрофон выключен")
            self.mic_state.set("Микрофон: выключен")
        else:
            self.voice.start();self.voice_enabled=True
            self.status.set("Включаю микрофон…")
            self.mic_state.set("Микрофон: подключается…")

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
        if s:self.handle_text(s)

    def handle_text(self,text):
        if self._closing:return
        self.log("Вы",text)
        mode_command=self.modes.parse(text,self.desktop.is_installed)
        if mode_command is not None:
            self.handle_mode_command(mode_command)
            return
        if any(token in text.casefold() for token in (
            'смонтируй ролик', 'вирусный ролик', 'вирусное видео',
            'сценарий для рилс', 'сценарий для шортс', 'снять тикток')):
            self.open_viral_studio('audience')
            self.status.set('Видео-студия: сначала анализ аудитории; интернет только с разрешения.')
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
            self.status.set("Думаю локально — первый ответ может занять время…")
            def chat_worker():
                try:
                    result=(True,self.local_chat.ask(text))
                except Exception as exc:
                    result=(False,"Локальный разговор недоступен: "+str(exc)[:200])
                self.q.put(("chat_result",result))
            threading.Thread(target=chat_worker,daemon=True,name="jarvis-local-chat").start()
        else:
            self.status.set("Обдумываю запрос…")
            def worker():
                plan=ask_ai_for_plan(text,self.engine)
                self.q.put(("plan",plan))
            threading.Thread(target=worker,daemon=True).start()

    def request_trimodal(self, source: str, audio_pcm: bytes | None = None):
        if self._closing or self.executing:return
        if source not in {"camera","screen"}:return
        noun="камеры" if source=="camera" else "экрана"
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
                    source=source, camera_consent=source=="camera",
                    screen_consent=source=="screen", seconds=5.0,
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
        self.executing=True
        self.status.set("Выполняю команду…")
        def worker():
            self.desktop._active_override=target
            try:
                results=[]
                for step in plan.steps:
                    results.append(self.desktop.run(step))
                self.q.put(("action_result", (True,". ".join(results),
                                                tuple(x.kind for x in plan.steps))))
            except AppSuggestion as suggestion:
                self.q.put(("app_suggestion", (suggestion.spoken,suggestion.installed)))
            except Exception as exc:
                self.q.put(("action_result", (False,"Не получилось: "+str(exc)[:250],
                                                tuple(x.kind for x in plan.steps))))
            finally:
                self.desktop._active_override=None
        threading.Thread(target=worker,daemon=True,name="jarvis-action").start()

    def reply(self,s):
        if self._closing:return
        self.log("JARVIS",s)
        self.status.set(s[:100])
        def speak_and_rearm():
            self.speaker.say(s)
            # The follow-up window starts AFTER speech playback, not before.
            # The mic deliberately ignores its own TTS echo while Speaker.busy.
            if (not self._shutdown.is_set() and self.voice_enabled
                    and self.engine=="bundled" and not self._closing):
                self.voice.activate()
        threading.Thread(target=speak_and_rearm,daemon=True,name="jarvis-speak-rearm").start()

    def pump(self):
        if self._closing:return
        try:
            while True:
                op,val=self.q.get_nowait()
                if op=="heard":self.handle_text(val)
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
                elif op=="trimodal_complete":
                    self.executing=False
                elif op=="chat_result":
                    self.executing=False
                    success,answer=val
                    if success:self.reply(answer)
                    else:self.reply(answer+" Проверь установку моделей.")
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
                    self.status.set(val)
                elif op=="mic_level":
                    success,rms,peak,rate=val
                    if success:
                        self.status.set(
                            f"Тест микрофона: RMS {rms:.4f}, пик {peak:.3f}, {rate} Гц. "
                            +("Очень тихий сигнал: проверь усиление в Windows." if rms<0.002
                              else "Сигнал обнаружен; это не проверка точности Whisper."))
                    else:
                        self.status.set("Не могу проверить микрофон: "+rms)
                elif op=="plan":self.execute_plan(val)
                elif op=="action_result":
                    self.executing=False
                    success,text,kinds=val
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
        self._closing=True
        self._shutdown.set()  # prevent slow model initialization reopening the mic
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
