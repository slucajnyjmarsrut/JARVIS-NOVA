# -*- coding: utf-8 -*-
"""Typing panel when the main JARVIS window is minimized."""
import tkinter as tk
from nova_overlay import NovaOverlay
from nova_ui import GREEN, MUTED


class TextOverlay(NovaOverlay):
    def __init__(self, app):
        super().__init__(app)
        self.status_label.configure(text="ГОТОВ К ПЕРЕПИСКЕ", fg=GREEN)
        self.last_user.configure(text="ВЫ  ·  напишите сообщение")
        controls = self.restore_button.master
        entry_row = tk.Frame(controls.master,bg=controls.master.cget("bg"))
        entry_row.pack(fill="x",padx=10,pady=(0,4),before=controls)
        self.quick_entry = tk.Entry(entry_row,font=("Segoe UI",9))
        self.quick_entry.pack(side="left",fill="x",expand=True,padx=(0,4))
        self.quick_entry.bind("<Return>",self.send_text)
        # Enter submits from the mini-chat; no separate Send button.

    def send_text(self,event=None):
        if self._closed or getattr(self.app,"_closing",False):
            return "break"
        text=self.quick_entry.get().strip()
        if text:
            self.quick_entry.delete(0,"end")
            self.app.handle_text(text)
        return "break"

    def refresh_preview(self):
        visible=bool(getattr(self.app,"overlay_show_text",True))
        if visible:
            user=getattr(self.app,"overlay_last_user","") or "ВЫ  ·  напишите сообщение"
            reply=getattr(self.app,"overlay_last_answer","") or "NOVA  ·  готов к переписке"
        else:
            user="ВЫ  ·  сообщение скрыто"
            reply="NOVA  ·  текст скрыт"
        self.last_user.configure(text=user)
        self.last_answer.configure(text=reply)
        self.privacy_button.configure(text="◉  СКРЫТЬ" if visible else "◌  ПОКАЗАТЬ")

    def refresh(self):
        if self._closed or not self.winfo_exists() or self.state()!="normal":
            return
        self._timer_id=None
        busy=bool(getattr(self.app,"executing",False))
        self.status_label.configure(text="ПИШУ ОТВЕТ…" if busy else "ГОТОВ К ПЕРЕПИСКЕ",
                                    fg=MUTED if busy else GREEN)
        self.refresh_preview()
        self._timer_id=self.after(190,self.refresh)
