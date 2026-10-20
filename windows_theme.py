# -*- coding: utf-8 -*-
"""Windows DWM dark title bar; preserve native minimize, resize and Alt+Tab.

Never use overrideredirect on the main window: removing Windows decorations
also removes keyboard, snap and taskbar affordances.
"""
from __future__ import annotations
import sys


def make_titlebar_dark(window) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        window.update_idletasks()
        native=ctypes.windll.user32
        hwnd=native.GetParent(window.winfo_id()) or window.winfo_id()
        dwm=ctypes.windll.dwmapi.DwmSetWindowAttribute

        def set_color(attribute,red,green,blue):
            # DWM COLORREF: 0x00BBGGRR
            value=ctypes.c_uint32(red | (green<<8) | (blue<<16))
            return dwm(hwnd,attribute,ctypes.byref(value),ctypes.sizeof(value))==0

        dark=ctypes.c_int(1)
        enabled=any(dwm(hwnd,attribute,ctypes.byref(dark),ctypes.sizeof(dark))==0
                    for attribute in (20,19))
        # Win11 caption, border and text colors (Win10 ignores unsupported ids).
        set_color(35,7,13,23)
        set_color(34,32,54,75)
        set_color(36,233,246,255)
        return enabled
    except (OSError,AttributeError,ValueError,TypeError):
        return False
