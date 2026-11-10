# -*- coding: utf-8 -*-
"""Creator onboarding: registration remains in the user's own browser."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from creator_accounts import (
    SITES, CreatorSignupError, open_creator_registration,
    open_creator_help, suggest_creator_handles,
)


class CreatorAccountsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        from studio_theme import apply_video_theme, BG, CARD, TEXT, CYAN
        from windows_titlebar import install_dark_titlebar

        self.title("JARVIS NOVA — YouTube · TikTok · Instagram")
        self.configure(bg=BG)
        self.geometry(f"{min(900,max(500,self.winfo_screenwidth()-80))}x"
                      f"{min(735,max(550,self.winfo_screenheight()-80))}")
        self.minsize(500, 510)
        apply_video_theme(self)
        install_dark_titlebar(self, background=BG)

        panel = ttk.Frame(self, padding=15, style="Studio.TFrame")
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="СОЗДАНИЕ АККАУНТОВ · ОФИЦИАЛЬНЫЕ САЙТЫ",
                  style="Studio.Heading.TLabel").pack(anchor="w", pady=(0,6))
        ttk.Label(panel, text=(
            "JARVIS поможет открыть регистрацию и подготовить название. "
            "Пароли, email, дату рождения, CAPTCHA и SMS вводишь только "
            "в официальном браузере. JARVIS их не читает и не сохраняет."),
            style="Studio.Small.TLabel", wraplength=790).pack(
                anchor="w", pady=(0,12))

        for site in SITES:
            card = tk.Frame(panel, bg=CARD, padx=12, pady=9)
            card.pack(fill="x", pady=(0,8))
            tk.Label(card, text=site.name, bg=CARD, fg=CYAN,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(card, text=site.guide, bg=CARD, fg=TEXT,
                     font=("Segoe UI", 9), justify="left",
                     wraplength=790).pack(anchor="w", pady=(5,7))
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x")
            ttk.Button(
                row, text="Открыть официальную регистрацию",
                style="Studio.Primary.TButton",
                command=lambda key=site.key: self._open(key),
            ).pack(side="left", padx=(0,8))
            ttk.Button(
                row, text="Справка платформы",
                style="Studio.TButton",
                command=lambda key=site.key: self._help(key),
            ).pack(side="left")

        ttk.Label(panel, text="Идеи @имени (доступность не проверяется)",
                  style="Studio.TLabel").pack(anchor="w", pady=(5,3))
        chooser = ttk.Frame(panel, style="Studio.TFrame")
        chooser.pack(fill="x")
        self.brand = tk.StringVar()
        ttk.Entry(chooser, textvariable=self.brand, style="Studio.TEntry").pack(
            side="left", fill="x", expand=True)
        ttk.Button(chooser, text="Предложить", command=self._handles,
                   style="Studio.TButton").pack(side="right", padx=(8,0))
        self.result = tk.StringVar(value="Можно придумать одно узнаваемое имя для трёх площадок.")
        ttk.Label(panel, textvariable=self.result, style="Studio.Small.TLabel",
                  wraplength=780).pack(anchor="w", pady=(8,0))

    def _open(self, key):
        site = next(item for item in SITES if item.key == key)
        if not messagebox.askyesno(
            "Перейти на официальный сайт?",
            f"Открыть регистрацию {site.name} в твоём обычном браузере?\n\n"
            "JARVIS не заполняет формы и не обходит проверки сервиса.",
            parent=self,
        ):
            return
        try:
            if not open_creator_registration(key, confirmed=True):
                raise CreatorSignupError("Браузер не смог открыть страницу.")
            self.result.set(
                "Сайт открыт. Заверши создание аккаунта самостоятельно "
                "в официальном браузере.")
        except (OSError, CreatorSignupError) as exc:
            messagebox.showerror("Регистрация", str(exc), parent=self)

    def _help(self, key):
        site = next(item for item in SITES if item.key == key)
        if messagebox.askyesno(
            "Открыть справку?", "Показать официальную справку " +
            site.name + " в браузере?", parent=self,
        ):
            try:
                if not open_creator_help(key, confirmed=True):
                    raise CreatorSignupError("Браузер не смог открыть справку.")
            except (OSError, CreatorSignupError) as exc:
                messagebox.showerror("Справка", str(exc), parent=self)

    def _handles(self):
        try:
            names = suggest_creator_handles(self.brand.get())
            self.result.set("Возможные имена: " + " · ".join("@" + n for n in names))
        except CreatorSignupError as exc:
            self.result.set(str(exc))
