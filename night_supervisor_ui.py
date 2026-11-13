# -*- coding: utf-8 -*-
"""Explicitly approved overnight queue UI. The window never bypasses consent."""
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from night_supervisor import NightSupervisor, SupervisorError

TASKS = (
    ("Сценарий — Gemma3", "scenario"),
    ("Python-проект — Qwen Coder", "code"),
    ("Советы по монтажу — Llama3.2", "montage_advice"),
)

class NightSupervisorWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("JARVIS NOVA — Автономная ночная работа")
        self.geometry("790x660")
        self.minsize(570, 480)
        self.supervisor = NightSupervisor()
        self.cancel_event = threading.Event()
        self._busy = False
        self._visible_jobs = []
        self.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="JARVIS SUPERVISOR · НОЧНАЯ ОЧЕРЕДЬ",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Только новые файлы в ~/JARVIS-NOVA-Projects/Night-Supervisor. "
                 "Локальные модели, без скачивания, удаления, публикации, "
                 "чтения экрана и запуска сгенерированного кода. "
                 "Приложение и компьютер должны оставаться включёнными.",
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
        ttk.Label(frame, text="Опиши проект (для советов нужен ID сценария)").pack(
            anchor="w", pady=(8, 3))
        self.prompt = tk.Text(frame, height=3, wrap="word")
        self.prompt.pack(fill="x")
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=9)
        for label, action in (
            ("Добавить с разрешением", self.enqueue),
            ("Запустить очередь", self.start),
            ("Пауза", self.pause),
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
            value="Ожидание твоих задач. Никакая модель не запускается сама.")
        ttk.Label(frame, textvariable=self.status, wraplength=735,
                  justify="left").pack(fill="x", pady=(7, 0))
        self.refresh()

    def _ui(self, callback):
        try:
            if self.winfo_exists():
                self.after(0, callback)
        except (tk.TclError, RuntimeError):
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
            "Проверка ограничена структурой сценария, статическим "
            "Python AST или форматом монтажных советов. "
            "Результат не считается функционально проверенным.\n\n"
            "Подтвердить?", parent=self):
            return
        try:
            job_id = self.supervisor.enqueue(
                kind, task, source_id=source, approved=True,
                allow_new_files=True)
            self.status.set("Добавлена задача " + job_id +
                            ". Скачивания или выполнения пока нет.")
            self.refresh()
        except (SupervisorError, ValueError, PermissionError) as exc:
            messagebox.showerror("Не добавлено", str(exc), parent=self)

    def start(self):
        if self._busy:
            return
        if not any(j.status == "queued" for j in self.supervisor.list_jobs()):
            self.status.set("Нет новых задач. Паузы нужно возобновить отдельно.")
            return
        if not messagebox.askyesno(
            "Запустить работу на ночь?",
            "Начать все одобренные задачи (не больше 12) в пределах "
            "6 часов? Компьютер должен не переходить в сон. "
            "Модели не устанавливаются. Непройденные задачи "
            "отмечаются в журнале.\n\nЗапустить?", parent=self):
            return
        self.cancel_event.clear()
        self._busy = True
        self.status.set("Supervisor работает. Не закрывай приложение.")
        def worker():
            try:
                count = self.supervisor.run_queue(
                    cancel=self.cancel_event, progress=self._progress,
                    max_minutes=360)
                self._ui(lambda: self.status.set(
                    f"Очередь завершена или приостановлена. Обработано задач: {count}. "
                    "Проверь журнал и содержимое папок вручную."))
            except Exception as exc:
                error = str(exc)[:260]
                self._ui(lambda: self.status.set(
                    "Supervisor остановлен: " + error))
            finally:
                def finished():
                    self._busy = False
                    self.refresh()
                self._ui(finished)
        threading.Thread(target=worker, daemon=True,
                         name="jarvis-night-supervisor").start()

    def pause(self):
        self.cancel_event.set()
        self.status.set(
            "Пауза запрошена. Текущий вызов модели может завершиться; "
            "после него JARVIS сохранит контрольную точку и остановится.")

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
            self.status.set("Задача возвращена в очередь. Нажми «Запустить очередь».")
        except (SupervisorError, PermissionError) as exc:
            messagebox.showerror("Возобновление невозможно", str(exc), parent=self)

    def close(self):
        if self._busy:
            if not messagebox.askyesno(
                "Остановить ночной режим?",
                "Запросить паузу и закрыть окно? Текущая модель может "
                "завершить запрос; контрольная точка сохранится после ответа.",
                parent=self):
                return
            self.cancel_event.set()
        self.destroy()
