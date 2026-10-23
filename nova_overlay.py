# -*- coding: utf-8 -*-
"""Compact conversation-only NOVA bubble displayed when main window is minimized.

No second microphone and no permissions: buttons delegate to the existing Jarvis
controller. The preview contains the user's own recent chat, never raw audio.
"""
from __future__ import annotations
import time
import tkinter as tk

from nova_ui import BG, SURFACE, SURFACE_ALT, EDGE, CYAN, CYAN_DIM, GREEN, MUTED, TEXT, AMBER, level_readout, visual_state

MINI_WIDTH = 334
MINI_HEIGHT = 242
MINI_GAP = 20


def dock_geometry(screen_width, screen_height, width=MINI_WIDTH,
                  height=MINI_HEIGHT, gap=MINI_GAP):
    """Default: small bubble near the right edge, not over all the desktop."""
    sw, sh = max(1, int(screen_width)), max(1, int(screen_height))
    width, height = min(width, sw), min(height, sh)
    x = max(0, sw - width - gap)
    y = max(0, (sh - height) // 3)
    return f"{width}x{height}+{x}+{y}"


def clamp_drag_position(x, y, screen_width, screen_height,
                        width=MINI_WIDTH, height=MINI_HEIGHT):
    """Clamp to primary screen; supports low resolution/negative mouse coords."""
    sw, sh = max(1, int(screen_width)), max(1, int(screen_height))
    return max(0, min(int(x), max(0, sw-width))), max(0, min(int(y), max(0, sh-height)))


class NovaOverlay(tk.Toplevel):
    """A draggable always-on-top chat bubble, shown ONLY while main is hidden."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=CYAN_DIM)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self.geometry(dock_geometry(self.winfo_screenwidth(), self.winfo_screenheight()))
        self._manual_position = False
        self._drag = None
        self._timer_id = None
        self._closed = False

        shell = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=CYAN_DIM)
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        bar = tk.Frame(shell, bg=SURFACE)
        bar.pack(fill="x", padx=11, pady=(8, 1))
        self.brand = tk.Label(bar, text="◉  JARVIS NOVA", bg=SURFACE, fg=CYAN,
                              font=("Segoe UI", 11, "bold"), cursor="fleur")
        self.brand.pack(side="left")
        self.restore_btn = self.button(bar, "↗", self.restore_main)
        self.restore_btn.pack(side="right", padx=(4, 0))
        self.dock_btn = self.button(bar, "⌖", self.dock_right)
        self.dock_btn.pack(side="right")
        for widget in (bar, self.brand):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)
            widget.bind("<Double-Button-1>", self.dock_right)

        mode = tk.Frame(shell, bg=SURFACE)
        mode.pack(fill="x", padx=12, pady=(3, 2))
        self.status_label = tk.Label(mode, text="МИКРОФОН ВЫКЛ.", fg=MUTED, bg=SURFACE,
                                     font=("Segoe UI", 10, "bold"), anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.level = tk.Label(mode, text="НЕТ ДАННЫХ", bg=SURFACE, fg=MUTED,
                              font=("Segoe UI", 8))
        self.level.pack(side="right")

        # This miniature shows no modes, computer controls, app launchers or
        # permission toggles: it is strictly the conversation window.
        self.conversation = tk.Frame(shell, bg=SURFACE_ALT, highlightthickness=1,
                                      highlightbackground=EDGE)
        self.conversation.pack(fill="both", expand=True, padx=10, pady=(4, 5))
        self.last_user = tk.Label(self.conversation, text="ВЫ  ·  скажи «Джарвис»",
                                  bg=SURFACE_ALT, fg=TEXT, anchor="w",
                                  justify="left", wraplength=292, font=("Segoe UI", 9))
        self.last_user.pack(fill="x", padx=9, pady=(8, 2))
        self.last_answer = tk.Label(self.conversation, text="NOVA  ·  готов к разговору",
                                    bg=SURFACE_ALT, fg=CYAN, anchor="w",
                                    justify="left", wraplength=292, font=("Segoe UI", 9))
        self.last_answer.pack(fill="x", padx=9, pady=(1, 6))

        controls = tk.Frame(shell, bg=SURFACE)
        controls.pack(fill="x", padx=9, pady=(0, 7))
        self.mic_button = self.button(controls, "МИКРОФОН", app.toggle_voice)
        self.mic_button.pack(side="left", expand=True, fill="x", padx=2)
        self.listen_button = self.button(controls, "◉  F9", app.f9)
        self.listen_button.pack(side="left", expand=True, fill="x", padx=2)
        self.privacy_button = self.button(controls, "◌  ТЕКСТ", self.toggle_preview)
        self.privacy_button.pack(side="left", expand=True, fill="x", padx=2)
        self.restore_button = self.button(controls, "РАЗВЕРНУТЬ", self.restore_main)
        self.restore_button.pack(side="left", expand=True, fill="x", padx=2)

        self.protocol("WM_DELETE_WINDOW", self.restore_main)
        self.bind("<F9>", lambda e: (self.app.f9(), "break")[1])
        self.bind("<Control-Shift-O>", lambda e: (self.restore_main(), "break")[1])
        self.bind("<Control-Shift-M>", lambda e: (self.app.toggle_voice(), "break")[1])
        self.bind("<Control-Shift-R>", lambda e: (self.app.revoke(), "break")[1])

    @staticmethod
    def button(parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=EDGE, fg=TEXT,
                         activebackground=CYAN_DIM, activeforeground=TEXT,
                         relief="flat", bd=0, padx=3, pady=6,
                         cursor="hand2", font=("Segoe UI", 8, "bold"))

    def start_drag(self, event):
        self._drag = (event.x_root-self.winfo_x(), event.y_root-self.winfo_y())

    def drag(self, event):
        if self._drag is None:
            return
        x, y = clamp_drag_position(event.x_root-self._drag[0],
                                   event.y_root-self._drag[1],
                                   self.winfo_screenwidth(), self.winfo_screenheight(),
                                   self.winfo_width(), self.winfo_height())
        self.geometry(f"+{x}+{y}")
        self._manual_position = True

    def end_drag(self, event=None):
        self._drag = None
        if self._manual_position and hasattr(self.app, "save_window_layout"):
            self.app.save_window_layout()

    def dock_right(self, event=None):
        if self._closed:
            return
        self._manual_position = False
        self._drag = None
        self.geometry(dock_geometry(self.winfo_screenwidth(), self.winfo_screenheight()))
        if hasattr(self.app, "save_window_layout"):
            self.app.save_window_layout()

    def show(self):
        if self._closed or getattr(self.app, "_closing", False):
            return
        if not self._manual_position:
            self.geometry(dock_geometry(self.winfo_screenwidth(), self.winfo_screenheight()))
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        if self._timer_id is None:
            self.refresh()

    def hide(self):
        if self._timer_id is not None:
            try:
                self.after_cancel(self._timer_id)
            except tk.TclError:
                pass
            self._timer_id = None
        if not self._closed:
            self.withdraw()

    def toggle_preview(self):
        if self._closed:
            return
        self.app.set_overlay_preview(
            not bool(getattr(self.app, "overlay_show_text", True)))
        self.refresh_preview()

    def refresh_preview(self):
        visible = bool(getattr(self.app, "overlay_show_text", True))
        if visible:
            user = getattr(self.app, "overlay_last_user", "") or "ВЫ  ·  скажи «Джарвис»"
            reply = getattr(self.app, "overlay_last_answer", "") or "NOVA  ·  готов к разговору"
        else:
            user = "ВЫ  ·  реплика скрыта"
            reply = "NOVA  ·  текст скрыт"
        self.last_user.configure(text=user)
        self.last_answer.configure(text=reply)
        self.privacy_button.configure(text="◉  СКРЫТЬ" if visible else "◌  ПОКАЗАТЬ")

    def restore_main(self):
        if not self._closed and not getattr(self.app, "_closing", False):
            self.app.show_main()

    def refresh(self):
        if self._closed or not self.winfo_exists() or self.state() != "normal":
            return
        self._timer_id = None
        app = self.app
        speaking = bool(getattr(app.speaker, "busy", False) or
                        getattr(app.trimodal, "speaking", False))
        mode, label, color = visual_state(
            bool(app.voice_enabled), app.mic_state.get(), app.status.get(),
            bool(app.executing), speaking,
            listening=time.monotonic() < getattr(app.voice, "until", 0))
        self.status_label.configure(text=label, fg=color)
        self.mic_button.configure(text="ВЫКЛ. МИК." if app.voice_enabled else "ВКЛ. МИК.")
        current = None
        if (app.voice_enabled and app.hud_level_at and
                time.monotonic()-app.hud_level_at < 1.4):
            current = app.hud_level_value
        _, reading = level_readout(current)
        self.level.configure(text=reading if app.voice_enabled else "МИК. ВЫКЛ.")
        self.refresh_preview()
        self._timer_id = self.after(170, self.refresh)

    def shutdown(self):
        if self._closed:
            return
        self.hide()
        self._closed = True
        self.destroy()
