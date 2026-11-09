# -*- coding: utf-8 -*-
"""Reviewable UI for a local JARVIS source fix. No Git writes or EXE updates."""
from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from self_development import (
    EDITABLE, prepare_self_fix, apply_self_fix, undo_self_fix, suggest_target,
)


class SelfDevelopmentWindow(tk.Toplevel):
    def __init__(self, app, *, task=""):
        super().__init__(app)
        from studio_theme import apply_video_theme, BG, CARD, TEXT, MUTED
        from windows_titlebar import install_dark_titlebar
        self.app = app
        self.title("JARVIS NOVA — Самоисправление · jarvis")
        self.geometry(f"{min(950,max(500,self.winfo_screenwidth()-80))}x"
                      f"{min(720,max(560,self.winfo_screenheight()-90))}")
        self.minsize(min(500,self.winfo_screenwidth()), min(450,self.winfo_screenheight()))
        self.configure(bg=BG)
        apply_video_theme(self)
        install_dark_titlebar(self, background=BG)
        self._busy = False
        self.proposal = None
        self._last_applied = None
        self.folder = tk.StringVar(master=self)
        self.filename = tk.StringVar(master=self, value=suggest_target(task))
        self.status = tk.StringVar(master=self, value=(
            "Рабочий процесс: предложить код → проверить синтаксис → "
            "просмотреть → подтвердить запись в jarvis. GitHub и EXE не изменяются."))

        frame = ttk.Frame(self, padding=14, style="Studio.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="NOVA SELF-DEVELOPMENT · ПРЕДПРОСМОТР ИСПРАВЛЕНИЯ",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(frame,
            text="Только исходный клон GitHub JARVIS-NOVA, только ветка jarvis.",
            style="Studio.Small.TLabel").pack(anchor="w", pady=(2,12))
        ttk.Label(frame, text="Папка исходников (не папка установленного EXE)",
                  style="Studio.TLabel").pack(anchor="w")
        browse = ttk.Frame(frame, style="Studio.TFrame")
        browse.pack(fill="x", pady=(3,9))
        ttk.Entry(browse, textvariable=self.folder, style="Studio.TEntry").pack(
            side="left", fill="x", expand=True)
        ttk.Button(browse, text="Выбрать", command=self.choose,
                   style="Studio.TButton").pack(side="right", padx=(7,0))
        ttk.Label(frame, text="Файл для исправления",
                  style="Studio.TLabel").pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.filename, values=EDITABLE,
                     state="readonly", style="Studio.TCombobox").pack(
                         fill="x", pady=(3,9))
        ttk.Label(frame, text="Опиши ошибку или вставь результат анализа скриншота",
                  style="Studio.TLabel").pack(anchor="w")
        self.task = tk.Text(frame, height=4, wrap="word", bg=CARD,
                            fg=TEXT, insertbackground=TEXT,
                            font=("Segoe UI",10))
        self.task.pack(fill="x", pady=(3,9))
        self.task.insert("1.0", task[:2600])
        buttons = ttk.Frame(frame, style="Studio.TFrame")
        buttons.pack(fill="x", pady=(0,7))
        self.generate_button = ttk.Button(
            buttons, text="1. Подготовить исправление",
            command=self.generate, style="Studio.Primary.TButton")
        self.generate_button.pack(side="left")
        self.apply_button = ttk.Button(
            buttons, text="2. Подтвердить запись в jarvis",
            command=self.apply, style="Studio.TButton", state="disabled")
        self.apply_button.pack(side="right")
        self.undo_button = ttk.Button(
            buttons, text="3. Отменить последнее исправление",
            command=self.undo, style="Studio.TButton", state="disabled")
        self.undo_button.pack(side="right", padx=(0,8))
        ttk.Label(frame, textvariable=self.status, style="Studio.Small.TLabel",
                  wraplength=850).pack(fill="x", pady=(3,7))
        preview = ttk.Frame(frame, style="Studio.TFrame")
        preview.pack(fill="both", expand=True)
        self.output = tk.Text(preview, bg=CARD, fg=TEXT,
                              insertbackground=TEXT,
                              font=("Consolas",9), wrap="none")
        self.output.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(preview, orient="vertical", command=self.output.yview)
        scrollbar.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scrollbar.set)
        self._display("Изменения появятся здесь. Исходники ещё не менялись.")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def choose(self):
        folder = filedialog.askdirectory(parent=self, title="Выбери клон JARVIS-NOVA / jarvis")
        if folder:
            self.folder.set(folder)
            self.proposal = None
            self.apply_button.configure(state="disabled")

    def _display(self, message):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", message)
        self.output.configure(state="disabled")

    def prefill(self, task):
        if task:
            self.task.delete("1.0", "end")
            self.task.insert("1.0", task[:2600])
            self.filename.set(suggest_target(task))
            self.proposal = None
            self.apply_button.configure(state="disabled")
        self.lift()

    def _generator(self, prompt, language):
        if getattr(self.app, "engine", None) == "freellm":
            return self.app.freellm_chat.generate_code(prompt, language)
        runtime = getattr(self.app, "runtime", None)
        if runtime is None:
            raise RuntimeError("Не найден локальный движок Qwen.")
        from code_agent import request_local_model
        endpoint = runtime.start()
        return request_local_model(prompt, language,
                                   endpoint=endpoint, model=runtime.config.model)

    def _on_ui(self, callback):
        try:
            if self.winfo_exists():
                self.after(0, callback)
        except (RuntimeError, tk.TclError):
            pass

    def generate(self):
        if self._busy:
            return
        folder = self.folder.get().strip()
        filename = self.filename.get()
        task = self.task.get("1.0", "end").strip()
        if not folder or len(task) < 12:
            messagebox.showerror("Самоисправление",
                "Выбери клон исходников и опиши задачу (не менее 12 символов).", parent=self)
            return
        if getattr(self.app,"engine",None) == "freellm":
            if not messagebox.askyesno(
                "Разрешить отправку исходника в FreeLLM?",
                "Выбранный Python-файл JARVIS и описание ошибки будут переданы "
                "внешнему провайдеру. Скриншоты напрямую не отправляются. "
                "Продолжить?", parent=self):
                return
        elif getattr(self.app,"engine",None) != "bundled" or not getattr(self.app,"_local_model_ready",False):
            messagebox.showerror("Самоисправление",
                "Нужна установленная локальная Qwen или отдельно разрешённая FreeLLM.",parent=self)
            return
        self._busy = True
        self.proposal = None
        self.generate_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.status.set("Готовлю предложение в отдельной папке. Установленный JARVIS не меняется.")
        def worker():
            try:
                proposal = prepare_self_fix(folder, filename, task, generator=self._generator)
                self._on_ui(lambda: self.ready(proposal))
            except Exception as exc:
                explanation = str(exc)[:500]
                self._on_ui(lambda: self._display("Исправление не подготовлено: " + explanation))
                self._on_ui(lambda: self.status.set("Проверка отклонила предложение."))
            finally:
                self._on_ui(self._unblock)
        threading.Thread(target=worker, daemon=True,
                         name="jarvis-self-development-preview").start()

    def _unblock(self):
        self._busy = False
        self.generate_button.configure(state="normal")

    def ready(self, proposal):
        self.proposal = proposal
        self._display(
            "Файл: " + proposal.filename + "\n" +
            proposal.diagnostics + "\n" +
            "\n".join(proposal.review_notes) +
            "\n\nОТЛИЧИЯ (+ добавлено, - удалено):\n\n" +
            proposal.diff_text +
            "\n\nПОЛНЫЙ КОД НОВОГО ФАЙЛА:\n\n" +
            proposal.plan.files[0].content)
        self.status.set("Предложение готово. Исправление НЕ тестировалось на реальном Windows ПК.")
        self.apply_button.configure(state="normal")

    def apply(self):
        if self._busy or self.proposal is None:
            return
        proposal = self.proposal
        if (Path(self.folder.get().strip()).resolve() != proposal.folder
                or self.filename.get() != proposal.filename):
            messagebox.showerror("Самоисправление",
                "Путь или файл изменился. Подготовь предложение заново.",parent=self)
            return
        if not messagebox.askyesno(
            "Подтвердить запись только в jarvis",
            "Изменить локальный файл " + proposal.filename +
            " в клоне JARVIS-NOVA, ветка jarvis?\n\n"
            "Исходный файл будет сохранён в резервной копии.\n"
            "Синтаксис проверен; функциональные тесты и GitHub Actions ещё не выполнялись.\n"
            "Не будет публикации, обновления EXE или изменения main.\n\n"
            "Ты просмотрел предложение и подтверждаешь?", parent=self):
            return
        try:
            changed = apply_self_fix(proposal, confirmed=True)
            self._last_applied = proposal
            self.undo_button.configure(state="normal")
            self.proposal = None
            self.apply_button.configure(state="disabled")
            self.status.set(
                "Локальный исходник обновлён. Проверь тесты, GitHub Actions "
                "и собранный EXE перед публикацией стабильного релиза.")
            self._display("Записано с резервной копией:\n" +
                          "\n".join(changed) + "\n\nВетка main не изменена.")
        except Exception as exc:
            messagebox.showerror("Самоисправление",str(exc),parent=self)


    def undo(self):
        """Confirm and restore exactly the last applied change in this session."""
        proposal = self._last_applied
        if self._busy or proposal is None:
            return
        if not messagebox.askyesno(
            "Отменить последнее самоисправление?",
            "Вернуть предыдущую версию файла " + proposal.filename +
            " в локальном клоне ветки jarvis?\n"
            "Новая версия останется в резервных копиях. "
            "Ни GitHub, ни установленная программа не изменятся.\n\n"
            "Продолжить?", parent=self):
            return
        try:
            restored = undo_self_fix(proposal, confirmed=True)
            self._last_applied = None
            self.undo_button.configure(state="disabled")
            self.proposal = None
            self.apply_button.configure(state="disabled")
            self.status.set("Предыдущая версия исходника восстановлена. Копия исправления сохранена.")
            self._display("Отмена подтверждена. Восстановлен файл:\n" + restored)
        except Exception as exc:
            messagebox.showerror("Отмена самоисправления", str(exc), parent=self)
