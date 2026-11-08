# -*- coding: utf-8 -*-
"""A real, accessible dark ttk theme for the JARVIS NOVA video studio."""
import tkinter as tk
from tkinter import ttk

BG="#081421"
CARD="#10253A"
ALT="#0B1D30"
EDGE="#2D5269"
TEXT="#EAF5FC"
MUTED="#A9BFCE"
CYAN="#43DFE5"
HOVER="#1D4761"
GREEN="#6CDEAF"

def apply_video_theme(window):
    style=ttk.Style(window)
    if style.theme_use()!="clam":
        style.theme_use("clam")
    style.configure("Studio.TFrame",background=BG)
    style.configure("Studio.Card.TFrame",background=CARD)
    style.configure("Studio.TLabel",background=BG,foreground=TEXT,
                    font=("Segoe UI",10))
    style.configure("Studio.Small.TLabel",background=BG,foreground=MUTED,
                    font=("Segoe UI",9))
    style.configure("Studio.Heading.TLabel",background=BG,foreground=TEXT,
                    font=("Segoe UI Semibold",15))
    style.configure("Studio.Card.TLabel",background=CARD,foreground=TEXT,
                    font=("Segoe UI",10))
    style.configure("Studio.TLabelframe",background=CARD,relief="solid",
                    bordercolor=EDGE,borderwidth=1)
    style.configure("Studio.TLabelframe.Label",background=CARD,foreground=CYAN,
                    font=("Segoe UI Semibold",10))
    style.configure("Studio.TCheckbutton",background=CARD,foreground=TEXT,
                    font=("Segoe UI",9),padding=4)
    style.map("Studio.TCheckbutton",
              background=[("active",CARD),("disabled",CARD)],
              foreground=[("disabled",MUTED)])
    style.configure("Studio.TRadiobutton",background=CARD,foreground=TEXT,
                    font=("Segoe UI",9),padding=(6,5))
    style.map("Studio.TRadiobutton",background=[("active",CARD)],
              foreground=[("active",CYAN)])
    style.configure("Studio.TEntry",fieldbackground=ALT,foreground=TEXT,
                    bordercolor=EDGE,lightcolor=CYAN,darkcolor=EDGE,padding=7)
    style.map("Studio.TEntry",fieldbackground=[("disabled",CARD)])
    style.configure("Studio.TCombobox",fieldbackground=ALT,background=ALT,
                    foreground=TEXT,arrowcolor=CYAN,bordercolor=EDGE,
                    lightcolor=CYAN,darkcolor=EDGE,padding=4)
    style.map("Studio.TCombobox",
        fieldbackground=[("readonly",ALT)],
        background=[("readonly",ALT),("active",HOVER)],
        foreground=[("readonly",TEXT)],
        arrowcolor=[("readonly",CYAN)])
    style.configure("Studio.TButton",background=CARD,foreground=TEXT,
                    borderwidth=1,relief="flat",bordercolor=EDGE,
                    font=("Segoe UI",9),padding=(12,9))
    style.map("Studio.TButton",background=[("active",HOVER),
                                           ("pressed",EDGE)],
              foreground=[("disabled",MUTED),("active",CYAN)])
    style.configure("Studio.Primary.TButton",background="#147A85",
                    foreground="#FFFFFF",font=("Segoe UI Semibold",10),
                    padding=(14,10),borderwidth=1,bordercolor=CYAN)
    style.map("Studio.Primary.TButton",
              background=[("active","#1D96A2"),("pressed","#11636A"),
                          ("disabled",EDGE)])
    style.configure("Studio.Vertical.TScrollbar",background=EDGE,
                    troughcolor=ALT,arrowcolor=CYAN,bordercolor=BG)
    return style
