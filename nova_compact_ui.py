# -*- coding: utf-8 -*-
"""The compact NOVA desktop panel; the classic Tk HUD widgets remain reusable.

The text-only window uses this bounded geometry helper.
"""
from __future__ import annotations
import math
import time
import tkinter as tk
from tkinter import ttk


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


