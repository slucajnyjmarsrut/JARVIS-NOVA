# -*- coding: utf-8 -*-
"""Speech-free shared desktop controller. Start text_only_main.TextJarvis."""
from __future__ import annotations
import os, queue, sys, threading, time, math, re, tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from agent_core import Plan, parse_local, validate_plan, ask_ai_for_plan
from desktop import Desktop, AppSuggestion
from self_improve import LearningStore, safe_name
from self_repair import repair_configs, inspect_configs
from auto_update import installed_application, check_and_download, stage_helper
from work_modes import ModeManager, ModeCommand, MODES, VIDEO_STAGES
from game_catalog import GameCatalog
from local_chat import LocalChat, explain_local_model_failure
from nova_compact_ui import compact_geometry
from nova_window_state import save_layout
from overlay_commands import overlay_intent, preview_line
from debate_mode import debate_command
from manual_file_deletion import (
    is_delete_request, is_folder_request, choose_for_manual_deletion,
    user_explanation,
)

def screen_question(text):
    """Recognize typed request; no automatic image capture here."""
    phrase=str(text).casefold().replace("ё","е")
    return any(x in phrase for x in (
        "посмотри на экран", "опиши экран", "что на экране",
        "что ты видишь", "что видишь на экране", "покажи экран", "анализ экрана"))

class Jarvis(tk.Tk):
    """Shared non-audio methods for the production TextJarvis window."""
    def __init__(self):
        raise RuntimeError("Запускай JARVIS через text_only_main.TextJarvis.")

    def _set_native_dark_titlebar(self):
        """Apply DwmSetWindowAttribute to the full native Tk window safely."""
        from windows_titlebar import install_dark_titlebar
        install_dark_titlebar(self, background="#070D17")

    def open_code_assistant(self, language="java", task="", *, auto_start=False):
        """Open an integrated coding dialog; user approves changes explicitly."""
        try:
            from code_gui import CodeWindow
            window=getattr(self,"_code_window",None)
            if window is not None and window.winfo_exists():
                window.prefill(language,task)
                window.focus_force()
                if auto_start and task:
                    window.after(50,lambda w=window:w.generate(auto_save=True))
                return
            self._code_window=CodeWindow(self,language=language,task=task)
            if auto_start and task:
                self._code_window.after(50,lambda w=self._code_window:w.generate(auto_save=True))
        except Exception as exc:
            messagebox.showerror("Программирование",str(exc),parent=self)

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
        """Only positions/sizes; never store conversation."""
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
        messagebox.showinfo("JARVIS NOVA — возможности",
            "Чат, программы, экран, сценарии, код и видеомонтаж. "
            "Управление компьютером требует разрешения.",parent=self)

    def log(self,person,message):
        self.history.configure(state="normal")
        tag=person if person in {"JARVIS","Вы","Система","Профиль"} else "error" if "ошиб" in person.casefold() else "Система"
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

    def _restore_startup_permissions(self):
        """Load the Windows first-run defaults or a saved user override."""
        from startup_permissions import load_startup_permissions
        saved = load_startup_permissions()
        self.control_allowed = saved.control
        self.vision_allowed = saved.vision
        self.status.set(
            "Готов. Разрешения при запуске: ПК — " +
            ("включено" if saved.control else "отключено") + ", экран — " +
            ("включено" if saved.vision else "отключено") +
            ". Автозахват и выполнение команд не запускаются. "
            "Отключить можно через Настройки → Разрешения.")

    def enable_persistent_permissions(self):
        """An explicit one-time human confirmation; never from LLM output."""
        from startup_permissions import (
            StartupPermissions, save_startup_permissions,
        )
        if not messagebox.askyesno(
                "Всегда разрешать JARVIS управление и зрение?",
                "Сохранять разрешение на управление мышью, клавиатурой и "
                "окнами, а также на доступ к текущему экрану в каждом "
                "следующем запуске JARVIS под этой учётной записью Windows?\n\n"
                "Оба доступа будут доступны JARVIS сразу после запуска, "
                "пока ты их не отзовёшь в настройках. "
                "Это НЕ включает постоянную запись экрана, "
                "автоматический захват, скачивание моделей, "
                "облачные сервисы, удаление файлов или "
                "автоматическое выполнение опасных команд.\n\n"
                "Разрешить и запомнить для будущих запусков?",
                parent=self):
            return False
        try:
            save_startup_permissions(StartupPermissions(True, True))
        except (OSError, ValueError) as exc:
            self.status.set("Не удалось сохранить постоянные разрешения: " +
                            str(exc)[:150])
            messagebox.showerror("Разрешения не сохранены",
                                 str(exc), parent=self)
            return False
        self.control_allowed = True
        self.vision_allowed = True
        self.status.set("Управление и зрение разрешены сейчас и при следующих "
                        "запусках. Отозвать можно в настройках.")
        return True

    def grant_control(self):
        if self.control_allowed:
            self.status.set("Управление ПК уже включено в настройках.")
            return True
        if messagebox.askyesno("Разрешение","Разрешить JARVIS управлять мышью, клавиатурой и окнами до закрытия приложения?"):
            self.control_allowed=True
            self.status.set("Управление разрешено до закрытия JARVIS")
            return True
        return False

    def grant_vision(self):
        if self.vision_allowed:
            self.status.set("Зрение уже включено в настройках.")
            return True
        if messagebox.askyesno("Разрешение","Разрешить захватывать текущий экран в оперативную память и отправлять кадры только в локальную Ollama?"):
            self.vision_allowed=True
            self.status.set("Локальное зрение разрешено до закрытия JARVIS")
            return True
        return False

    def revoke(self):
        """Turn off live rights and revoke the persistent Windows preference."""
        from startup_permissions import (
            StartupPermissions, save_startup_permissions,
        )
        self.control_allowed = False
        self.vision_allowed = False
        # Invalidate any one-shot screenshot request queued in a worker.
        # Do this even if the persistent permission store cannot be saved.
        epoch = getattr(self, "_vision_revocation_epoch", 0)
        self._vision_revocation_epoch = (epoch if type(epoch) is int else 0) + 1
        try:
            save_startup_permissions(StartupPermissions(False, False))
        except (OSError, ValueError) as exc:
            self.status.set("Разрешения отключены до закрытия JARVIS, но "
                            "не удалось сбросить сохранённый выбор: " +
                            str(exc)[:130])
            messagebox.showerror(
                "Не удалось отозвать сохранённые разрешения",
                "Доступ отключён в текущем сеансе. "
                "Ошибка при изменении записи запуска: " + str(exc)[:220] +
                "\n\nСохранённая настройка всё ещё действует: "
                "устрани ошибку записи и повтори отзыв. "
                "НЕ удаляй startup_permissions.bin: без файла "
                "новая установка Windows использует доступ по умолчанию.",
                parent=self)
            return False
        self.status.set("Все разрешения отозваны, включая последующие запуски.")
        return True

    def teach_alias(self):
        spoken=simpledialog.askstring("Обучение JARVIS", "Какое короткое название программы ты вводишь в чате?",parent=self)
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

    def open_creator_accounts(self):
        """User-led registration at official YouTube, TikTok or Instagram sites."""
        if self._closing:
            return None
        from creator_accounts_ui import CreatorAccountsWindow
        previous=getattr(self, "_creator_accounts_window", None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return previous
        self._creator_accounts_window=CreatorAccountsWindow(self)
        return self._creator_accounts_window

    def open_timeline(self):
        """Editable timeline: non-destructive trims, ordering and final render."""
        if self._closing:
            return None
        from video_timeline_ui import TimelineWindow
        previous=getattr(self,"_timeline_window",None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return previous
        self._timeline_window=TimelineWindow(self)
        return self._timeline_window

    def open_multitrack(self):
        """Genuine local multi-track compositor; no media leaves this computer."""
        if self._closing:
            return None
        from multitrack_ui import MultitrackWindow
        old=getattr(self,"_multitrack_window",None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        self._multitrack_window=MultitrackWindow(self)
        return self._multitrack_window

    def open_publish_preparation(self,video=None):
        """Prepare a local draft; upload requires the owner's manual action."""
        if self._closing:
            return None
        from creator_publish_ui import PublishWindow
        old=getattr(self,"_publish_window",None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        self._publish_window=PublishWindow(self,video=video)
        return self._publish_window

    def open_viral_studio(self,stage="audience"):
        """One in-app window for trend research, a shot list and local video editing."""
        if self._closing:return
        from viral_studio_ui import ViralStudioWindow
        previous=getattr(self,'_viral_window',None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            previous.focus_stage(stage)
            return previous
        self._viral_window=ViralStudioWindow(self)
        self._viral_window.focus_stage(stage)
        return self._viral_window

    def activate_mode(self,key):
        if key not in MODES and key!='neutral':
            return
        command=self.modes.set_mode(key)
        self.handle_mode_command(command)
        if key=='gaming':
            # Choose a game using the native dialog.
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

    def show_module_health(self):
        """Read-only health dashboard: no models or external tools launched."""
        from module_health_ui import ModuleHealthWindow
        ModuleHealthWindow(self)

    def open_night_supervisor(self):
        """Open explicit-consent night queue, never execute on open."""
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

    def set_debate_mode(self, enabled=None):
        """Opt-in, session-only debate style for conversational models."""
        if self._closing:
            return
        if getattr(self,"executing",False):
            self.reply("Сначала дождись завершения текущего ответа.")
            return
        if enabled is None:
            enabled = not bool(getattr(self,"_debate_mode",False))
        if type(enabled) is not bool:
            raise ValueError("Нужен логический параметр режима спора.")
        for name in ("local_chat","freellm_chat"):
            client=getattr(self,name,None)
            if client is not None:
                client.set_debate_mode(enabled)
        self._debate_mode=enabled
        if enabled:
            self.reply("Режим спора включён. Предложи тезис — я выдвину "
                       "аргументы против, проверю доводы и буду готов "
                       "признать твою правоту. Чтобы завершить, скажи "
                       "«хватит спорить».")
        else:
            self.reply("Режим спора выключен. Вернулся к обычному диалогу.")

    def enter(self,event=None):
        s=self.entry.get().strip()
        self.entry.delete(0,"end")
        if s:

            self.handle_text(s)

    def _check_auto_update(self, force=False):
        """Check and DOWNLOAD official stable GitHub release in background.

        The app never downloads release artifacts, branches, or scripts.
        No network is attempted during normal source/developer runs.
        """
        if self._closing or self._auto_update_busy or self._auto_update_pending:
            return
        preferences=getattr(self,"update_preferences",None)
        if not force and preferences is not None and not preferences.automatic_checks:
            return
        installed=installed_application()
        if installed is None:
            if force:
                self._auto_update_state=("Обновления доступны только в "
                                         "установленном Windows-приложении.")
                self.status.set(self._auto_update_state)
            return
        from publisher_trust import publisher_is_configured
        if not publisher_is_configured():
            self._auto_update_state=(
                "Автообновления заблокированы: сертификат издателя "
                "пока не закреплён. Неподписанные EXE не устанавливаются.")
            if force:
                self.status.set(self._auto_update_state)
            return
        self._auto_update_busy=True
        self._auto_update_progress=0
        self._auto_update_state="Проверяю официальные стабильные релизы…"
        if force:
            self.status.set(self._auto_update_state)
        def worker():
            try:
                result=check_and_download(
                    cancel=self._shutdown,
                    progress=lambda done,total:self.q.put((
                        "update_progress",(done,total))),
                    on_release=lambda release:self.q.put((
                        "update_found",release.version)))
                if self._shutdown.is_set():
                    return
                if result is not None:
                    self.q.put(("update_ready",result))
                else:
                    self.q.put(("update_none",None))
            except Exception as exc:
                if not self._shutdown.is_set():
                    # Never display remote API text, file names or tokens.
                    self.q.put(("update_error",type(exc).__name__))
            finally:
                if not self._shutdown.is_set():
                    self.q.put(("update_check_done",None))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-update-check").start()

    def _finish_auto_update(self, force=False):
        """Apply staged update only when safe. Users can trigger it instantly."""
        if self._closing or not self._auto_update_pending:
            return
        preferences=getattr(self,"update_preferences",None)
        if not force and preferences is not None and not preferences.automatic_restart:
            return
        if not force and getattr(self,"_auto_update_snoozed",False):
            return
        release,installer=self._auto_update_pending
        studio=getattr(self,"_viral_window",None)
        input_widget=getattr(self,"entry",None)
        unsent=bool(input_widget is not None and input_widget.get().strip())
        busy=(self.executing or getattr(studio,"running",False) or unsent)
        from update_idle_guard import editing_window_open
        if editing_window_open(self):
            busy=True
        if busy:
            if force:
                self._auto_update_state=(
                    "Сохрани черновик, дождись окончания работы и повтори обновление.")
                self.status.set(self._auto_update_state)
            else:
                self.after(15000,self._finish_auto_update)
            return
        # The previous implementation closed the app after only 12 seconds,
        # which could interrupt somebody reading the answer or notes.
        # Restart only after ten minutes of no keyboard or mouse interaction.
        if not force:
            last_seen=getattr(self,"_auto_update_first_seen",0)
            # Older controller integrations do not track keyboard activity.
            # In that case the ready timestamp still controls safe deferral.
            last_activity=getattr(self,"_last_input_activity",last_seen)
            if time.monotonic()-max(last_activity,last_seen)<600:
                self.after(15000,self._finish_auto_update)
                return
        installed=installed_application()
        if installed is None:
            self._auto_update_pending=None
            self._auto_update_state="Обновление недоступно вне установленной программы."
            return
        try:
            stage_helper(release,installer,installed,installer.parent)
        except Exception as exc:
            self._auto_update_state="Обновление отложено: "+type(exc).__name__
            self.status.set(self._auto_update_state)
            self._auto_update_pending=None
            return
        self._auto_update_state="Устанавливаю обновление; JARVIS перезапустится."
        self.status.set(self._auto_update_state)
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

    def show_manual_delete_location(self, *, folder=False):
        """User-operated file chooser, then Explorer only; no deletion."""
        self.reply(user_explanation())
        try:
            selected=choose_for_manual_deletion(
                parent=self, folder=folder)
        except (OSError,ValueError) as exc:
            self.reply("Не удалось открыть расположение: "+str(exc)[:200])
            return
        if selected is None:
            self.reply("Выбор отменён. Ничего не удалено.")
        else:
            self.reply("Открыл расположение выбранного объекта в "
                       "Проводнике. Ничего не удалено; решение за тобой.")

    def handle_text(self,text):
        if self._closing:return
        self.log("Вы",text)
        if is_delete_request(text):
            self.show_manual_delete_location(
                folder=is_folder_request(text))
            return
        debate=debate_command(text)
        if debate is not None:
            if debate=="status":
                self.reply("Режим спора "+("включён." if getattr(
                    self,"_debate_mode",False) else "выключен."))
            else:
                self.set_debate_mode(debate=="on")
            return
        from coding_intent import detect_coding_intent
        coding=detect_coding_intent(text)
        if coding is not None:
            self.open_code_assistant(coding.language,coding.task,auto_start=True)
            self.reply("Открываю программирование. Проверь проект и подтверди запись файлов.")
            return
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
        # Typed requests can open the fully automatic studio, but must never
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
        # A webcam cannot be opened by JARVIS, including via text that would trigger desktop app launching.
        normalized=text.casefold().replace("ё","е")
        if (re.search(r"(?:камер|вебкамер|webcam|camera)",normalized) and
                re.search(r"(?:включи|открой|покажи|посмотри|сними|сфотографируй|что перед|опиши)",normalized)):
            self.reply("Веб-камера полностью удалена из JARVIS. Можно анализировать только экран.")
            return
        if screen_question(text):
            self.request_screen_analysis("screen")
            return
        if text.casefold().strip() in {"стоп","отмена","прекрати"}:
            self.status.set("Остановлено")
            return
        local=parse_local(text)
        if self.engine=="none" or local.steps or local.answer or text.casefold().strip() in {"открой","запусти","включи"}:
            self.execute_plan(local)
        elif self.engine in ("bundled","freellm"):
            if self.executing:
                self.reply("Подожди, пока я закончу предыдущий запрос.")
                return
            self.executing=True
            request_style="normal"
            provider=self.engine
            self.status.set(
                "FreeLLM: ожидаю ответ выбранной модели…" if provider=="freellm"
                else "Думаю локально — первый ответ может занять время…")
            def chat_worker():
                try:
                    client=self.freellm_chat if provider=="freellm" else self.local_chat
                    result=(True,client.ask(text))
                except Exception as exc:
                    if provider=="freellm":
                        result=(False,"FreeLLM недоступен: "+str(exc)[:200])
                    else:
                        result=(False,explain_local_model_failure(exc))
                self.q.put(("chat_result",(*result,request_style)))
            threading.Thread(target=chat_worker,daemon=True,name="jarvis-text-chat").start()
        else:
            request_style="normal"
            self.status.set("Обдумываю запрос…")
            def worker():
                plan=ask_ai_for_plan(text,self.engine)
                self.q.put(("plan",(plan,request_style)))
            threading.Thread(target=worker,daemon=True).start()

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
            self.request_screen_analysis("screen")
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
        request_style="normal"
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

    def check_models(self):
        from module_health_ui import ModuleHealthWindow
        ModuleHealthWindow(self)

    def reply(self, message):
        if not self._closing:
            self.log("JARVIS",str(message))
            self.status.set(str(message)[:130])

    def pump(self):
        """Dispatch only keyboard/chat, desktop and update events on Tk thread."""
        if self._closing:return
        try:
            while True:
                op,val=self.q.get_nowait()
                if op=="update_found":
                    self._auto_update_state="Новая версия "+str(val)+": проверяю SHA256…"
                    self.status.set(self._auto_update_state)
                elif op=="update_progress":
                    received,total=val
                    self._auto_update_progress=int(100*received/max(1,total))
                    self._auto_update_state="Обновление: "+str(self._auto_update_progress)+"%"
                elif op=="update_ready":
                    self._auto_update_pending=val
                    self._auto_update_progress=100
                    self._auto_update_first_seen=time.monotonic()
                    self._auto_update_state="Версия "+val[0].version+" проверена; обновить через меню ⟳."
                    self.status.set(self._auto_update_state)
                    self.after(3000,self._finish_auto_update)
                elif op=="update_none":
                    self._auto_update_state="Новых стабильных обновлений пока нет."
                elif op=="update_error":
                    self._auto_update_state="Ошибка проверки обновлений: "+str(val)[:60]
                    self.status.set(self._auto_update_state)
                elif op=="update_check_done":
                    self._auto_update_busy=False
                    self.after(12*60*60*1000,self._check_auto_update)
                elif op=="chat_result":
                    self.executing=False
                    self.reply(val[1])
                elif op=="plan":
                    self.execute_plan(val[0] if isinstance(val,tuple) and len(val)==2 else val)
                elif op=="action_result":
                    self.executing=False
                    success,message,kinds=val[:3]
                    for kind in kinds:
                        self.learning.feedback(kind,success)
                    if self._pending_alias:
                        alias,official=self._pending_alias
                        self._pending_alias=None
                        if success and self.desktop.is_installed(official):
                            try:
                                self.learning.learn(alias,official,verified=True)
                                message+=f". Запомнил «{alias}»."
                            except (OSError,ValueError):
                                message+=". Не смог запомнить название."
                    self.reply(message)
                elif op=="app_suggestion":
                    self.executing=False
                    alias,installed=val
                    if self.desktop.is_installed(installed) and messagebox.askyesno(
                            "Самоулучшение JARVIS",f"«{alias}» означает «{installed}»? "
                            "Запустить и запомнить после успеха?",parent=self):
                        self._pending_alias=(alias,installed)
                        from agent_core import Step, Plan
                        self.execute_plan(Plan(steps=[Step("open_app",installed)]))
                    else:
                        self.reply("Не запускаю без подтверждения.")
                elif op=="status":
                    self.status.set(str(val)[:250])
        except queue.Empty:
            pass
        self.after(100,self.pump)

if __name__ == "__main__":
    from text_only_main import TextJarvis
    TextJarvis().mainloop()
