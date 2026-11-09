# -*- coding: utf-8 -*-
"""Native dark update center for installed JARVIS NOVA.

Checking/downloading happens in an existing background worker, never on the
Tk thread. No arbitrary installer URLs or source/git updates are accepted.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from auto_update import APP_VERSION, installed_application
from update_preferences import UpdatePreferences, save_preferences
from publisher_trust import publisher_is_configured

BG="#081421"
CARD="#10253A"
HOVER="#20465C"
CYAN="#43DFE5"
TEXT="#E9F6FB"
MUTED="#A5BDCB"
GREEN="#6CDEAF"


class UpdateCenter(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app=app
        self.title("JARVIS NOVA — Автообновления")
        self.configure(bg=BG)
        self.resizable(False,False)
        self.geometry("495x405")
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW",self.destroy)
        self.auto_check=tk.BooleanVar(master=self,value=app.update_preferences.automatic_checks)
        self.auto_restart=tk.BooleanVar(master=self,value=app.update_preferences.automatic_restart)
        frame=tk.Frame(self,bg=BG)
        frame.pack(fill="both",expand=True,padx=20,pady=16)
        tk.Label(frame,text="⟳  ОБНОВЛЕНИЯ NOVA",bg=BG,fg=CYAN,
                 font=("Segoe UI",15,"bold")).pack(anchor="w")
        tk.Label(frame,text="Установленная версия: "+APP_VERSION,
                 bg=BG,fg=MUTED,font=("Segoe UI",10)).pack(anchor="w",pady=(5,10))
        box=tk.Frame(frame,bg=CARD,highlightthickness=1,
                     highlightbackground="#315366")
        box.pack(fill="x",pady=(0,10),ipadx=12,ipady=10)
        self.status=tk.StringVar(master=self,value="Проверяю статус…")
        self.status_label=tk.Label(box,textvariable=self.status,bg=CARD,fg=TEXT,
                                   font=("Segoe UI",10),wraplength=420,
                                   anchor="w",justify="left")
        self.status_label.pack(fill="x",padx=12,pady=6)
        self.progress=ttk.Progressbar(box,mode="determinate",maximum=100)
        self.progress.pack(fill="x",padx=12,pady=(0,7))
        chk1=tk.Checkbutton(frame,text="Автоматически проверять и скачивать новые версии",
            variable=self.auto_check,command=self.save,
            bg=BG,fg=TEXT,selectcolor=CARD,
            activebackground=BG,activeforeground=CYAN,
            font=("Segoe UI",10),anchor="w",borderwidth=0)
        chk1.pack(anchor="w",pady=3)
        chk2=tk.Checkbutton(frame,text="Перезапускать JARVIS, когда я долго не работаю",
            variable=self.auto_restart,command=self.save,
            bg=BG,fg=TEXT,selectcolor=CARD,
            activebackground=BG,activeforeground=CYAN,
            font=("Segoe UI",10),anchor="w",borderwidth=0)
        chk2.pack(anchor="w",pady=3)
        buttons=tk.Frame(frame,bg=BG)
        buttons.pack(fill="x",pady=(15,5))
        self.check_button=self._button(buttons,"Проверить сейчас",self.check)
        self.check_button.pack(side="left",padx=(0,8))
        self.install_button=self._button(buttons,"Обновить и перезапустить",
                                          self.install,accent=True)
        self.install_button.pack(side="left")
        self.later_button=self._button(frame,"Отложить до следующего запуска",
                                       self.later)
        self.later_button.pack(anchor="w",pady=(4,2))
        tk.Label(frame,text="Только стабильные GitHub Releases. "
            "Для установки необходимы SHA256, действующая подпись Windows "
            "и закреплённый сертификат издателя. Без них обновление запрещено.",
            bg=BG,fg=MUTED,font=("Segoe UI",9),justify="left",
            wraplength=450).pack(anchor="w",pady=(5,0))
        self.after(250,self.refresh)

    def _button(self,parent,text,command,accent=False):
        bg="#127480" if accent else CARD
        button=tk.Button(parent,text=text,command=command,
            bg=bg,fg=TEXT,activebackground=HOVER,activeforeground=CYAN,
            relief="flat",bd=0,padx=13,pady=9,font=("Segoe UI",9,"bold"),
            cursor="hand2")
        return button

    def save(self):
        before=self.app.update_preferences
        preferences=UpdatePreferences(self.auto_check.get(),self.auto_restart.get())
        try:
            save_preferences(preferences)
        except (OSError,ValueError) as exc:
            self.auto_check.set(before.automatic_checks)
            self.auto_restart.set(before.automatic_restart)
            messagebox.showerror("Не сохранились настройки",
                "Не удалось сохранить параметры автообновления: "+
                type(exc).__name__,parent=self)
            return
        self.app.update_preferences=preferences
        if (preferences.automatic_restart and self.app._auto_update_pending
                and publisher_is_configured()):
            self.app.after(500,self.app._finish_auto_update)
        if preferences.automatic_checks and not before.automatic_checks:
            self.app.after(500,self.app._check_auto_update)

    def check(self):
        if not publisher_is_configured():
            self.status.set("Проверка обновлений заблокирована: нет доверенной подписи издателя.")
            return
        self.app._check_auto_update(force=True)
        self.refresh()

    def install(self):
        if not publisher_is_configured():
            self.status.set("Установка запрещена: издатель EXE ещё не подтверждён.")
            return
        if not self.app._auto_update_pending:
            self.status.set("Обновление ещё не загружено.")
            return
        self.app._finish_auto_update(force=True)

    def later(self):
        self.app._auto_update_snoozed=True
        self.app._auto_update_state="Установка отложена до следующего запуска JARVIS."
        self.status.set(self.app._auto_update_state)

    def refresh(self):
        try:
            if not self.winfo_exists():
                return
            active=installed_application() is not None
            trusted=publisher_is_configured()
            if not active:
                label="Автообновления доступны только в установленном Windows-приложении."
            elif not trusted:
                label=("Автоустановка заблокирована: разработчик ещё не "
                       "закрепил проверенный сертификат подписи EXE. "
                       "Твои файлы и текущая версия защищены.")
            else:
                label=getattr(self.app,"_auto_update_state",
                              "Готово к проверке стабильных обновлений.")
            self.status.set(label)
            progress=getattr(self.app,"_auto_update_progress",0)
            self.progress["value"]=max(0,min(100,int(progress)))
            busy=bool(getattr(self.app,"_auto_update_busy",False))
            self.check_button.configure(
                state="disabled" if busy or not active or not trusted else "normal")
            pending=bool(getattr(self.app,"_auto_update_pending",None))
            self.install_button.configure(
                state="normal" if pending and active and trusted else "disabled")
            self.after(400,self.refresh)
        except tk.TclError:
            return


def show_update_center(app):
    previous=getattr(app,"_update_center",None)
    if previous is not None and previous.winfo_exists():
        previous.lift()
        previous.focus_set()
        return previous
    window=UpdateCenter(app)
    app._update_center=window
    window.lift()
    return window
