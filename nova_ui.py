# -*- coding: utf-8 -*-
"""JARVIS NOVA desktop HUD: entirely local, dependency-free Tkinter graphics.

The visual layer never starts devices, grants permissions or performs actions.
Those remain in Jarvis callbacks; animation runs only on Tk's event loop.
"""
import math
import time
import tkinter as tk

BG = "#070D17"
SURFACE = "#0D1929"
SURFACE_ALT = "#112238"
EDGE = "#20364B"
CYAN = "#4DE4F7"
CYAN_DIM = "#236C80"
TEXT = "#E9F6FF"
MUTED = "#85A3B8"
GREEN = "#56EBB0"
AMBER = "#FFC86C"
RED = "#FF7889"
VIOLET = "#B8A4FF"


def visual_state(voice_enabled, mic_state, status, executing=False, speaking=False, listening=None):
    """Pure state resolver. A status message cannot turn a stopped mic 'on'."""
    mic = str(mic_state).casefold()
    event = str(status).casefold()
    if "ошибка микрофона" in event or "ошибка устройства" in mic:
        return "error", "ОШИБКА ВХОДА", RED
    if executing:
        return "processing", "ОБРАБОТКА", VIOLET
    if speaking:
        return "speaking", "ОТВЕЧАЮ", GREEN
    if not voice_enabled:
        return "offline", "МИКРОФОН ВЫКЛ.", MUTED
    if listening is True:
        return "listening", "СЛУШАЮ", CYAN
    if listening is None and ("жду команду" in mic or "слушаю команду" in event
                              or "распозна" in event or "whisper" in event):
        return "listening", "СЛУШАЮ", CYAN
    if "подключ" in mic or "запуска" in event:
        return "starting", "ЗАПУСК МИКРОФОНА", AMBER
    return "ready", "ЖДУ «ДЖАРВИС»", GREEN



def level_readout(level):
    """Compute a true RMS display; None means no recent microphone frames."""
    if level is None:
        return 0.0, "НЕТ ДАННЫХ"
    value = float(level)
    if not math.isfinite(value):
        return 0.0, "НЕТ ДАННЫХ"
    value = max(0.0,min(1.0,value))
    db = 20*math.log10(max(1e-6,value))
    intensity = max(0.0,min(1.0,(db+65)/60))
    return intensity, "ТИШИНА" if db < -80 else f"{db:.0f} dBFS"


class LevelMeter(tk.Canvas):
    """Actual level meter; bars represent RMS dBFS, not a simulated waveform."""
    def __init__(self,parent):
        super().__init__(parent,width=215,height=30,bg=SURFACE,
                         highlightthickness=0,bd=0)
        self.last_fraction=0.0

    def paint(self,level):
        fraction,_=level_readout(level)
        self.last_fraction=fraction
        self.delete("meter")
        width=max(2,self.winfo_width())
        height=max(2,self.winfo_height())
        bars=22
        usable=max(2,width-4)
        for index in range(bars):
            x1=2+(index*(usable/bars))
            x2=2+((index+1)*(usable/bars))-3
            fill=(GREEN if index<bars*.67 else
                  AMBER if index<bars*.85 else RED)
            if (index+.5)/bars > fraction:
                fill=EDGE
            self.create_rectangle(x1,5,x2,height-5,fill=fill,
                                  outline="",tags="meter")

class Reactor(tk.Canvas):
    """Animated vector reactor: no assets, network, blocking loops or GPU."""

    def __init__(self, parent):
        super().__init__(parent, width=230, height=192, bg=SURFACE,
                         highlightthickness=0, bd=0)
        self.phase = 0
        self._mode = "offline"
        self._painted = False
        self.last_energy = 0.0
        self.bind("<Configure>",lambda event:setattr(self,"_painted",False),add="+")

    def paint(self, mode, level=None):
        if not self.winfo_exists() or not self.winfo_viewable():
            return
        self._mode = mode
        self.last_energy,_ = level_readout(level)
        self.phase = (self.phase + (3 if mode == "listening" else 1) +
                      4*self.last_energy) % 360
        self.delete("hud")
        self._painted = True
        w = max(2, self.winfo_width())
        h = max(2, self.winfo_height())
        cx, cy = w / 2, h / 2
        r = min(w * .41, h * .45, 95)
        color = {
            "offline": MUTED, "error": RED, "processing": VIOLET,
            "speaking": GREEN, "listening": CYAN, "starting": AMBER,
            "ready": CYAN,
        }.get(mode, CYAN)
        self.create_oval(cx-r*.95, cy-r*.95, cx+r*.95, cy+r*.95,
                         outline=EDGE, width=1, tags="hud")
        self.create_oval(cx-r*.74, cy-r*.74, cx+r*.74, cy+r*.74,
                         outline=CYAN_DIM, width=1, tags="hud")
        self.create_oval(cx-r*.49, cy-r*.49, cx+r*.49, cy+r*.49,
                         outline=color, width=2, tags="hud")
        for index in range(48):
            angle=math.radians(index*7.5)
            inner=r*(.88 if index % 4 else .82)
            outer=r*(.96 if index % 4 else 1.02)
            self.create_line(cx+inner*math.cos(angle),
                             cy+inner*math.sin(angle),
                             cx+outer*math.cos(angle),
                             cy+outer*math.sin(angle),
                             fill=color if index%4==0 else EDGE,
                             width=2 if index%4==0 else 1,tags="hud")
        for radius, start, extent, shade, width in (
            (.83, self.phase, 74, color, 3),
            (.83, (self.phase+185)%360, 40, CYAN_DIM, 2),
            (.61, (360-self.phase*1.5)%360, 130, color, 2),
            (1.08, (self.phase*.6)%360, 40, CYAN_DIM, 1),
        ):
            rr=r*radius
            self.create_arc(cx-rr,cy-rr,cx+rr,cy+rr,
                            start=start,extent=extent,style=tk.ARC,
                            outline=shade,width=width,tags="hud")
        pulse = (math.sin(math.radians(self.phase*4))+1)/2
        core = r*(.28 + .12*self.last_energy +
                  (.04*pulse if mode in ("listening","speaking") else 0))
        self.create_oval(cx-core,cy-core,cx+core,cy+core,
                         fill=SURFACE_ALT,outline=color,width=2,tags="hud")
        self.create_text(cx,cy-7,text="N",fill=TEXT,
                         font=("Segoe UI",23,"bold"),tags="hud")
        self.create_text(cx,cy+17,text="N O V A",fill=color,
                         font=("Consolas",8,"bold"),tags="hud")
        for dx,dy in ((-r*1.18,0),(r*1.18,0)):
            self.create_line(cx+dx-5,cy+dy,cx+dx+5,cy+dy,
                             fill=CYAN_DIM,tags="hud")


def _label(parent, text="", *, fg=MUTED, size=9, bold=False, **kw):
    return tk.Label(parent,text=text,fg=fg,bg=parent.cget("bg"),
                    font=("Segoe UI",size,"bold" if bold else "normal"),
                    **kw)


def _action(parent,text,command,*,primary=False,compact=False):
    background = CYAN_DIM if primary else SURFACE_ALT
    hover = "#32849A" if primary else "#1B3650"
    foreground = TEXT if primary else "#D7EAF5"
    button=tk.Button(parent,text=text,command=command,
                     bg=background,fg=foreground,
                     activebackground=hover,activeforeground="#FFFFFF",
                     relief="flat",bd=0,highlightthickness=1,
                     highlightbackground=EDGE,highlightcolor=CYAN,
                     cursor="hand2",takefocus=True,
                     font=("Segoe UI",9 if compact else 10,"bold"),
                     padx=7,pady=5 if compact else 7)
    button.bind("<Enter>",lambda e:button.configure(bg=hover),add="+")
    button.bind("<Leave>",lambda e:button.configure(bg=background),add="+")
    return button


def build_interface(app):
    """Create the complete dashboard while preserving Jarvis' public widgets."""
    app.configure(bg=BG)
    app.status=tk.StringVar(master=app,value="Запускаю офлайн-голос…")
    app.mic_state=tk.StringVar(master=app,value="Микрофон: подключается…")
    app.hud_transcript=tk.StringVar(master=app,value="РАСПОЗНАНО: ожидаю команду…")
    app.hud_animate=tk.BooleanVar(master=app,value=True)
    app.hud_level_value=0.0
    app.hud_level_at=0.0

    body=tk.Frame(app,bg=BG)
    body.pack(fill="both",expand=True,padx=20,pady=(12,9))

    rail=tk.Frame(body,bg=SURFACE,width=286,highlightthickness=1,
                  highlightbackground=EDGE)
    rail.pack(side="left",fill="y",padx=(0,12))
    rail.pack_propagate(False)
    app.hud_rail=rail
    # NOVA identity and access status now live in the LEFT rail.
    header=tk.Frame(rail,bg=SURFACE)
    header.pack(fill="x",padx=12,pady=(9,2))
    tk.Frame(header,bg=CYAN,width=3).pack(side="left",fill="y",padx=(0,9))
    brand=tk.Frame(header,bg=SURFACE)
    brand.pack(side="left",anchor="w")
    _label(brand,"NEURAL VOICE  /  OFFLINE",fg=CYAN_DIM,size=8,bold=True).pack(anchor="w")
    _label(brand,"JARVIS  NOVA",fg=TEXT,size=17,bold=True).pack(anchor="w")
    meta=tk.Frame(rail,bg=SURFACE)
    meta.pack(fill="x",padx=14,pady=(0,2))
    app.hud_clock=_label(meta,"--:--:--",fg=TEXT,size=10,bold=True)
    app.hud_clock.pack(side="left")
    app.hud_engine=_label(meta,"QWEN  /  ЛОКАЛЬНО",fg=GREEN,size=8,bold=True)
    app.hud_engine.pack(side="right")
    app.hud_access=_label(rail,"УПРАВЛЕНИЕ: ЗАПРЕТ  /  ЗРЕНИЕ*: ЗАПРЕТ",
                           fg=MUTED,size=7,bold=True)
    app.hud_access.pack(anchor="w",padx=14,pady=(0,3))
    # All advanced commands live here, not in Windows' pale native top menu.
    app.hud_settings_button=_action(
        rail,"⚙  НАСТРОЙКИ  /  F10",lambda:app.show_settings_menu(),
        compact=True)
    app.hud_settings_button.pack(fill="x",padx=13,pady=(2,5))
    tk.Frame(rail,bg=CYAN_DIM,height=1).pack(fill="x",padx=13,pady=(0,3))
    rail_top=tk.Frame(rail,bg=SURFACE)
    rail_top.pack(fill="x",padx=14,pady=(3,0))
    _label(rail_top,"01  /  ГОЛОСОВОЕ ЯДРО",fg=CYAN,size=9,bold=True).pack(anchor="w")
    app.hud_reactor=Reactor(rail)
    app.hud_reactor.pack(fill="x",padx=6,pady=(1,0))
    app.hud_mode=_label(rail,"ЗАГРУЗКА",fg=GREEN,size=11,bold=True)
    app.hud_mode.pack(anchor="center",pady=(0,3))
    app.hud_mic=_label(rail,fg=MUTED,size=9,justify="center",
                       wraplength=226,textvariable=app.mic_state)
    app.hud_mic.pack(fill="x",padx=10,pady=(0,5))
    app.hud_meter=LevelMeter(rail)
    app.hud_meter.pack(fill="x",padx=13,pady=(0,0))
    app.hud_meter_label=_label(rail,"ВХОД: НЕТ ДАННЫХ",fg=MUTED,size=8)
    app.hud_meter_label.pack(anchor="center",pady=(0,8))
    _label(rail,"ЗВУК НЕ СОХРАНЯЕТСЯ",fg=CYAN_DIM,size=8).pack(
        anchor="center",pady=(0,2))
    app.hud_last_transcript=_label(
        rail,fg=CYAN,size=8,justify="left",anchor="w",
        wraplength=256,height=2,textvariable=app.hud_transcript)
    app.hud_last_transcript.pack(fill="x",padx=11,pady=(1,4))

    controls=tk.Frame(rail,bg=SURFACE)
    controls.pack(fill="x",padx=11)
    def resize_rail(event):
        target=95 if event.height<650 else 133
        if int(app.hud_reactor.cget("height"))!=target:
            app.hud_reactor.configure(height=target)
    rail.bind("<Configure>",resize_rail,add="+")
    app.mic_toggle_button=_action(controls,"МИКРОФОН",app.toggle_voice,primary=True)
    app.mic_toggle_button.pack(fill="x",pady=(0,6))
    _action(controls,"ВЫБРАТЬ УСТРОЙСТВО",app.select_microphone,
            compact=True).pack(fill="x",pady=(0,6))
    _action(controls,"ТЕСТ СИГНАЛА",app.test_microphone,
            compact=True).pack(fill="x",pady=(0,6))
    _action(controls,"◉  СЛУШАЙ  /  F9",lambda:app.f9(),
            compact=True).pack(fill="x",pady=(0,5))
    _label(controls,"ЧУВСТВИТЕЛЬНОСТЬ",fg=CYAN_DIM,size=8,bold=True).pack(anchor="w")
    app.hud_sensitivity_readout=_label(controls,"1.00×  /  ТИХАЯ РЕЧЬ",
                                       fg=MUTED,size=8)
    def update_sensitivity(value):
        level=round(float(value),2)
        if hasattr(app,"voice") and hasattr(app.voice,"set_sensitivity"):
            app.voice.set_sensitivity(level)
        app.hud_sensitivity_readout.configure(text=f"{level:.2f}×  /  ТИХАЯ РЕЧЬ")
    app.hud_sensitivity_var=tk.DoubleVar(master=app,value=1.0)
    app.hud_sensitivity_var.trace_add(
        "write",lambda *_:update_sensitivity(app.hud_sensitivity_var.get()))
    app.hud_sensitivity=tk.Scale(controls,from_=0.75,to=2.0,resolution=.05,
        orient="horizontal",variable=app.hud_sensitivity_var,
        bg=SURFACE,fg=TEXT,activebackground=CYAN_DIM,
        highlightthickness=0,bd=0,troughcolor=EDGE,showvalue=False,length=220)
    app.hud_sensitivity.pack(fill="x",pady=(0,0))
    app.hud_sensitivity_readout.pack(anchor="w",pady=(0,3))
    app.hud_sensitivity.set(1.0)


    main=tk.Frame(body,bg=SURFACE,highlightthickness=1,highlightbackground=EDGE)
    main.pack(side="left",fill="both",expand=True)
    app.hud_chat=main
    main.grid_columnconfigure(0,weight=1)
    main.grid_rowconfigure(2,weight=1)
    main.grid_rowconfigure(3,weight=0)

    panel=tk.Frame(main,bg=SURFACE)
    panel.grid(row=0,column=0,sticky="ew",padx=14,pady=(11,0))
    _label(panel,"02  /  ЦЕНТР КОММУНИКАЦИЙ",
           fg=CYAN,size=9,bold=True).pack(side="left")
    _label(panel,"WHISPER / QWEN / SILERO",fg=MUTED,size=8).pack(side="right")

    app.hud_status=_label(main,fg=MUTED,size=9,textvariable=app.status,
                          wraplength=580,justify="left",anchor="w",height=2)
    app.hud_status.grid(row=1,column=0,sticky="ew",padx=14,pady=(4,6))
    chat_shell=tk.Frame(main,bg=SURFACE_ALT,highlightthickness=1,
                        highlightbackground=EDGE)
    chat_shell.grid(row=2,column=0,sticky="nsew",padx=12,pady=(0,9))
    chat_shell.grid_rowconfigure(0,weight=1)
    chat_shell.grid_columnconfigure(0,weight=1)
    app.history=tk.Text(chat_shell,wrap="word",bg=SURFACE_ALT,fg=TEXT,
                        insertbackground=CYAN,selectbackground=CYAN_DIM,
                        relief="flat",font=("Segoe UI",10),padx=13,pady=11,
                        state="disabled",undo=False,borderwidth=0)
    app.history.grid(row=0,column=0,sticky="nsew")
    # Use themed ttk+clam rather than native Windows Tk Scrollbar,
    # which is bright white even when bg/troughcolor are dark.
    from tkinter import ttk
    theme=ttk.Style(app)
    theme_name="NOVA.Dark.Vertical.TScrollbar"
    theme.theme_use("clam") if theme.theme_use()!="clam" else None
    theme.configure(theme_name,
                    background=CYAN_DIM,foreground=TEXT,
                    troughcolor=SURFACE_ALT,arrowcolor=TEXT,
                    bordercolor=EDGE,lightcolor=SURFACE_ALT,
                    darkcolor=SURFACE_ALT,relief="flat",width=9)
    theme.map(theme_name,background=[("active",CYAN)])
    scroll=ttk.Scrollbar(chat_shell,orient="vertical",
                         style=theme_name,command=app.history.yview)
    scroll.grid(row=0,column=1,sticky="ns")
    app.hud_scrollbar=scroll
    app.history.configure(yscrollcommand=scroll.set)
    for name,color in (("JARVIS",CYAN),("Вы",GREEN),("Система",MUTED),
                       ("Whisper",VIOLET),("Профиль",AMBER)):
        app.history.tag_configure(name,foreground=color,
                                  font=("Segoe UI",10,"bold"))
    app.history.tag_configure("error",foreground=RED,
                              font=("Segoe UI",10,"bold"))

    sendbar=tk.Frame(main,bg=SURFACE)
    sendbar.grid(row=3,column=0,sticky="ew",padx=12,pady=(0,11))
    sendbar.grid_columnconfigure(0,weight=1)
    app.entry=tk.Entry(sendbar,bg=SURFACE_ALT,fg=TEXT,insertbackground=CYAN,
                       selectbackground=CYAN_DIM,relief="flat",bd=0,
                       highlightthickness=1,highlightbackground=EDGE,
                       highlightcolor=CYAN,font=("Segoe UI",11))
    app.entry.grid(row=0,column=0,sticky="ew",ipady=9,padx=(0,7))
    _action(sendbar,"ОТПРАВИТЬ  ›",app.enter,primary=True).grid(
        row=0,column=1,sticky="ns")
    app.entry.bind("<Return>",app.enter)
    app.bind("<F9>",app.f9)
    app.bind("<Control-l>",lambda e:(app.entry.focus_set(),"break")[1])
    app.bind("<Control-Shift-M>",lambda e:(app.toggle_voice(),"break")[1])
    app.bind("<Control-Shift-R>",lambda e:(app.revoke(),"break")[1])

    # Left-side controls: no top or bottom shortcut bar.
    shortcuts=tk.Frame(rail,bg=SURFACE)
    shortcuts.pack(fill="x",padx=9,pady=(1,5))
    _label(shortcuts,"БЫСТРЫЕ ДЕЙСТВИЯ",fg=CYAN,size=8,bold=True).grid(
        row=0,column=0,columnspan=2,sticky="w",pady=(0,3))
    choices=(
        ("РОЛИКИ",lambda:app.open_viral_studio("audience")),
        ("ИГРЫ",lambda:app.activate_mode("gaming")),
        ("РАБОТА",lambda:app.activate_mode("work")),
        ("ОФИС",lambda:app.activate_mode("office")),
        ("УЧЁБА",lambda:app.activate_mode("study")),
        ("ЭКРАН",lambda:app.request_trimodal("screen")),
        ("ВОЗМОЖНОСТИ",app.show_capabilities),
    )
    app.hud_mode_buttons={}
    app.hud_shortcuts=shortcuts
    app.hud_shortcut_buttons=[]
    app.hud_shortcut_columns=2
    for index,(name,callback) in enumerate(choices):
        widget=_action(shortcuts,name,callback,compact=True)
        widget.grid(row=1+index//2,column=index%2,sticky="ew",padx=2,pady=2)
        app.hud_shortcut_buttons.append(widget)
        if name in {"ИГРЫ","РАБОТА","ОФИС","УЧЁБА"}:
            app.hud_mode_buttons[{"ИГРЫ":"gaming","РАБОТА":"work",
                                  "ОФИС":"office","УЧЁБА":"study"}[name]]=widget
    for column in range(2):
        shortcuts.grid_columnconfigure(column,weight=1)

    def resize_main(event):
        app.hud_status.configure(wraplength=max(140,event.width-35))
    app.hud_reflow=resize_main
    main.bind("<Configure>",resize_main,add="+")

    footer=tk.Frame(app,bg=BG)
    footer.pack(fill="x",padx=20,pady=(0,9))
    app.hud_footer=_label(footer,"●  ЗАЩИЩЁННЫЙ ЛОКАЛЬНЫЙ КОНТУР",
                           fg=GREEN,size=8,bold=True)
    app.hud_footer.pack(side="left")
    _label(footer,"NOVA HUD  /  F9 — СЛУШАТЬ  /  CTRL+L — ВВОД",
           fg=CYAN_DIM,size=8).pack(side="right")

    def tick():
        if getattr(app,"_closing",False):
            return
        try:
            speaking=bool(getattr(app.speaker,"busy",False) or
                          getattr(app.trimodal,"speaking",False))
            mode,name,color=visual_state(
                getattr(app,"voice_enabled",False),app.mic_state.get(),
                app.status.get(),getattr(app,"executing",False),speaking,
                listening=time.monotonic()<getattr(getattr(app,"voice",None),"until",0))
            app.hud_clock.configure(text=time.strftime("%H:%M:%S"))
            app.hud_mode.configure(text=name,fg=color)
            mode_key=getattr(app.modes,"mode","neutral") if hasattr(app,"modes") else "neutral"
            captions={"neutral":"ОБЫЧНЫЙ","gaming":"ИГРЫ","work":"РАБОТА",
                      "office":"ОФИС","study":"УЧЁБА","videos":"РОЛИКИ",
                      "video_shoot":"СЪЁМКА","video_edit":"МОНТАЖ",
                      "video_review":"ОЦЕНКА"}
            current=captions.get(mode_key,mode_key.upper()[:16])
            if getattr(app,"_hud_last_selected_mode",None)!=mode_key:
                app._hud_last_selected_mode=mode_key
                for selected,widget in app.hud_mode_buttons.items():
                    widget.configure(bg=CYAN_DIM if selected==mode_key else SURFACE_ALT,
                                     fg=TEXT)
            deadline=getattr(app,"_focus_deadline",None)
            if deadline is not None and deadline>time.monotonic():
                remain=math.ceil(deadline-time.monotonic())
                current+=f"  ·  ФОКУС {remain//60:02d}:{remain%60:02d}"
            if speaking:
                current+=("  ·  ТИХИЙ ОТВЕТ" if
                          getattr(app,"_current_playback_style","normal")=="whisper"
                          else "  ·  ОБЫЧНЫЙ ОТВЕТ")
            app.hud_footer.configure(text="●  "+name+"  /  "+current,fg=color)
            app.hud_access.configure(
                text=("УПРАВЛЕНИЕ: ДОСТУП" if getattr(app,"control_allowed",False)
                      else "УПРАВЛЕНИЕ: ЗАПРЕТ")+
                ("   /   ЗРЕНИЕ*: ДОСТУП" if getattr(app,"vision_allowed",False)
                      else "   /   ЗРЕНИЕ*: ЗАПРЕТ"),
                fg=AMBER if (getattr(app,"control_allowed",False) or
                             getattr(app,"vision_allowed",False)) else MUTED)
            level=None
            if (app.voice_enabled and app.hud_level_at
                    and time.monotonic()-app.hud_level_at<1.4):
                level=app.hud_level_value
            app.hud_meter.paint(level)
            _,readout=level_readout(level)
            app.hud_meter_label.configure(
                text="ВХОД: "+(readout if app.voice_enabled else "МИКРОФОН ВЫКЛ."),
                fg=GREEN if level is not None else MUTED)
            app.mic_toggle_button.configure(
                text="ОТКЛЮЧИТЬ МИКРОФОН" if app.voice_enabled
                     else "ВКЛЮЧИТЬ МИКРОФОН")
            engine={"bundled":"QWEN  /  ЛОКАЛЬНО",
                    "none":"ОФЛАЙН-КОМАНДЫ",
                    "ollama":"OLLAMA  /  ВНЕШНЯЯ",
                    "openai":"OPENAI API  /  СЕТЬ",
                    "anthropic":"CLAUDE API  /  СЕТЬ"}
            key=getattr(app,"engine","bundled")
            app.hud_engine.configure(text=engine.get(key,"AI  /  НЕИЗВЕСТНО"),
                                     fg=GREEN if key in ("bundled","none") else AMBER)
            if (app.hud_animate.get() or not app.hud_reactor._painted
                    or app.hud_reactor._mode != mode):
                app.hud_reactor.paint(mode,level)
            app._nova_after_id=app.after(130,tick)
        except tk.TclError:
            # Window is being destroyed; never keep a background animation alive.
            return
    def stop_animation(event):
        if event.widget is not app:
            return
        pending=getattr(app,"_nova_after_id",None)
        if pending is not None:
            try:
                app.after_cancel(pending)
            except tk.TclError:
                pass
            app._nova_after_id=None
    app.bind("<Destroy>",stop_animation,add="+")
    tick()
