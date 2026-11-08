# -*- coding: utf-8 -*-
"""Compact keyboard-only interface; no microphone/listen/voice UI."""
from __future__ import annotations
import time
import tkinter as tk
from tkinter import ttk
from nova_ui import BG, SURFACE, SURFACE_ALT, EDGE, CYAN, CYAN_DIM
from nova_ui import GREEN, MUTED, TEXT, AMBER, VIOLET, Reactor, _label, _action


def build_text_interface(app):
    app.configure(bg=BG)
    app.status = tk.StringVar(master=app, value="Готов к переписке.")
    app.hud_animate = tk.BooleanVar(master=app, value=True)
    app._nova_after_id = None
    shell = tk.Frame(app, bg=BG)
    shell.pack(fill="both", expand=True, padx=12, pady=11)
    header = tk.Frame(shell, bg=BG)
    header.pack(fill="x", pady=(0, 9))
    title = tk.Frame(header, bg=BG)
    title.pack(side="left", expand=True, fill="x")
    _label(title, "JARVIS NOVA", fg=TEXT, size=14, bold=True).pack(anchor="w")
    _label(title, "ТОЛЬКО ТЕКСТ · ЛОКАЛЬНО", fg=CYAN_DIM, size=8).pack(anchor="w")
    app.hud_settings_button = _action(header, "⚙", app.show_settings_menu, compact=True)
    app.hud_settings_button.pack(side="right", padx=4)
    app.hud_update_button = _action(header, "⟳", app.show_update_center, compact=True)
    app.hud_update_button.pack(side="right", padx=3)
    app.hud_minimize_button = _action(header, "▁", app.hide_main, compact=True)
    app.hud_minimize_button.pack(side="right")
    hub = tk.Frame(shell, bg=SURFACE, highlightthickness=1, highlightbackground=EDGE)
    hub.pack(fill="x", pady=(0, 8))
    bar = tk.Frame(hub, bg=SURFACE)
    bar.pack(fill="x", padx=12, pady=(9, 0))
    app.hud_mode = _label(bar, "ГОТОВ К ТЕКСТУ", fg=GREEN, size=10, bold=True)
    app.hud_mode.pack(side="left")
    app.hud_engine = _label(bar, "QWEN · ЛОКАЛЬНО", fg=GREEN, size=8)
    app.hud_engine.pack(side="right")
    app.hud_reactor = Reactor(hub)
    app.hud_reactor.configure(height=105)
    app.hud_reactor.pack(fill="x", padx=7, pady=(0, 8))
    modes = tk.Frame(shell, bg=BG)
    modes.pack(fill="x", pady=(0, 7))
    app.hud_mode_buttons = {}
    for key, label in (("work","РАБОТА"),("gaming","ИГРЫ"),("study","УЧЁБА")):
        btn = _action(modes,label,lambda v=key:app.activate_mode(v),compact=True)
        btn.pack(side="left",fill="x",expand=True,padx=2)
        app.hud_mode_buttons[key] = btn
    card = tk.Frame(shell,bg=SURFACE,highlightthickness=1,highlightbackground=EDGE)
    card.pack(fill="both",expand=True,pady=(0,7))
    titlebar = tk.Frame(card,bg=SURFACE)
    titlebar.pack(fill="x",padx=10,pady=(8,4))
    _label(titlebar,"ПЕРЕПИСКА С NOVA",fg=CYAN,bold=True,size=9).pack(side="left")
    app.hud_clock = _label(titlebar,"--:--",fg=MUTED,size=9)
    app.hud_clock.pack(side="right")
    app.hud_status = _label(card,fg=MUTED,size=9,textvariable=app.status,
                            wraplength=392,justify="left",anchor="w")
    app.hud_status.pack(fill="x",padx=10,pady=(0,6))
    body = tk.Frame(card,bg=SURFACE_ALT)
    body.pack(fill="both",expand=True,padx=9,pady=(0,8))
    app.history = tk.Text(body,wrap="word",bg=SURFACE_ALT,fg=TEXT,
        insertbackground=CYAN,selectbackground=CYAN_DIM,relief="flat",
        font=("Segoe UI",10),padx=9,pady=7,state="disabled",undo=False,bd=0,height=8)
    app.history.pack(side="left",fill="both",expand=True)
    bar = ttk.Scrollbar(body,orient="vertical",command=app.history.yview)
    bar.pack(side="right",fill="y")
    app.history.configure(yscrollcommand=bar.set)
    for role,color in (("JARVIS",CYAN),("Вы",GREEN),("Система",MUTED),("Профиль",AMBER)):
        app.history.tag_configure(role,foreground=color,font=("Segoe UI",9,"bold"))
    app.history.tag_configure("error",foreground=AMBER)
    writer = tk.Frame(shell,bg=BG)
    writer.pack(fill="x",pady=(0,7))
    app.entry = tk.Entry(writer,bg=SURFACE_ALT,fg=TEXT,insertbackground=CYAN,
        selectbackground=CYAN_DIM,relief="flat",bd=0,font=("Segoe UI",11),
        highlightthickness=1,highlightbackground=EDGE,highlightcolor=CYAN)
    app.entry.pack(side="left",fill="x",expand=True,ipady=9,padx=(0,6))
    _action(writer,"ОТПРАВИТЬ",app.enter,primary=True,compact=True).pack(side="right")
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
            app.hud_mode.configure(text=label,fg=color)
            app.hud_clock.configure(text=time.strftime("%H:%M"))
            engine=getattr(app,"engine","bundled")
            app.hud_engine.configure(text={
                "bundled":"QWEN · ЛОКАЛЬНО","none":"КОМАНДЫ · ОФЛАЙН",
                "ollama":"OLLAMA · ЛОКАЛЬНО","freellm":"FREELLM · МОДЕЛИ",
                "openai":"OPENAI · СЕТЬ",
                "anthropic":"CLAUDE · СЕТЬ"}.get(engine,"AI"),
                fg=GREEN if engine in ("bundled","none") else AMBER)
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
            if app.hud_animate.get() or not app.hud_reactor._painted or app.hud_reactor._mode!=mode:
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
