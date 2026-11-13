# -*- coding: utf-8 -*-
"""Visible task AI dashboard. All extra weights are opt-in user downloads."""
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from task_ai_registry import (
    ROLE_ORDER, get_specialist, pull_specialist, specialist_available,
    SpecialistUnavailable,
)


class TaskAIHub(tk.Toplevel):
    """Read-only task model overview with explicit, cancellable install."""
    def __init__(self,parent,role="scenario"):
        super().__init__(parent)
        self.title("JARVIS NOVA — ИИ для каждой задачи")
        self.geometry("660x450")
        self.minsize(480,360)
        self.parent=parent
        self._busy=False
        self._cancel=threading.Event()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.status=tk.StringVar(value="Каждая задача имеет отдельную роль. Модели не скачиваются сами.")
        self._states={}
        outer=ttk.Frame(self,padding=14)
        outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="ИИ ПО ЗАДАЧАМ",font=("Segoe UI",15,"bold")).pack(anchor="w")
        ttk.Label(outer,
            text="Сценарии — Gemma3, код — Qwen Coder, монтаж — Llama3.2, "
                 "разговор — Qwen3, зрение — Qwen3-VL. "
                 "Без отдельного диалога доступна встроенная Qwen Vision.",
            wraplength=600,justify="left").pack(anchor="w",pady=(4,10))
        rows=ttk.Frame(outer)
        rows.pack(fill="both",expand=True)
        self._buttons={}
        for index,kind in enumerate(ROLE_ORDER):
            spec=get_specialist(kind)
            row=ttk.Frame(rows)
            row.pack(fill="x",pady=4)
            ttk.Label(row,text=spec.label,font=("Segoe UI",10,"bold"),
                      width=24).pack(side="left",padx=(0,4))
            ttk.Label(row,text=spec.model,width=23).pack(side="left")
            state=tk.StringVar(value="встроенная модель" if spec.backend=="bundled"
                               else "не проверено")
            self._states[kind]=state
            ttk.Label(row,textvariable=state,width=16).pack(side="left",padx=4)
            if spec.backend=="ollama":
                button=ttk.Button(row,text="Подключить",
                    command=lambda target=kind:self.connect(target))
                button.pack(side="right")
                self._buttons[kind]=button
        footer=ttk.Frame(outer)
        footer.pack(fill="x",pady=(8,0))
        ttk.Button(footer,text="Проверить установленные модели",
                   command=self.refresh).pack(side="left")
        ttk.Button(footer,text="Отменить загрузку",
                   command=self.cancel).pack(side="left",padx=8)
        ttk.Label(outer,textvariable=self.status,wraplength=600,
                  justify="left").pack(fill="x",pady=(9,0))
        self._focus_role=role if role in ROLE_ORDER else "scenario"

    def _on_ui(self,fn):
        try:
            if self.winfo_exists():
                self.after(0,fn)
        except tk.TclError:
            pass

    def _status(self,message):
        self._on_ui(lambda message=message:self.status.set(str(message)[:330]))

    def refresh(self):
        if self._busy:
            return
        self._busy=True
        def work():
            try:
                from task_ai_registry import local_tags
                installed=set(local_tags())
                def display():
                    for kind in self._buttons:
                        spec=get_specialist(kind)
                        self._states[kind].set(
                            "установлена" if spec.model in installed
                            else "не установлена")
                    self.status.set(
                        "Проверена только локальная Ollama. "
                        "Ничего не скачано и не запущено.")
                self._on_ui(display)
            except SpecialistUnavailable as exc:
                self._status(str(exc))
            finally:
                self._on_ui(lambda:setattr(self,"_busy",False))
        threading.Thread(target=work,daemon=True,name="jarvis-task-ai-check").start()

    def connect(self,kind):
        if self._busy:
            self.status.set("Другая операция ИИ ещё выполняется.")
            return
        spec=get_specialist(kind)
        if spec.backend!="ollama":
            self.status.set("Встроенная модель подключается в настройках Qwen.")
            return
        if not messagebox.askyesno(
            "Скачать отдельный ИИ?",
            f"Для задачи «{spec.label}» будет загружена модель "
            f"{spec.model} в локальную Ollama.\n\n"
            "Загрузка требует интернета и места на диске. "
            "Модель используется только локально: текст задачи не отправляется "
            "в облачный ИИ. Уже скачанные данные не удаляются. "
            "Никакая модель не будет установлена без этого разрешения.\n\n"
            "Разрешить загрузку?",parent=self):
            return
        self._cancel.clear()
        self._busy=True
        def worker():
            try:
                model=pull_specialist(
                    kind,confirmed=True,cancel=self._cancel,
                    progress=self._status)
                def ready():
                    self._states[kind].set("установлена")
                    if kind=="chat":
                        local_chat=getattr(self.parent,"local_chat",None)
                        if local_chat is not None:
                            local_chat.prefer_task_specialist(True)
                    self.status.set("Подключён "+spec.label+": "+model+
                                    ". Теперь открой соответствующую задачу.")
                self._on_ui(ready)
            except (SpecialistUnavailable,OSError) as exc:
                self._status(str(exc))
            finally:
                self._on_ui(lambda:setattr(self,"_busy",False))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-task-ai-pull").start()

    def cancel(self):
        self._cancel.set()
        self.status.set("Отмена запрошена. Скачанные части останутся на диске.")

    def close(self):
        if self._busy:
            if not messagebox.askyesno(
                "Завершить операцию?",
                "Отменить текущую проверку или загрузку модели? "
                "Скачанные данные останутся на диске.",parent=self):
                return
            self._cancel.set()
        self.destroy()
