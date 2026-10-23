# -*- coding: utf-8 -*-
"""The compact NOVA desktop panel; the classic Tk HUD widgets remain reusable.

One visible narrow window, no wallpaper, network, extra microphone or new
computer permissions. All actions call the original Jarvis controller.
"""
from __future__ import annotations
import math
import time
import tkinter as tk
from tkinter import ttk

from nova_ui import (BG, SURFACE, SURFACE_ALT, EDGE, CYAN, CYAN_DIM,
                     GREEN, MUTED, TEXT, AMBER, VIOLET,
                     LevelMeter, Reactor, _label, _action, level_readout,
                     visual_state)

PANEL_WIDTH = 468
PANEL_HEIGHT = 810
PANEL_GAP = 18


def compact_geometry(screen_width, screen_height, width=PANEL_WIDTH,
                     height=PANEL_HEIGHT, gap=PANEL_GAP):
    sw, sh = max(1, int(screen_width)), max(1, int(screen_height))
    w, h = min(sw, width), min(sh, height)
    x = max(0, sw-w-gap)
    y = max(0, (sh-h)//2)
    return f"{w}x{h}+{x}+{y}"


def build_interface(app):
    """Replace fullscreen/dashboard layouts with a single narrow right panel."""
    app.configure(bg=BG)
    app.status = tk.StringVar(master=app, value="Голосовой движок запускается…")
    app.mic_state = tk.StringVar(master=app, value="Микрофон: подключается…")
    app.hud_transcript = tk.StringVar(master=app, value="РАСПОЗНАНО: жду обращение…")
    app.hud_animate = tk.BooleanVar(master=app, value=True)
    app.hud_level_value = 0.0
    app.hud_level_at = 0.0
    app._nova_after_id = None

    shell = tk.Frame(app, bg=BG)
    shell.pack(fill="both", expand=True, padx=12, pady=11)

    header = tk.Frame(shell, bg=BG)
    header.pack(fill="x", pady=(0, 6))
    logo = tk.Canvas(header, bg=BG, width=37, height=37,
                     highlightthickness=0)
    logo.pack(side="left", padx=(0, 9))
    logo.create_oval(2, 2, 35, 35, outline=CYAN_DIM, width=3)
    logo.create_oval(8, 8, 29, 29, outline=CYAN, width=2)
    logo.create_oval(14, 14, 23, 23, fill=CYAN, outline="")
    title = tk.Frame(header, bg=BG)
    title.pack(side="left", fill="x", expand=True)
    _label(title, "JARVIS NOVA", fg=TEXT, size=14, bold=True).pack(anchor="w")
    _label(title, "ЛОКАЛЬНЫЙ ПОМОЩНИК · 0.5.18", fg=CYAN_DIM,
           size=8).pack(anchor="w")
    app.hud_settings_button = _action(
        header, "⚙", lambda: app.show_settings_menu(), compact=True)
    app.hud_settings_button.pack(side="right", padx=(5, 0))
    app.hud_minimize_button = _action(
        header, "▁", lambda: app.hide_main(), compact=True)
    app.hud_minimize_button.pack(side="right")

    voice_shell = tk.Frame(shell, bg=SURFACE, highlightthickness=1,
                           highlightbackground=EDGE)
    voice_shell.pack(fill="x", pady=(0, 7))
    statusbar = tk.Frame(voice_shell, bg=SURFACE)
    statusbar.pack(fill="x", padx=12, pady=(7, 1))
    app.hud_mode = _label(statusbar, "ЗАГРУЗКА", fg=AMBER, size=10, bold=True)
    app.hud_mode.pack(side="left")
    app.hud_engine = _label(statusbar, "QWEN · ЛОКАЛЬНО", fg=GREEN, size=8)
    app.hud_engine.pack(side="right")
    app.hud_reactor = Reactor(voice_shell)
    app.hud_reactor.configure(height=142)
    app.hud_reactor.pack(fill="x", padx=6)
    app.hud_mic = _label(voice_shell, fg=MUTED, size=9,
                         textvariable=app.mic_state, wraplength=410)
    app.hud_mic.pack(pady=(0, 2))
    app.hud_meter = LevelMeter(voice_shell)
    app.hud_meter.configure(height=20)
    app.hud_meter.pack(fill="x", padx=14)
    app.hud_meter_label = _label(voice_shell, "ВХОД: НЕТ ДАННЫХ",
                                  fg=MUTED, size=8)
    app.hud_meter_label.pack(pady=(0, 5))

    transcript_shell = tk.Frame(shell, bg=SURFACE_ALT,
                                highlightthickness=1, highlightbackground=EDGE)
    transcript_shell.pack(fill="x", pady=(0, 7))
    _label(transcript_shell, "●  РАСПОЗНАННАЯ РЕЧЬ", fg=CYAN, size=8,
           bold=True).pack(anchor="w", padx=10, pady=(7, 1))
    app.hud_last_transcript = _label(
        transcript_shell, fg=TEXT, size=9, textvariable=app.hud_transcript,
        wraplength=404, justify="left", anchor="w", height=2)
    app.hud_last_transcript.pack(fill="x", padx=10, pady=(0, 7))

    buttons = tk.Frame(shell, bg=BG)
    buttons.pack(fill="x", pady=(0, 6))
    app.mic_toggle_button = _action(
        buttons, "МИКРОФОН", app.toggle_voice, primary=True, compact=True)
    app.mic_toggle_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
    app.hud_listen_button = _action(
        buttons, "◉  СЛУШАЙ / F9", app.f9, compact=True)
    app.hud_listen_button.pack(side="left", fill="x", expand=True)

    modes = tk.Frame(shell, bg=BG)
    modes.pack(fill="x", pady=(0, 6))
    app.hud_mode_buttons = {}
    for key, title in (("work", "РАБОТА"), ("gaming", "ИГРЫ"),
                       ("study", "УЧЁБА")):
        button = _action(modes, title,
                         lambda selected=key: app.activate_mode(selected),
                         compact=True)
        button.pack(side="left", fill="x", expand=True, padx=2)
        app.hud_mode_buttons[key] = button

    # Grow only the chat card on larger displays; chat and input remain usable
    # on 720px screens. No hidden horizontal second panel.
    card = tk.Frame(shell, bg=SURFACE, highlightthickness=1,
                    highlightbackground=EDGE)
    card.pack(fill="both", expand=True, pady=(0, 6))
    card_header = tk.Frame(card, bg=SURFACE)
    card_header.pack(fill="x", padx=10, pady=(8, 3))
    _label(card_header, "ДИАЛОГ С NOVA", fg=CYAN, bold=True,
           size=9).pack(side="left")
    app.hud_clock = _label(card_header, "--:--", fg=MUTED, size=9)
    app.hud_clock.pack(side="right")
    app.hud_status = _label(card, fg=MUTED, size=8,
                            textvariable=app.status, wraplength=390,
                            justify="left", anchor="w")
    app.hud_status.pack(fill="x", padx=11, pady=(0, 5))
    history_shell = tk.Frame(card, bg=SURFACE_ALT)
    history_shell.pack(fill="both", expand=True, padx=9, pady=(0, 8))
    app.history = tk.Text(history_shell, wrap="word", bg=SURFACE_ALT, fg=TEXT,
                          insertbackground=CYAN, selectbackground=CYAN_DIM,
                          relief="flat", font=("Segoe UI", 9), padx=9, pady=7,
                          state="disabled", undo=False, bd=0, height=7)
    app.history.pack(side="left", fill="both", expand=True)
    style = ttk.Style(app)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    style.configure("NOVA.Compact.Vertical.TScrollbar",
                    background=CYAN_DIM, troughcolor=SURFACE_ALT,
                    arrowcolor=TEXT, bordercolor=EDGE, relief="flat", width=8)
    scrollbar = ttk.Scrollbar(
        history_shell, orient="vertical",
        style="NOVA.Compact.Vertical.TScrollbar", command=app.history.yview)
    scrollbar.pack(side="right", fill="y")
    app.hud_scrollbar = scrollbar
    app.history.configure(yscrollcommand=scrollbar.set)
    for role, color in (("JARVIS", CYAN), ("Вы", GREEN), ("Система", MUTED),
                        ("Whisper", VIOLET), ("Профиль", AMBER)):
        app.history.tag_configure(role, foreground=color,
                                  font=("Segoe UI", 9, "bold"))
    app.history.tag_configure("error", foreground=AMBER)

    sendbar = tk.Frame(shell, bg=BG)
    sendbar.pack(fill="x", pady=(0, 6))
    app.entry = tk.Entry(sendbar, bg=SURFACE_ALT, fg=TEXT,
                         insertbackground=CYAN, selectbackground=CYAN_DIM,
                         relief="flat", bd=0, font=("Segoe UI", 10),
                         highlightthickness=1, highlightbackground=EDGE,
                         highlightcolor=CYAN)
    app.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 5))
    _action(sendbar, "➤", app.enter, primary=True, compact=True).pack(side="right")
    app.entry.bind("<Return>", app.enter)
    app.bind("<F9>", app.f9)
    app.bind("<Control-l>", lambda e: (app.entry.focus_set(), "break")[1])
    app.bind("<Control-Shift-M>", lambda e: (app.toggle_voice(), "break")[1])
    app.bind("<Control-Shift-R>", lambda e: (app.revoke(), "break")[1])

    footer = tk.Frame(shell, bg=BG)
    footer.pack(fill="x")
    app.hud_access = _label(footer, "УПРАВЛЕНИЕ: ЗАПРЕТ", size=8, fg=MUTED)
    app.hud_access.pack(side="left")
    app.hud_footer = _label(footer, "●  ЛОКАЛЬНО", fg=GREEN, size=8)
    app.hud_footer.pack(side="right")

    def tick():
        if getattr(app, "_closing", False):
            return
        try:
            speaking = bool(getattr(app.speaker, "busy", False) or
                            getattr(app.trimodal, "speaking", False))
            mode, label, color = visual_state(
                bool(getattr(app, "voice_enabled", False)), app.mic_state.get(),
                app.status.get(), bool(getattr(app, "executing", False)),
                speaking, time.monotonic() < getattr(
                    getattr(app, "voice", None), "until", 0))
            app.hud_mode.configure(text=label, fg=color)
            app.hud_clock.configure(text=time.strftime("%H:%M"))
            current = None
            if (app.voice_enabled and app.hud_level_at and
                    time.monotonic()-app.hud_level_at < 1.4):
                current = app.hud_level_value
            app.hud_meter.paint(current)
            _, reading = level_readout(current)
            app.hud_meter_label.configure(
                text="ВХОД: "+(reading if app.voice_enabled else "МИКРОФОН ВЫКЛ."),
                fg=GREEN if current is not None else MUTED)
            app.mic_toggle_button.configure(
                text="ВЫКЛ. МИКРОФОН" if app.voice_enabled else "ВКЛ. МИКРОФОН")
            engine = getattr(app, "engine", "bundled")
            app.hud_engine.configure(
                text={"bundled": "QWEN · ЛОКАЛЬНО", "none": "КОМАНДЫ · ОФЛАЙН",
                      "ollama": "OLLAMA · ВНЕШН.", "openai": "OPENAI · СЕТЬ",
                      "anthropic": "CLAUDE · СЕТЬ"}.get(engine, "AI"),
                fg=GREEN if engine in ("bundled", "none") else AMBER)
            current_mode = getattr(getattr(app, "modes", None), "mode", "neutral")
            if getattr(app, "_hud_selected", None) != current_mode:
                app._hud_selected = current_mode
                for key, btn in app.hud_mode_buttons.items():
                    btn.configure(bg=CYAN_DIM if key == current_mode else SURFACE_ALT)
            allowed = bool(getattr(app, "control_allowed", False))
            vision = bool(getattr(app, "vision_allowed", False))
            app.hud_access.configure(
                text=("ПК: ДОСТУП" if allowed else "ПК: ЗАПРЕТ") +
                     (" · ЭКРАН: ДОСТУП" if vision else " · ЭКРАН: ЗАПРЕТ"),
                fg=AMBER if (allowed or vision) else MUTED)
            app.hud_footer.configure(text="●  "+label, fg=color)
            if (app.hud_animate.get() or not app.hud_reactor._painted or
                    app.hud_reactor._mode != mode):
                app.hud_reactor.paint(mode, current)
            app._nova_after_id = app.after(170, tick)
        except tk.TclError:
            return

    def stop_tick(event):
        if event.widget is not app:
            return
        current = getattr(app, "_nova_after_id", None)
        if current is not None:
            try:
                app.after_cancel(current)
            except tk.TclError:
                pass
            app._nova_after_id = None
    app.bind("<Destroy>", stop_tick, add="+")
    tick()
