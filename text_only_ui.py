# -*- coding: utf-8 -*-
"""Compact keyboard-only interface; no microphone/listen/voice UI."""
from __future__ import annotations
import time
import tkinter as tk
from tkinter import ttk
from nova_ui import BG, SURFACE, SURFACE_ALT, EDGE, CYAN, CYAN_DIM
from nova_ui import GREEN, MUTED, TEXT, AMBER, VIOLET, Reactor, _label, _action
from intuitive_start import QUICK_ACTIONS, model_hint


def engine_badge(engine: str, model_ready: bool):
    """Keep the HUD truthful: selecting local Qwen does not install it."""
    if engine == "bundled":
        return (("QWEN · ЛОКАЛЬНО", GREEN) if model_ready
                else ("QWEN · НЕ ПОДКЛЮЧЕНА", AMBER))
    labels = {
        "none": ("КОМАНДЫ · ОФЛАЙН", GREEN),
        "ollama": ("OLLAMA · ЛОКАЛЬНО", AMBER),
        "freellm": ("FREELLM · МОДЕЛИ", AMBER),
        "openai": ("OPENAI · СЕТЬ", AMBER),
        "anthropic": ("CLAUDE · СЕТЬ", AMBER),
    }
    return labels.get(engine, ("AI · НЕ ВЫБРАН", AMBER))


def build_text_interface(app):
    app.configure(bg=BG)
    app.status = tk.StringVar(master=app, value="Готов к переписке.")
    app.hud_animate = tk.BooleanVar(master=app, value=True)
    app._nova_after_id = None
    shell = tk.Frame(app, bg=BG)
    shell.pack(fill="both", expand=True, padx=10, pady=7)
    header = tk.Frame(shell, bg=BG)
    header.pack(fill="x", pady=(0, 5))
    title = tk.Frame(header, bg=BG)
    title.pack(side="left", expand=True, fill="x")
    _label(title, "JARVIS NOVA", fg=TEXT, size=14, bold=True).pack(anchor="w")
    _label(title, "ВЫБЕРИ ЗАДАЧУ ИЛИ НАПИШИ СВОЮ", fg=CYAN_DIM, size=8).pack(anchor="w")
    app.hud_settings_button = _action(header, "⚙ НАСТРОЙКИ", app.show_settings_menu, compact=True)
    app.hud_settings_button.pack(side="right", padx=(6, 0))

    # The primary tasks are visible on the very first launch. Every button
    # opens an existing editor; it never grants permission, writes files or
    # initiates exporting by itself. Keep two equal columns on narrow screens.
    start = tk.Frame(shell, bg=SURFACE, highlightbackground=EDGE,
                     highlightthickness=1)
    start.pack(fill="x", pady=(0, 8))
    _label(start, "С ЧЕГО НАЧАТЬ?", fg=CYAN, size=9, bold=True).pack(
        anchor="w", padx=10, pady=(7, 4))
    actions = tk.Frame(start, bg=SURFACE)
    actions.pack(fill="x", padx=8, pady=(0, 8))
    for column in range(2):
        actions.grid_columnconfigure(column, weight=1, uniform="quick")
    callbacks = {
        "video": lambda: app.open_viral_studio(stage="audience"),
        "edit": app.open_timeline,
        "code": lambda: app.open_code_assistant(
            "python", "", auto_start=False),
        "image": app.open_screenshot_review,
    }
    app.hud_quick_actions = {}
    for index, (label, key) in enumerate(QUICK_ACTIONS):
        button = _action(actions, label, callbacks[key],
                         primary=index == 0, compact=True)
        button.grid(row=index // 2, column=index % 2, sticky="ew",
                    padx=3, pady=3)
        app.hud_quick_actions[key] = button

    # A minimal, visible setup route: users must not guess hidden exact phrases.
    # Each action is a safe, explicit controller method; network/model setup
    # still requires an independent affirmative confirmation dialog.
    modelbar = tk.Frame(shell, bg=BG)
    modelbar.pack(fill="x", pady=(0, 4))
    app.hud_find_models = _action(
        modelbar, "НАЙТИ МОДЕЛИ", app.scan_models_on_pc, compact=True)
    app.hud_find_models.pack(side="left", padx=(0, 6))
    app.hud_download_qwen = _action(
        modelbar, "СКАЧАТЬ QWEN", lambda: app.check_models(offer_scan=False),
        compact=True)
    app.hud_download_qwen.pack(side="left", padx=(0, 6))
    app.hud_cancel_scan = _action(
        modelbar, "СТОП ПОИСК", app.cancel_model_scan, compact=True)
    # Screen consent and actual screenshot selection are distinct operations.
    # Granting vision does NOT silently start capturing or watching the desktop.
    screenbar = tk.Frame(shell, bg=BG)
    screenbar.pack(fill="x", pady=(0, 4))
    app.hud_enable_screen = _action(
        screenbar, "РАЗРЕШИТЬ ЭКРАН", app.grant_vision, compact=True)
    app.hud_enable_screen.pack(side="left", padx=(0, 6))
    app.hud_show_screenshot = _action(
        screenbar, "ПОКАЗАТЬ СКРИНШОТ", app.open_screenshot_review, compact=True)
    app.hud_show_screenshot.pack(side="left", padx=(0, 6))
    # Keep old references for callers, without adding unrelated toolbar items.
    app.hud_update_button = _action(header, "⟳", app.show_update_center, compact=True)
    app.hud_minimize_button = _action(header, "▁", app.hide_main, compact=True)
    hub = tk.Frame(shell, bg=SURFACE, highlightthickness=1, highlightbackground=EDGE)
    hub.pack(fill="x", pady=(0, 8))
    bar = tk.Frame(hub, bg=SURFACE)
    bar.pack(fill="x", padx=12, pady=(9, 0))
    app.hud_mode = _label(bar, "ГОТОВ К ТЕКСТУ", fg=GREEN, size=10, bold=True)
    app.hud_mode.pack(side="left")
    from model_storage import local_model_available
    loaded=local_model_available(app._asset_root)
    app._local_model_ready = loaded
    engine_label,engine_color=engine_badge(getattr(app,"engine","bundled"),loaded)
    app.hud_engine = _label(bar,engine_label,fg=engine_color,size=8)
    app.hud_engine.pack(side="right")
    app.hud_model_hint = _label(
        hub, model_hint(loaded), fg=GREEN if loaded else AMBER,
        size=8, justify="left", anchor="w", wraplength=345)
    app.hud_model_hint.pack(fill="x", padx=11, pady=(5, 5))
    # Leave room for the task choices and the actual conversation.
    app.hud_reactor = Reactor(hub)
    # Keep the legacy status widget for compatibility but do not display the
    # decorative canvas in Lite: on a 390x600 laptop it pushed text entry off
    # the screen. Real task controls and the message box take priority.
    # Modes are now selected by chat (or by the optional F10 palette).
    app.hud_mode_buttons = {}
    card = tk.Frame(shell,bg=SURFACE,highlightthickness=1,highlightbackground=EDGE)
    card.pack(fill="both",expand=True,pady=(0,7))
    titlebar = tk.Frame(card,bg=SURFACE)
    titlebar.pack(fill="x",padx=10,pady=(8,4))
    _label(titlebar,"ДИАЛОГ С JARVIS",fg=CYAN,bold=True,size=9).pack(side="left")
    app.hud_clock = _label(titlebar,"--:--",fg=MUTED,size=9)
    app.hud_clock.pack(side="right")
    # Visible cancellation while Qwen is downloading: users should not
    # have to search a nested settings menu when the network stalls.
    app.hud_cancel_model = _action(
        titlebar,"СТОП QWEN",app.cancel_local_model_download,compact=True)
    app.hud_status = _label(card,fg=MUTED,size=9,textvariable=app.status,
                            wraplength=392,justify="left",anchor="w")
    app.hud_status.pack(fill="x",padx=10,pady=(0,6))
    body = tk.Frame(card,bg=SURFACE_ALT)
    body.pack(fill="both",expand=True,padx=9,pady=(0,8))
    app.history = tk.Text(body,wrap="word",bg=SURFACE_ALT,fg=TEXT,
        insertbackground=CYAN,selectbackground=CYAN_DIM,relief="flat",
        font=("Segoe UI",10),padx=9,pady=7,state="disabled",undo=False,bd=0,height=4)
    app.history.pack(side="left",fill="both",expand=True)
    bar = ttk.Scrollbar(body,orient="vertical",command=app.history.yview)
    bar.pack(side="right",fill="y")
    app.history.configure(yscrollcommand=bar.set)
    for role,color in (("JARVIS",CYAN),("Вы",GREEN),("Система",MUTED),("Профиль",AMBER)):
        app.history.tag_configure(role,foreground=color,font=("Segoe UI",9,"bold"))
    app.history.tag_configure("error",foreground=AMBER)
    _label(shell, "ИЛИ НАПИШИ СВОИМИ СЛОВАМИ И НАЖМИ ENTER",
           fg=CYAN_DIM,size=8).pack(anchor="w",pady=(0,4))
    writer = tk.Frame(shell,bg=BG)
    writer.pack(fill="x",pady=(0,7))
    app.entry = tk.Entry(writer,bg=SURFACE_ALT,fg=TEXT,insertbackground=CYAN,
        selectbackground=CYAN_DIM,relief="flat",bd=0,font=("Segoe UI",11),
        highlightthickness=1,highlightbackground=EDGE,highlightcolor=CYAN)
    app.entry.pack(side="left",fill="x",expand=True,ipady=9)
    # Enter sends the text. The screenshot editor opens via chat.
    app.entry.bind("<Return>",app.enter)
    app.bind("<Control-l>",lambda e:(app.entry.focus_set(),"break")[1])
    app.bind("<F9>",app.f9)
    app.bind("<Control-Shift-R>",lambda e:(app.revoke(),"break")[1])
    footer = tk.Frame(shell,bg=BG)
    footer.pack(fill="x")
    app.hud_access = _label(footer,"ПК: ЗАПРЕТ",size=8,fg=MUTED)
    app.hud_access.pack(side="left")
    app.hud_footer = _label(footer,"●  ПЕЧАТАЙ СООБЩЕНИЕ",fg=GREEN,size=8)
    app.hud_footer.pack(side="right")

    def tick():
        if getattr(app,"_closing",False):
            return
        try:
            busy=bool(getattr(app,"executing",False))
            mode,label,color=(("processing","ОБРАБОТКА ТЕКСТА",VIOLET)
                               if busy else ("ready","ГОТОВ К ТЕКСТУ",GREEN))
            if not busy and getattr(app,"_debate_mode",False):
                label="РЕЖИМ СПОРА"
            app.hud_mode.configure(text=label,fg=color)
            app.hud_clock.configure(text=time.strftime("%H:%M"))
            if getattr(app, "_model_scan_busy", False):
                if not app.hud_cancel_scan.winfo_manager():
                    app.hud_cancel_scan.pack(side="left", padx=(0, 6))
            elif app.hud_cancel_scan.winfo_manager():
                app.hud_cancel_scan.pack_forget()
            if getattr(app,"_model_download_busy",False):
                if not app.hud_cancel_model.winfo_manager():
                    app.hud_cancel_model.pack(side="right",padx=(2,8))
            elif app.hud_cancel_model.winfo_manager():
                app.hud_cancel_model.pack_forget()
            engine=getattr(app,"engine","bundled")
            engine_label,engine_color=engine_badge(
                engine,getattr(app,"_local_model_ready",False))
            app.hud_engine.configure(text=engine_label,fg=engine_color)
            app.hud_model_hint.configure(
                text=model_hint(getattr(app,"_local_model_ready",False),
                                getattr(app,"_model_download_busy",False)),
                fg=GREEN if getattr(app,"_local_model_ready",False) else AMBER)
            selected=getattr(getattr(app,"modes",None),"mode","neutral")
            if getattr(app,"_hud_selected",None)!=selected:
                app._hud_selected=selected
                for key,btn in app.hud_mode_buttons.items():
                    btn.configure(bg=CYAN_DIM if key==selected else SURFACE_ALT)
            allowed=bool(getattr(app,"control_allowed",False))
            vision=bool(getattr(app,"vision_allowed",False))
            app.hud_access.configure(
                text=("ПК: ДОСТУП" if allowed else "ПК: ЗАПРЕТ")+
                     (" · ЭКРАН: ДОСТУП" if vision else " · ЭКРАН: ЗАПРЕТ"),
                fg=AMBER if (allowed or vision) else MUTED)
            app.hud_footer.configure(text="●  "+label,fg=color)
            if app.hud_reactor.winfo_manager() and (
                    app.hud_animate.get() or not app.hud_reactor._painted
                    or app.hud_reactor._mode!=mode):
                app.hud_reactor.paint(mode,None)
            app._nova_after_id=app.after(190,tick)
        except tk.TclError:
            return
    def stop_tick(event):
        if event.widget is not app:
            return
        pending=app._nova_after_id
        if pending is not None:
            try:
                app.after_cancel(pending)
            except tk.TclError:
                pass
            app._nova_after_id=None
    app.bind("<Destroy>",stop_tick,add="+")
    tick()
