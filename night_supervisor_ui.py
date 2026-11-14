# -*- coding: utf-8 -*-
"""Visible controls for default-on, permission-limited background Supervisor."""
from __future__ import annotations
import threading
from queue import Empty, Queue
import tkinter as tk
from tkinter import messagebox, ttk
from night_supervisor import NightSupervisor, SupervisorError

TASKS = (
    ("Готовый MP4 из темы — анимированная графика", "topic_video"),
    ("Сценарий — Gemma3", "scenario"),
    ("Python-проект — Qwen Coder", "code"),
    ("Советы по монтажу — Llama3.2", "montage_advice"),
)

class NightSupervisorWindow(tk.Toplevel):
    def __init__(self, parent):
        # Acquire queue access before showing a window. Another live process
        # must not cause a half-created Tk window or reset in-flight jobs.
        supervisor = NightSupervisor()
        super().__init__(parent)
        self.parent = parent
        self.title("JARVIS NOVA — Автономная ночная работа")
        self.geometry("790x660")
        self.minsize(570, 480)
        self.supervisor = supervisor
        self.cancel_event = threading.Event()
        self._busy = False
        self._close_when_stopped = False
        self._ui_events = Queue()
        self._visible_jobs = []
        self.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="JARVIS SUPERVISOR · НОЧНАЯ ОЧЕРЕДЬ",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Для MP4 достаточно темы: JARVIS создаёт графику, "
                 "оригинальные тона, титры и монтирует ролик с FFmpeg. "
                 "Это не фотореалистичное AI-видео и без дикторской речи. "
                 "Никаких скачиваний, публикаций и запуска чужого кода.",
            wraplength=735, justify="left").pack(fill="x", pady=(5, 10))
        fields = ttk.Frame(frame)
        fields.pack(fill="x")
        ttk.Label(fields, text="Задача").grid(row=0, column=0, sticky="w")
        self.kind = tk.StringVar(value=TASKS[0][0])
        self.kind_box = ttk.Combobox(
            fields, state="readonly", textvariable=self.kind,
            values=[item[0] for item in TASKS], width=33)
        self.kind_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(fields, text="ID сценария для советов").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.source = ttk.Entry(fields, width=38)
        self.source.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        fields.columnconfigure(1, weight=1)
        ttk.Button(fields, text="Взять ID выбранного сценария",
                   command=self.use_selected_source).grid(
                       row=2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Label(frame, text="Опиши проект (для советов нужен ID сценария)").pack(
            anchor="w", pady=(8, 3))
        self.prompt = tk.Text(frame, height=3, wrap="word")
        self.prompt.pack(fill="x")
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=9)
        for label, action in (
            ("Добавить с разрешением", self.enqueue),
            ("Включить Supervisor", self.start),
            ("Пауза Supervisor", self.pause),
            ("Возобновить выбранную", self.resume),
            ("Обновить", self.refresh),
        ):
            ttk.Button(controls, text=label, command=action).pack(
                side="left", padx=(0, 5))
        ttk.Label(frame, text="Очередь · выбери запись для возобновления").pack(
            anchor="w", pady=(4, 2))
        self.jobs = tk.Listbox(frame, height=7, exportselection=False)
        self.jobs.pack(fill="both", expand=True)
        ttk.Label(frame, text="Журнал и контрольные точки").pack(
            anchor="w", pady=(9, 2))
        self.history = tk.Text(frame, height=7, state="disabled", wrap="word")
        self.history.pack(fill="both", expand=True)
        self.status = tk.StringVar(
            value=("Supervisor включён: новые одобренные задачи запускаются сами."
                   if self.supervisor.background_enabled()
                   else "Supervisor на паузе: задачи ожидают включения."))
        ttk.Label(frame, textvariable=self.status, wraplength=735,
                  justify="left").pack(fill="x", pady=(7, 0))
        self.refresh()
        self.after(120, self._drain_ui)

    def _ui(self, callback):
        """Background threads only enqueue UI work, never touch Tk."""
        self._ui_events.put(callback)

    def _drain_ui(self):
        """All real Tk interactions run exclusively on the main event loop."""
        try:
            for _ in range(40):
                try:
                    callback = self._ui_events.get_nowait()
                except Empty:
                    break
                callback()
            if self.winfo_exists():
                self.after(120, self._drain_ui)
        except tk.TclError:
            pass

    def _progress(self, job_id, message):
        self._ui(lambda: self.status.set(job_id[:8] + ": " + message[:240]))

    def refresh(self):
        try:
            self._visible_jobs = list(self.supervisor.list_jobs())
            self.jobs.delete(0, "end")
            for job in self._visible_jobs:
                label = job.prompt[:44] or ("Сценарий " + job.source_id[:8])
                self.jobs.insert("end", "{} · {} · {} · {}".format(
                    job.id[:8], job.kind, job.status, label))
            lines = ["{} · {} · {} · {}".format(
                row[2][11:19], row[1][:8], row[3], row[4])
                for row in self.supervisor.journal(limit=25)]
            self.history.configure(state="normal")
            self.history.delete("1.0", "end")
            self.history.insert("1.0", "\n".join(lines))
            self.history.configure(state="disabled")
        except (OSError, SupervisorError) as exc:
            self.status.set("Ошибка журнала: " + str(exc)[:260])

    def use_selected_source(self):
        selected = self.jobs.curselection()
        if not selected or selected[0] >= len(self._visible_jobs):
            self.status.set("Сначала выбери сценарий в списке.")
            return
        job = self._visible_jobs[selected[0]]
        if job.kind != "scenario":
            self.status.set("Источником может быть только задача-сценарий.")
            return
        self.source.delete(0, "end")
        self.source.insert(0, job.id)
        self.status.set("ID сценария указан. Можно добавить советы по монтажу.")

    def enqueue(self):
        if self._busy:
            self.status.set("Сначала заверши текущую операцию.")
            return
        kind = dict(TASKS)[self.kind.get()]
        task = self.prompt.get("1.0", "end-1c").strip()
        source = self.source.get().strip().lower() if kind == "montage_advice" else ""
        if not messagebox.askyesno(
            "Разрешение на автономную задачу",
            "Разрешить JARVIS выполнить только эту задачу через локальную "
            "модель и самостоятельно сохранить НОВЫЕ файлы в свою папку?\n\n"
            "Никаких команд ОС, удаления, перезаписи, загрузки моделей, "
            "запуска сгенерированного кода, поиска медиа, публикации "
            "или доступа к экрану.\n\n"
            "MP4 создаётся автономно из графики/звука собственного "
            "синтеза без твоих видео, но это НЕ нейрогенерация реалистичных "
            "сцен и НЕ диктор. FFmpeg и Gemma должны быть установлены. "
            "Техническая проверка ролика не гарантирует художественный "
            "результат.\n\n"
            "Подтвердить?", parent=self):
            return
        try:
            job_id = self.supervisor.enqueue(
                kind, task, source_id=source, approved=True,
                allow_new_files=True)
            self.status.set(
                "Задача " + job_id[:8] + " добавлена и разрешена. "
                + ("Фоновый Supervisor заберёт её сам."
                   if self.supervisor.background_enabled()
                   else "Supervisor на паузе, задача ожидает."))
            self.refresh()
        except (SupervisorError, ValueError, PermissionError) as exc:
            messagebox.showerror("Не добавлено", str(exc), parent=self)

    def start(self):
        """Enable persistent background mode, no additional queue start."""
        try:
            self.supervisor.set_background_enabled(True)
            from night_autorecovery import start_always_on
            start_always_on()
            self.status.set("Supervisor включён постоянно. Уже разрешённые "
                            "задачи выполняются в фоне автоматически.")
            self.refresh()
        except (SupervisorError, OSError, ValueError) as exc:
            self.status.set("Не удалось включить Supervisor: " + str(exc)[:240])

    def pause(self):
        """Persist Pause; any current model request finishes before checkpoint."""
        self.cancel_event.set()
        try:
            self.supervisor.set_background_enabled(False)
            self.supervisor.stop_overnight()
            self.status.set(
                "Supervisor остановлен. Новые задания не начнутся. "
                "Текущая модель может завершить запрос до контрольной точки; "
                "пауза сохранится после перезапуска Windows.")
            self.refresh()
        except (SupervisorError, OSError) as exc:
            self.status.set("Не удалось сохранить паузу: " + str(exc)[:180])

    def resume(self):
        selected = self.jobs.curselection()
        if not selected or selected[0] >= len(self._visible_jobs):
            self.status.set("Выбери прерванную задачу из очереди.")
            return
        job = self._visible_jobs[selected[0]]
        if job.status != "paused":
            self.status.set("Продолжить можно только задачу со статусом paused.")
            return
        if not messagebox.askyesno(
            "Продолжить ночную задачу?",
            "Возобновить только ранее разрешённые действия для этой задачи? "
            "Уже созданные файлы никогда не перезаписываются.", parent=self):
            return
        try:
            self.supervisor.resume(job.id, approved=True)
            self.refresh()
            self.status.set(
                "Задача снова в очереди. Если Supervisor включён, "
                "он обработает её самостоятельно.")
        except (SupervisorError, PermissionError) as exc:
            messagebox.showerror("Возобновление невозможно", str(exc), parent=self)

    def close(self):
        """Closing this window does NOT pause or kill headless Supervisor."""
        self.destroy()
