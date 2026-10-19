# -*- coding: utf-8 -*-
"""Non-intrusive Windows NOVA overlay shown when the main Tk window is hidden.

No global keyboard hook, screen capture, network call or extra microphone stream.
All actions delegate to the main Jarvis instance and keep its permission checks.
"""
import time
import math
import tkinter as tk
from nova_ui import (BG, SURFACE, EDGE, CYAN, GREEN, MUTED, TEXT, RED, AMBER,
                     level_readout, visual_state)


def dock_geometry(screen_width, screen_height, width=344, height=328, gap=20):
    """Right-hand edge of the desktop, clamped for small screens."""
    sw=max(1,int(screen_width))
    sh=max(1,int(screen_height))
    w=min(width,sw)
    h=min(height,sh)
    x=max(0,sw-w-max(0,gap))
    y=max(0,(sh-h)//3)
    return f"{w}x{h}+{x}+{y}"


def clamp_drag_position(x,y,screen_width,screen_height,width=344,height=328):
    """Keep the overlay entirely inside the primary desktop area."""
    sw=max(1,int(screen_width))
    sh=max(1,int(screen_height))
    return (max(0,min(int(x),max(0,sw-width))),
            max(0,min(int(y),max(0,sh-height))))


class NovaOverlay(tk.Toplevel):
    """Draggable always-on-top HUD; only visible while the main window is hidden."""

    def __init__(self,app):
        super().__init__(app)
        self.app=app
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=CYAN)
        self.attributes("-topmost",True)
        try:
            self.attributes("-alpha",.96)
        except tk.TclError:
            pass
        self.resizable(False,False)
        self.geometry(dock_geometry(self.winfo_screenwidth(),self.winfo_screenheight()))
        self._manual_position=False
        self._drag=None
        self._timer_id=None
        self._closed=False

        shell=tk.Frame(self,bg=SURFACE,highlightthickness=1,
                       highlightbackground=CYAN)
        shell.pack(fill="both",expand=True,padx=1,pady=1)

        dragbar=tk.Frame(shell,bg=SURFACE)
        dragbar.pack(fill="x",padx=13,pady=(10,2))
        title=tk.Label(dragbar,text="◉  NOVA  /  OVERLAY",bg=SURFACE,
                       fg=CYAN,font=("Segoe UI",11,"bold"),cursor="fleur")
        title.pack(side="left")
        self.restore_btn=tk.Button(
            dragbar,text="↗  ОТКРЫТЬ",command=self.restore_main,bg=SURFACE,
            fg=TEXT,activebackground=EDGE,activeforeground=CYAN,
            bd=0,relief="flat",cursor="hand2",font=("Segoe UI",9,"bold"))
        self.restore_btn.pack(side="right")
        self.dock_btn=tk.Button(
            dragbar,text="⇥",command=self.dock_right,bg=SURFACE,
            fg=CYAN,activebackground=EDGE,activeforeground=TEXT,
            bd=0,relief="flat",cursor="hand2",font=("Segoe UI",12,"bold"))
        self.dock_btn.pack(side="right",padx=(2,7))

        for widget in (dragbar,title):
            widget.bind("<ButtonPress-1>",self.start_drag)
            widget.bind("<B1-Motion>",self.drag)
            widget.bind("<ButtonRelease-1>",self.end_drag)
            widget.bind("<Double-Button-1>",self.dock_right)

        bar=tk.Frame(shell,bg=SURFACE)
        bar.pack(fill="x",padx=13,pady=(4,4))
        self.dot=tk.Canvas(bar,width=12,height=12,highlightthickness=0,bg=SURFACE)
        self.dot.pack(side="left",padx=(0,7))
        self.status_label=tk.Label(bar,text="МИКРОФОН ВЫКЛ.",bg=SURFACE,fg=MUTED,
                            font=("Segoe UI",11,"bold"))
        self.status_label.pack(side="left")

        self.context=tk.Label(shell,text="РЕЖИМ: ОБЫЧНЫЙ",bg=SURFACE,
                              fg=MUTED,font=("Segoe UI",9),anchor="w")
        self.context.pack(fill="x",padx=14,pady=(2,4))
        self.listen_detail=tk.Label(shell,text="ГОТОВ К КОМАНДАМ",bg=SURFACE,
                                    fg=CYAN,font=("Segoe UI",9,"bold"),anchor="w")
        self.listen_detail.pack(fill="x",padx=14,pady=(0,4))
        self.privacy=tk.Label(shell,text="УПРАВЛЕНИЕ: ЗАПРЕТ · ЗРЕНИЕ*: ЗАПРЕТ",
                              bg=SURFACE,fg=MUTED,font=("Segoe UI",8),anchor="w")
        self.privacy.pack(fill="x",padx=14,pady=(0,4))
        self.meter=tk.Canvas(shell,height=23,highlightthickness=0,bg=SURFACE)
        self.meter.pack(fill="x",padx=14,pady=(1,2))
        self.level=tk.Label(shell,text="ВХОД: НЕТ ДАННЫХ",bg=SURFACE,
                            fg=MUTED,font=("Segoe UI",8))
        self.level.pack(anchor="w",padx=14)
        self.last_turn=tk.Label(shell,text="ПОСЛЕДНИЕ РЕПЛИКИ СКРЫТЫ",
                                bg=SURFACE,fg=MUTED,wraplength=306,
                                justify="left",anchor="w",height=2,
                                font=("Segoe UI",8))
        self.last_turn.pack(fill="x",padx=14,pady=(4,2))

        actions=tk.Frame(shell,bg=SURFACE)
        actions.pack(fill="x",padx=11,pady=(8,8))
        self.mic_button=self.button(actions,"ВКЛ. МИКРОФОН",app.toggle_voice)
        self.mic_button.pack(side="left",expand=True,fill="x",padx=2)
        self.listen_button=self.button(actions,"СЛУШАЙ",app.f9)
        self.listen_button.pack(side="left",expand=True,fill="x",padx=2)
        self.restore_button=self.button(actions,"ОКНО",self.restore_main)
        self.restore_button.pack(side="left",expand=True,fill="x",padx=2)
        self.preview_button=self.button(shell,"ПОКАЗАТЬ НОВЫЕ РЕПЛИКИ",
                                        self.toggle_preview)
        self.preview_button.pack(fill="x",padx=14,pady=(0,8))
        self.protocol("WM_DELETE_WINDOW",self.restore_main)
        self.bind("<F9>",lambda e:(self.app.f9(),"break")[1])
        self.bind("<Control-Shift-O>",lambda e:(self.restore_main(),"break")[1])
        self.bind("<Control-Shift-M>",lambda e:(self.app.toggle_voice(),"break")[1])
        self.bind("<Control-Shift-R>",lambda e:(self.app.revoke(),"break")[1])

    @staticmethod
    def button(parent,text,command):
        return tk.Button(parent,text=text,command=command,bg=EDGE,fg=TEXT,
                         activebackground="#236C80",activeforeground=TEXT,
                         relief="flat",bd=0,padx=5,pady=5,cursor="hand2",
                         font=("Segoe UI",8,"bold"))

    def start_drag(self,event):
        self._drag=(event.x_root-self.winfo_x(),event.y_root-self.winfo_y())

    def drag(self,event):
        if self._drag is None:return
        x,y=clamp_drag_position(
            event.x_root-self._drag[0],event.y_root-self._drag[1],
            self.winfo_screenwidth(),self.winfo_screenheight(),
            self.winfo_width(),self.winfo_height())
        self.geometry(f"+{x}+{y}")
        self._manual_position=True

    def end_drag(self,event=None):
        self._drag=None

    def dock_right(self,event=None):
        if self._closed:return
        self._manual_position=False
        self._drag=None
        self.geometry(dock_geometry(self.winfo_screenwidth(),
                                    self.winfo_screenheight()))

    def show(self):
        if self._closed or getattr(self.app,"_closing",False):return
        if not self._manual_position:
            self.geometry(dock_geometry(self.winfo_screenwidth(),
                                        self.winfo_screenheight()))
        self.deiconify()
        self.lift()
        self.attributes("-topmost",True)
        if self._timer_id is None:
            self.refresh()

    def hide(self):
        if self._timer_id is not None:
            try:self.after_cancel(self._timer_id)
            except tk.TclError:pass
            self._timer_id=None
        if not self._closed:
            self.withdraw()

    def toggle_preview(self):
        if self._closed:return
        self.app.set_overlay_preview(
            not bool(getattr(self.app,"overlay_show_text",False)))
        self.refresh_preview()

    def refresh_preview(self):
        enabled=bool(getattr(self.app,"overlay_show_text",False))
        self.preview_button.configure(
            text="СКРЫТЬ РЕПЛИКИ" if enabled else "ПОКАЗАТЬ НОВЫЕ РЕПЛИКИ")
        if not enabled:
            text="ПОСЛЕДНИЕ РЕПЛИКИ СКРЫТЫ"
        else:
            text="\n".join(filter(None,(
                getattr(self.app,"overlay_last_user",""),
                getattr(self.app,"overlay_last_answer","")))) or "ОЖИДАЮ НОВУЮ РЕПЛИКУ…"
        self.last_turn.configure(text=text,
                                 fg=TEXT if enabled else MUTED)

    def restore_main(self):
        if self._closed or getattr(self.app,"_closing",False):return
        self.app.show_main()

    def refresh(self):
        if self._closed or not self.winfo_exists():return
        if self.state() != "normal":return
        self._timer_id=None  # the previous scheduled callback has fired
        app=self.app
        state,label,color=visual_state(
            bool(app.voice_enabled),app.mic_state.get(),app.status.get(),
            bool(app.executing),
            bool(getattr(app.speaker,"busy",False) or
                 getattr(app.trimodal,"speaking",False)),
            listening=time.monotonic()<getattr(app.voice,"until",0))
        self.status_label.configure(text=label,fg=color)
        self.dot.delete("all")
        self.dot.create_oval(1,1,11,11,fill=color,outline="")
        self.mic_button.configure(
            text="ВЫКЛ. МИКРОФОН" if app.voice_enabled else "ВКЛ. МИКРОФОН")
        label=getattr(app.modes,"mode","neutral")
        modes={"neutral":"ОБЫЧНЫЙ","gaming":"ИГРЫ","work":"РАБОТА",
               "office":"ОФИС","study":"УЧЁБА","videos":"РОЛИКИ",
               "video_shoot":"СЪЁМКА","video_edit":"МОНТАЖ",
               "video_review":"ОЦЕНКА"}
        deadline=getattr(app,"_focus_deadline",None)
        focus=""
        if deadline is not None and deadline>time.monotonic():
            left=math.ceil(deadline-time.monotonic())
            focus=f"  ·  ФОКУС {left//60:02d}:{left%60:02d}"
        self.context.configure(text=("РЕЖИМ: "+modes.get(label,label.upper()[:18])
                             +focus+("  •  ДЕЙСТВИЕ…" if app.executing else "")))
        self.refresh_preview()
        voice=getattr(app,"voice",None)
        until=float(getattr(voice,"until",0))
        queued=len(getattr(voice,"whisper_queue",()))
        busy=bool(getattr(voice,"whisper_busy",False))
        if not app.voice_enabled:
            detail="ГОЛОСОВОЙ ВВОД ОТКЛЮЧЁН"
        elif busy:
            detail="WHISPER РАСПОЗНАЁТ"+(f"  ·  ОЧЕРЕДЬ {queued}/2" if queued else "")
        elif until>time.monotonic():
            detail=f"СЛУШАЮ  ·  {max(1,int(until-time.monotonic()+.99))} СЕК."
        else:
            detail="ЖДУ КОМАНДУ «ДЖАРВИС»"
        self.listen_detail.configure(text=detail)
        has_control=bool(getattr(app,"control_allowed",False))
        has_vision=bool(getattr(app,"vision_allowed",False))
        self.privacy.configure(
            text=("УПРАВЛЕНИЕ: ДОСТУП" if has_control else "УПРАВЛЕНИЕ: ЗАПРЕТ")+
                 ("  ·  ЗРЕНИЕ*: ДОСТУП" if has_vision else "  ·  ЗРЕНИЕ*: ЗАПРЕТ"),
            fg=AMBER if (has_control or has_vision) else MUTED)
        current=None
        if app.voice_enabled and app.hud_level_at and time.monotonic()-app.hud_level_at<1.4:
            current=app.hud_level_value
        fraction,reading=level_readout(current)
        if not app.voice_enabled:reading="МИКРОФОН ВЫКЛ."
        self.level.configure(text="ВХОД: "+reading)
        self.meter.delete("all")
        total=20
        width=max(1,self.meter.winfo_width())
        for index in range(total):
            x1=index*width/total+1
            x2=(index+1)*width/total-2
            fill=(GREEN if index<14 else AMBER if index<17 else RED)
            if (index+.5)/total>fraction:fill=EDGE
            self.meter.create_rectangle(x1,4,x2,20,fill=fill,outline="")
        self._timer_id=self.after(180,self.refresh)

    def shutdown(self):
        if self._closed:return
        self.hide()
        self._closed=True
        self.destroy()
