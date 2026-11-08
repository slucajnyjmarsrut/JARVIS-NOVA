# -*- coding: utf-8 -*-
"""Prevent automatic JARVIS restarts while editors are open.

The mini-chat, command palette and Update Center itself are shell chrome,
not documents. Any other visible Tk top-level may contain unsaved work,
especially the code assistant, viral studio, game and configuration dialogs.
"""
from __future__ import annotations

import tkinter as tk


def editing_window_open(app) -> bool:
    # A Qwen model pull can last much longer than ten minutes. Restarting
    # JARVIS in the middle can interrupt a multi-gigabyte opt-in download.
    if getattr(app,"_model_download_busy",False):
        return True
    children=getattr(app,"winfo_children",None)
    if not callable(children):
        return False
    palette=getattr(app,"_command_palette",None)
    ignored=(
        getattr(app,"overlay",None),
        getattr(app,"_update_center",None),
        getattr(palette,"popup",None),
    )
    try:
        for child in children():
            if (isinstance(child,tk.Toplevel) and
                    child not in ignored and
                    child.winfo_exists() and child.winfo_viewable()):
                return True
    except tk.TclError:
        # Tk destroyed while checking: defer an update rather than risking
        # a destructive restart.
        return True
    return False
