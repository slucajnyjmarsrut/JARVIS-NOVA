# -*- coding: utf-8 -*-
"""Best-effort dark Windows titlebars without replacing native window controls.

Windows 10 uses DWMWA_USE_IMMERSIVE_DARK_MODE (20 or legacy 19);
Windows 11 also supports explicit caption/text colours (35/36).
Use pointer-sized HWND values: Tk's winfo_id() is often a child of the
native wrapper and untyped ctypes calls truncate HWND on 64-bit Windows.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


def _colorref(rgb: str) -> int:
    """Convert '#RRGGBB' to the Win32 COLORREF (0x00BBGGRR)."""
    rgb = rgb.removeprefix("#")
    if len(rgb) != 6:
        raise ValueError("Expected a six-digit RGB colour")
    value = int(rgb, 16)
    return ((value & 0xFF) << 16) | (value & 0xFF00) | (value >> 16)


def apply_dark_titlebar(window, *, background="#070D17", foreground="#EAF5FC") -> bool:
    """Apply Windows DWM colours to the actual native top-level HWND.

    Never strips the native caption, resize border or minimize/maximize buttons.
    Older Windows versions safely retain their system titlebar.
    """
    if sys.platform != "win32":
        return False
    try:
        if not window.winfo_exists():
            return False
        user32 = ctypes.windll.user32
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
        get_ancestor.restype = wintypes.HWND
        raw_hwnd = int(window.winfo_id())
        hwnd = get_ancestor(raw_hwnd, 2) or raw_hwnd  # GA_ROOT
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        dwm.restype = ctypes.c_long

        dark = ctypes.c_int(1)
        succeeded = (dwm(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)) == 0)
        if not succeeded:  # Windows 10 1809 used attribute 19
            succeeded = (dwm(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark)) == 0)

        for attribute, rgb in ((35, background), (36, foreground)):
            colour = ctypes.c_uint(_colorref(rgb))
            if dwm(hwnd, attribute, ctypes.byref(colour), ctypes.sizeof(colour)) == 0:
                succeeded = True

        if succeeded:
            set_window_pos = user32.SetWindowPos
            set_window_pos.argtypes = (
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            )
            set_window_pos.restype = wintypes.BOOL
            # SWP_FRAMECHANGED | SWP_NOSIZE | SWP_NOMOVE |
            # SWP_NOZORDER | SWP_NOACTIVATE. Keep position and window state.
            set_window_pos(hwnd, None, 0, 0, 0, 0, 0x0037)
        return succeeded
    except Exception:
        # Cosmetic Windows integration must never prevent the GUI from opening.
        return False


def install_dark_titlebar(window, *, background="#070D17", foreground="#EAF5FC"):
    """Retry after Tk creates/maps its native wrapper, and on later remaps."""
    if sys.platform != "win32":
        return
    if getattr(window, "_nova_dark_titlebar_installed", False):
        return
    window._nova_dark_titlebar_installed = True

    def paint():
        apply_dark_titlebar(window, background=background, foreground=foreground)

    def when_mapped(event):
        if event.widget is window:
            try:
                window.after_idle(paint)
            except Exception:
                pass

    window.bind("<Map>", when_mapped, add="+")
    window.after(100, paint)
    window.after(700, paint)
