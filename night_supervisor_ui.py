# -*- coding: utf-8 -*-
"""Explicitly approved overnight queue UI. The window never bypasses consent."""
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
            "Автономная ночная работа — до 6 часов",
            "Разрешить JARVIS самостоятельно завершить ВСЮ заранее одобренную "
            "очередь в пределах 6 часов, без дополнительных вопросов?\n\n"
            "При нехватке ОЗУ JARVIS будет выгружать только собственные "
            "локальные модели, ждать восстановления памяти и продолжать. "
            "После неожиданного завершения приложения разрешение остаётся "
            "действительным только до окончания этих 6 часов: при "
            "следующем запуске JARVIS продолжит незавершённые этапы.\n\n"
            "Никаких установок, удаления чужих файлов, запуска "
            "сгенерированного кода или публикаций. "
            "При постоянной нехватке памяти очередь безопасно остановится. "
            "Компьютер должен быть включён и JARVIS запущен.\n\n"
            "Разрешить автономную работу?", parent=self):
            return
        try:
            self.supervisor.approve_overnight(approved=True, max_minutes=360)
        except (SupervisorError, PermissionError, OSError) as exc:
            messagebox.showerror("Ночной запуск заблокирован", str(exc), parent=self)
            return
        self.cancel_event.clear()
        self._busy = True
        self.status.set("Supervisor работает. Не закрывай приложение.")
        def worker():
            try:
                count = self.supervisor.run_approved_overnight(
                    cancel=self.cancel_event, progress=self._progress)
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
                    if self._close_when_stopped:
                        self.destroy()
                self._ui(finished)
        threading.Thread(target=worker, daemon=True,
                         name="jarvis-night-supervisor").start()

    def pause(self):
        self.cancel_event.set()
        # Explicit pause must revoke unattended startup recovery, otherwise
        # a fresh application would unexpectedly resume the paused task.
        try:
            self.supervisor.stop_overnight()
        except (OSError, SupervisorError) as exc:
            self.status.set("Ошибка отключения автозапуска: " + str(exc)[:180])
            return
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
            self.supervisor.stop_overnight()
            self._close_when_stopped = True
            self.status.set("Жду завершения текущего вызова для сохранения "
                            "контрольной точки. Окно закроется после паузы.")
            return
        self.destroy()
