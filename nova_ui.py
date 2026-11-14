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
        self.last_energy = 0.0
        self.phase = (self.phase + (3 if mode == "processing" else 1) +
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


