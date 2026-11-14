# -*- coding: utf-8 -*-
"""Visible, read-only capability diagnostics; Tk is owned by main thread."""
from __future__ import annotations

from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import ttk

from module_health import collect_health


class ModuleHealthWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("JARVIS NOVA — состояние модулей")
        self.geometry("715x575")
        self.minsize(480,380)
        self._events=Queue()
        self._busy=False
        self._closed=False
        self._assets=getattr(parent,"_asset_root",None)
        self.protocol("WM_DELETE_WINDOW",self.close)
        body=ttk.Frame(self,padding=12)
        body.pack(fill="both",expand=True)
        ttk.Label(body,text="ДИАГНОСТИКА МОДУЛЕЙ",
                  font=("Segoe UI",15,"bold")).pack(anchor="w")
        ttk.Label(body,text=(
            "Только чтение: без скачивания, включения экрана, изменения файлов "
            "или запуска моделей. Статус «не проверено» — не ошибка."),
            wraplength=650).pack(anchor="w",pady=(5,8))
        self.report=tk.Text(body,wrap="word",state="disabled")
        self.report.pack(fill="both",expand=True)
        bottom=ttk.Frame(body)
        bottom.pack(fill="x",pady=7)
        ttk.Button(bottom,text="Проверить снова",command=self.refresh).pack(side="left")
        self.state=tk.StringVar(value="Проверяю…")
        ttk.Label(bottom,textvariable=self.state,wraplength=480).pack(
            side="left",padx=8)
        self.after(100,self._pump)
        self.refresh()

    def refresh(self):
        if self._busy or self._closed:
            return
        self._busy=True
        self.state.set("Читаю локальные сведения о модулях…")
        def check():
            try:
                result=collect_health(assets=self._assets)
                self._events.put(("result",result))
            except Exception:
                # The window must not expose paths/tokens in raw exceptions.
                self._events.put(("error","Не удалось выполнить проверку."))
        threading.Thread(target=check,daemon=True,
                         name="jarvis-module-health").start()

    def _pump(self):
        """Drain background diagnostics only inside the owning Tk thread."""
        if self._closed:
            return
        try:
            for _ in range(8):
                try:
                    kind,payload=self._events.get_nowait()
                except Empty:
                    break
                self._busy=False
                if kind=="error":
                    self.state.set(payload)
                    continue
                self.report.configure(state="normal")
                self.report.delete("1.0","end")
                names={"ready":"[ГОТОВО]", "missing":"[НЕ НАЙДЕНО]",
                       "warning":"[ВНИМАНИЕ]", "unknown":"[НЕ ПРОВЕРЕНО]"}
                for item in payload.items:
                    self.report.insert("end",(
                        f"{names.get(item.status,'[?]')} {item.name}\n"
                        f"  {item.detail}\n\n"))
                self.report.configure(state="disabled")
                self.state.set(payload.summary())
            if self.winfo_exists():
                self.after(100,self._pump)
        except tk.TclError:
            pass

    def close(self):
        self._closed=True
        self.destroy()
