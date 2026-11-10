# -*- coding: utf-8 -*-
"""Dark, keyboard-accessible command palette for text-only JARVIS NOVA.

Replaces Windows' bright native Tk popup. Every command forwards to an
existing controller method; never creates additional privileges or executes
commands from a model.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#081421"
CARD = "#10253A"
HOVER = "#1B4055"
EDGE = "#2B576C"
CYAN = "#43DFE5"
TEXT = "#ECF5FA"
MUTED = "#9BAFBE"

def clamp_popup(x, y, width, height, screen_width, screen_height):
    """Always keep popover within visible desktop bounds."""
    sw = max(240, int(screen_width))
    sh = max(240, int(screen_height))
    w = min(int(width), sw-16)
    h = min(int(height), sh-32)
    return max(8, min(int(x), sw-w-8)), max(8, min(int(y), sh-h-24)), w, h


def entries(app, section="main"):
    """(icon, caption, callback, subgroup), with None for divider."""
    if section == "permissions":
        return [
            ("✓", "Разрешить управление ПК", app.grant_control, None),
            ("◉", "Разрешить чтение экрана", app.grant_vision, None),
            ("×", "Отозвать разрешения", app.revoke, None),
        ]
    if section == "ai":
        return [("◆", label, lambda v=value: app.set_engine(v), None)
                for label,value in (
                    ("Qwen · локально","bundled"),("Только команды","none"),
                    ("Ollama · локально","ollama"),
                    ("FreeLLM · несколько моделей","freellm"),
                    ("OpenAI API","openai"),("Claude API","anthropic"))]
    if section == "modes":
        items=[("◈", label, lambda v=key: app.activate_mode(v), None)
               for key,label in (
                 ("neutral","Обычный"),("gaming","Игры"),("work","Работа"),
                 ("office","Офис"),("study","Учёба"),("videos","Ролики"),
                 ("video_shoot","Съёмка"),("video_edit","Монтаж"),
                 ("video_review","Оценка ролика"))]
        items += [
          None,("▶","Запустить режим",app.start_mode_apps,None),
          ("▣","Выбрать игру…",app.ask_game,None),
          ("⚙","Настроить приложения…",app.configure_mode_apps,None),
          ("◷","Таймер 25 минут",lambda:app._palette_start_focus_timer(),None),
          ("×","Остановить таймер",app.stop_focus_timer,None)]
        return items
    items=[
        ("⟳", "Автообновления · проверить версию", app.show_update_center, None),
        ("▣", "Разрешения", None, "permissions"),
        ("◎", "Описать экран текстом", lambda: app.request_trimodal("screen"), None),
        None,
        ("◈", "Режимы работы", None, "modes"),
        ("◆", "Выбрать AI", None, "ai"),
        ("⌘", "Программирование · 20 языков", app.open_code_assistant, None),
        ("🛠", "Самоисправление · только jarvis", app.open_self_development, None),
        ("▤", "Видео-студия", app.open_viral_studio, None),
        ("▶", "FilmCraft · открыть редактор", app.open_filmcraft, None),
        None,
        ("✦", "Проверить локальную модель", app.check_models, None),
        ("♢", "Возможности", app.show_capabilities, None),
        ("↺", "Восстановить настройки", app.self_repair_now, None),
        None,
        ("▣", "Свернуть в мини-чат", app.hide_main, None),
        ("⏻", "Выход", app.close, None),
    ]
    if getattr(app, "_model_download_busy", False):
        row=("×", "Отменить загрузку Qwen", app.cancel_local_model_download, None)
        anchor=next(i for i,item in enumerate(items)
                    if item is not None and item[1]=="Проверить локальную модель")
        items.insert(anchor+1,row)
    return items


class CommandPalette:
    def __init__(self, app):
        self.app = app
        self.section = "main"
        self.popup = tk.Toplevel(app)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.configure(bg=EDGE)
        self.popup.transient(app)
        self.popup._nova_palette = self
        self.popup.bind("<Escape>", lambda event: self.close())
        self.popup.bind("<FocusOut>", self._on_blur, add="+")
        self.search = tk.StringVar(master=app)
        outer = tk.Frame(self.popup,bg=BG,highlightbackground=CYAN,
                         highlightthickness=1)
        outer.pack(fill="both",expand=True,padx=1,pady=1)
        titlebar=tk.Frame(outer,bg=BG)
        titlebar.pack(fill="x",padx=14,pady=(12,7))
        self.heading=tk.Label(titlebar,text="КОМАНДЫ NOVA",fg=CYAN,bg=BG,
                              font=("Segoe UI",11,"bold"))
        self.heading.pack(side="left")
        close=tk.Button(titlebar,text="✕",bg=BG,fg=MUTED,relief="flat",
                        bd=0,activebackground=HOVER,activeforeground=TEXT,
                        command=self.close)
        close.pack(side="right")
        self.search_box=tk.Entry(outer,textvariable=self.search,
            bg=CARD,fg=TEXT,insertbackground=CYAN,relief="flat",
            highlightthickness=1,highlightbackground=EDGE,
            highlightcolor=CYAN,font=("Segoe UI",10))
        self.search_box.pack(fill="x",padx=14,ipady=7,pady=(0,8))
        self.search_box.bind("<Return>",self._activate_first)
        self.search.trace_add("write",lambda *_:self.render())
        container=tk.Frame(outer,bg=BG)
        container.pack(fill="both",expand=True,padx=(12,6),pady=(0,10))
        self.canvas=tk.Canvas(container,bg=BG,highlightthickness=0,
                              bd=0,relief="flat")
        self.scroll=ttk.Scrollbar(container,orient="vertical",
                                  command=self.canvas.yview)
        self.canvas.pack(side="left",fill="both",expand=True)
        self.scroll.pack(side="right",fill="y")
        self.rows=tk.Frame(self.canvas,bg=BG)
        self.canvas_item=self.canvas.create_window((0,0),window=self.rows,
                                                    anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.rows.bind("<Configure>",lambda e:self.canvas.configure(
            scrollregion=self.canvas.bbox("all")),add="+")
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(
            self.canvas_item,width=e.width),add="+")
        self.canvas.bind("<MouseWheel>",self._wheel,add="+")
        self.rows.bind("<MouseWheel>",self._wheel,add="+")
        button=app.hud_settings_button
        screenw=app.winfo_screenwidth()
        screenh=app.winfo_screenheight()
        x,y,w,h=clamp_popup(
            button.winfo_rootx()+button.winfo_width()-360,
            button.winfo_rooty()+button.winfo_height()+4,
            360,560,screenw,screenh)
        self.popup.geometry(f"{w}x{h}+{x}+{y}")
        self.render()
        self.popup.deiconify()
        self.popup.lift()
        self.search_box.focus_set()

    def _wheel(self,event):
        delta=getattr(event,"delta",0)
        if delta:
            self.canvas.yview_scroll(-int(delta/120) or (-1 if delta>0 else 1),
                                     "units")

    def _on_blur(self,event):
        # Let clicks into children acquire focus without closing.
        self.popup.after(130,self._close_if_lost)

    def _close_if_lost(self):
        if not self.popup.winfo_exists():
            return
        focus=self.popup.focus_get()
        if focus is not None and (focus==self.popup or
                                  str(focus).startswith(str(self.popup)+".")):
            return
        self.close()

    def _activate_first(self,event=None):
        if self.first_action is not None:
            self.first_action()
        return "break"

    def _invoke(self,action):
        self.close()
        action()

    def navigate(self,section):
        self.section=section
        self.search.set("")
        self.canvas.yview_moveto(0)
        self.render()
        self.search_box.focus_set()

    def render(self):
        for child in self.rows.winfo_children():
            child.destroy()
        names={"main":"КОМАНДЫ NOVA","permissions":"РАЗРЕШЕНИЯ",
               "ai":"ВЫБОР AI","modes":"РЕЖИМЫ"}
        self.heading.configure(text=names.get(self.section,"КОМАНДЫ NOVA"))
        query=self.search.get().casefold().strip()
        rows=entries(self.app,self.section)
        self.first_action=None
        if self.section!="main":
            self._row("‹","НАЗАД К КОМАНДАМ",lambda:self.navigate("main"),
                      highlight=True)
        for row in rows:
            if row is None:
                if not query:
                    sep=tk.Frame(self.rows,bg=EDGE,height=1)
                    sep.pack(fill="x",pady=6,padx=8)
                continue
            icon,label,callback,subsection=row
            if query and query not in label.casefold():
                continue
            if subsection is not None:
                callback=lambda dest=subsection:self.navigate(dest)
            else:
                action=callback
                callback=lambda fn=action:self._invoke(fn)
            if self.first_action is None:
                self.first_action=callback
            self._row(icon,label,callback,arrow=bool(subsection))
        self.canvas.yview_moveto(0)

    def _row(self,icon,label,command,arrow=False,highlight=False):
        row=tk.Frame(self.rows,bg=BG)
        row.pack(fill="x",pady=2)
        marker=tk.Label(row,text=icon,fg=CYAN,bg=BG,width=3,
                        font=("Segoe UI Symbol",12))
        marker.pack(side="left",padx=(5,2))
        button=tk.Button(row,text=label+("   ›" if arrow else ""),
            command=command,anchor="w",bg=BG,fg=TEXT,relief="flat",
            bd=0,font=("Segoe UI",10,"bold" if highlight else "normal"),
            activebackground=HOVER,activeforeground=CYAN,
            padx=6,pady=6,cursor="hand2")
        button.pack(side="left",fill="x",expand=True)
        def set_hover(hovered):
            color=HOVER if hovered else BG
            marker.configure(bg=color)
            button.configure(bg=color)
        for child in (button,marker):
            child.bind("<Enter>",lambda event:set_hover(True),add="+")
            child.bind("<Leave>",lambda event:set_hover(False),add="+")

    def close(self):
        if getattr(self.app,"_command_palette",None) is self:
            self.app._command_palette=None
        try:
            self.popup.destroy()
        except tk.TclError:
            pass


def show_palette(app):
    previous=getattr(app,"_command_palette",None)
    if previous is not None:
        previous.close()
        return
    app._command_palette=CommandPalette(app)
