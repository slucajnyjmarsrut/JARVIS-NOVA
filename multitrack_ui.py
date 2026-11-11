# -*- coding: utf-8 -*-
"""Dark, user-controlled multi-track video editor for JARVIS NOVA.

Never uploads anything. Browsing, FFmpeg rendering and filesystem writes
require an explicit user choice and final confirmation.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from multitrack_composer import (
    MultitrackError, MultitrackProject, POSITIONS, VisualLayer,
    render_multitrack, validate_project,
)


class MultitrackWindow(tk.Toplevel):
    def __init__(self, parent, base_video=None):
        super().__init__(parent)
        from studio_theme import apply_video_theme, BG, CARD, TEXT, CYAN
        from windows_titlebar import install_dark_titlebar
        self.configure(bg=BG)
        self.title("JARVIS NOVA — Многодорожечный монтаж")
        self.geometry(f"{min(880,self.winfo_screenwidth()-70)}x"
                      f"{min(730,self.winfo_screenheight()-70)}")
        self.minsize(590, 480)
        apply_video_theme(self)
        install_dark_titlebar(self, background=BG)
        self._events=queue.Queue()
        self._busy=False
        self._cancel=threading.Event()
        self.protocol("WM_DELETE_WINDOW", self.close)

        outer=ttk.Frame(self,style="Studio.TFrame",padding=14)
        outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="МНОГОДОРОЖЕЧНЫЙ МОНТАЖ · OFFLINE",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(
            outer,text="Основа + 2 наложения + титр + музыка + озвучка. "
            "Оригиналы не меняются, аккаунты и интернет не используются.",
            wraplength=800,style="Studio.Small.TLabel"
        ).pack(anchor="w",pady=(0,9))
        scroller=tk.Canvas(outer,bg=BG,borderwidth=0,highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient="vertical",command=scroller.yview)
        scroller.configure(yscrollcommand=scroll.set)
        scroller.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        body=ttk.Frame(scroller,style="Studio.TFrame",padding=5)
        window=scroller.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda e:scroller.configure(
            scrollregion=scroller.bbox("all")),add="+")
        scroller.bind("<Configure>",lambda e:scroller.itemconfigure(
            window,width=e.width),add="+")

        self.base=tk.StringVar(value=str(base_video) if base_video else "")
        self.output=tk.StringVar()
        self.title_text=tk.StringVar()
        self.music=tk.StringVar()
        self.voice=tk.StringVar()
        self.layer_files=[]
        self.layer_positions=[]
        self.layer_starts=[]
        self.layer_durations=[]

        self._picker(body,"01 · ОСНОВНОЕ MP4",self.base,"video")
        for index in (1,2):
            self._picker(body,f"02 · ВИДЕО / КАРТИНКА №{index}",
                         item:=tk.StringVar(),"visual")
            self.layer_files.append(item)
            row=ttk.Frame(body,style="Studio.TFrame")
            row.pack(fill="x",pady=(0,9))
            position=tk.StringVar(value="bottom-right")
            start=tk.StringVar(value="0")
            duration=tk.StringVar(value="4")
            self.layer_positions.append(position)
            self.layer_starts.append(start)
            self.layer_durations.append(duration)
            ttk.Label(row,text="Положение:",style="Studio.TLabel").pack(side="left")
            ttk.Combobox(row,textvariable=position,values=list(POSITIONS),
                         state="readonly",width=14,
                         style="Studio.TCombobox").pack(side="left",padx=(5,14))
            ttk.Label(row,text="Начало (сек):",style="Studio.TLabel").pack(side="left")
            ttk.Entry(row,textvariable=start,width=6,
                      style="Studio.TEntry").pack(side="left",padx=(5,14))
            ttk.Label(row,text="Длина (сек):",style="Studio.TLabel").pack(side="left")
            ttk.Entry(row,textvariable=duration,width=6,
                      style="Studio.TEntry").pack(side="left",padx=(5,0))

        ttk.Label(body,text="03 · ТИТР НА ЭКРАНЕ (необязательно)",
                  style="Studio.TLabel").pack(anchor="w")
        ttk.Entry(body,textvariable=self.title_text,
                  style="Studio.TEntry").pack(fill="x",pady=(3,10))
        self._picker(body,"04 · ФОНОВАЯ МУЗЫКА",self.music,"audio")
        self._picker(body,"05 · ОЗВУЧКА / ГОЛОС",self.voice,"audio")
        self._picker(body,"06 · НОВЫЙ РЕЗУЛЬТАТ MP4",self.output,"output")

        footer=ttk.Frame(self,style="Studio.TFrame",padding=12)
        footer.pack(fill="x")
        self.status=tk.StringVar(value="Выбери основной MP4 и место для нового видео.")
        ttk.Label(footer,textvariable=self.status,
                  style="Studio.Small.TLabel",wraplength=780).pack(anchor="w")
        actions=ttk.Frame(footer,style="Studio.TFrame")
        actions.pack(fill="x",pady=(7,0))
        self.go=ttk.Button(
            actions,text="ПРОВЕРИТЬ И СОБРАТЬ MP4",
            style="Studio.Primary.TButton",command=self.start)
        self.go.pack(side="left")
        ttk.Button(actions,text="ОТМЕНА",style="Studio.TButton",
                   command=self.cancel).pack(side="left",padx=(9,0))
        self.after(130,self._pump)

    def _picker(self,parent,label,var,kind):
        ttk.Label(parent,text=label,style="Studio.TLabel").pack(anchor="w")
        line=ttk.Frame(parent,style="Studio.TFrame")
        line.pack(fill="x",pady=(2,9))
        ttk.Entry(line,textvariable=var,style="Studio.TEntry").pack(
            side="left",fill="x",expand=True)
        ttk.Button(
            line,text="Выбрать",style="Studio.TButton",
            command=lambda:self._browse(var,kind)).pack(side="left",padx=(7,0))

    def _browse(self,var,kind):
        if kind=="output":
            chosen=filedialog.asksaveasfilename(
                parent=self,title="Создать новый MP4",
                defaultextension=".mp4",
                filetypes=[("Видео MP4","*.mp4")])
        else:
            masks={
                "video":[("Видео","*.mp4 *.mov *.mkv *.webm *.m4v")],
                "visual":[("Видео / изображение","*.mp4 *.mov *.mkv *.webm *.m4v *.png *.jpg *.jpeg *.webp")],
                "audio":[("Аудио","*.mp3 *.m4a *.wav *.aac *.flac *.ogg")],
            }
            chosen=filedialog.askopenfilename(
                parent=self,title="Выбери свой файл",filetypes=masks[kind])
        if chosen:
            var.set(chosen)

    def _project(self):
        layers=[]
        for file,pos,start,seconds in zip(
                self.layer_files,self.layer_positions,
                self.layer_starts,self.layer_durations):
            if file.get().strip():
                layers.append(VisualLayer(
                    Path(file.get()), start=float(start.get()),
                    duration=float(seconds.get()),position=pos.get()))
        return validate_project(MultitrackProject(
            base_video=Path(self.base.get()),
            output_video=Path(self.output.get()),
            layers=tuple(layers),
            title=self.title_text.get().strip(),
            music=Path(self.music.get()) if self.music.get().strip() else None,
            voiceover=Path(self.voice.get()) if self.voice.get().strip() else None,
        ))

    def start(self):
        if self._busy:
            return
        try:
            project=self._project()
        except (MultitrackError,ValueError,OSError) as exc:
            messagebox.showerror("Многодорожечный монтаж",str(exc),parent=self)
            return
        layers=len(project.layers)+int(bool(project.title.strip()))+(
            int(project.music is not None)+int(project.voiceover is not None))
        if not messagebox.askyesno(
            "Разрешить локальный монтаж?",
            "Основа: "+Path(project.base_video).name+
            "\nДополнительных слоёв: "+str(layers)+
            "\nНовый файл: "+str(project.output_video)+
            "\n\nЗапустить FFmpeg? Исходники не изменяются. "
            "Видео и музыка никуда не публикуются.",
            parent=self,
        ):
            return
        self._cancel.clear()
        self._busy=True
        self.go.configure(state="disabled")
        self.status.set("Работает FFmpeg. Проект не отправляется в облако.")
        def worker():
            try:
                result=render_multitrack(project,cancel=self._cancel)
                self._events.put(("done",result))
            except Exception as exc:
                self._events.put(("error",str(exc)[:300]))
        threading.Thread(
            target=worker,daemon=True,name="jarvis-multitrack").start()

    def _pump(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind,value=self._events.get_nowait()
                self._busy=False
                self.go.configure(state="normal")
                if kind=="done":
                    self.status.set(
                        "ГОТОВО: "+value["output"]+
                        " · монтажный лист _MULTITRACK.json сохранён.")
                    messagebox.showinfo(
                        "Монтаж завершён","Готовый MP4: "+value["output"]+
                        "\n\nОригиналы не изменены. Публикации не было.",
                        parent=self)
                else:
                    self.status.set("Монтаж не завершён. "+value)
                    messagebox.showerror("Многодорожечный монтаж",value,parent=self)
        except queue.Empty:
            pass
        self.after(130,self._pump)

    def cancel(self):
        if self._busy:
            self._cancel.set()
            self.status.set("Остановка FFmpeg. Недописанный MP4 будет удалён.")
        else:
            self.status.set("Сейчас нет активного монтажа.")

    def close(self):
        if self._busy:
            if not messagebox.askyesno(
                "Прервать монтаж?",
                "Прервать обработку? Недописанный MP4 не будет сохранён.",
                parent=self):
                return
            self._cancel.set()
        self.destroy()
