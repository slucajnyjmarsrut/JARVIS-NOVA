# -*- coding: utf-8 -*-
"""Dark, user-controlled multi-track video editor for JARVIS NOVA.

Never uploads anything. Browsing, FFmpeg rendering and filesystem writes
require an explicit user choice and final confirmation.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from multitrack_composer import (
    MultitrackError, MultitrackProject, POSITIONS, MOTIONS, VisualLayer,
    render_multitrack, validate_project, save_multitrack, load_multitrack,
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
        self._busy_since=None
        self._last_busy_second=-1
        self._last_export=None
        self.protocol("WM_DELETE_WINDOW", self.close)

        outer=ttk.Frame(self,style="Studio.TFrame",padding=14)
        outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="МНОГОДОРОЖЕЧНЫЙ МОНТАЖ · OFFLINE",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(
            outer,text="Основа + 3 наложения + титр + музыка + озвучка. "
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
        self.layer_widths=[]
        self.layer_opacities=[]
        self.layer_motions=[]
        self.layer_motion_times=[]
        self.music_volume=tk.StringVar(value="0.22")

        self._picker(body,"01 · ОСНОВНОЕ MP4",self.base,"video")
        for index in (1,2,3):
            self._picker(body,f"02 · ВИДЕО / КАРТИНКА №{index}",
                         item:=tk.StringVar(),"visual")
            self.layer_files.append(item)
            row=ttk.Frame(body,style="Studio.TFrame")
            row.pack(fill="x",pady=(0,9))
            position=tk.StringVar(value="bottom-right")
            start=tk.StringVar(value="0")
            duration=tk.StringVar(value="4")
            width=tk.StringVar(value="26")
            opacity=tk.StringVar(value="1.0")
            motion=tk.StringVar(value="static")
            motion_time=tk.StringVar(value="0.45")
            self.layer_motions.append(motion)
            self.layer_motion_times.append(motion_time)
            self.layer_widths.append(width)
            self.layer_opacities.append(opacity)
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
            options=ttk.Frame(body,style="Studio.TFrame")
            options.pack(fill="x",pady=(0,9))
            ttk.Label(options,text="Размер %:",style="Studio.TLabel").pack(side="left")
            ttk.Entry(options,textvariable=width,width=6,
                      style="Studio.TEntry").pack(side="left",padx=(6,15))
            ttk.Label(options,text="Прозрачность (0.1–1):",
                      style="Studio.TLabel").pack(side="left")
            ttk.Entry(options,textvariable=opacity,width=6,
                      style="Studio.TEntry").pack(side="left",padx=(6,0))
            animation=ttk.Frame(body,style="Studio.TFrame")
            animation.pack(fill="x",pady=(0,10))
            ttk.Label(animation,text="Анимация:",
                      style="Studio.TLabel").pack(side="left")
            ttk.Combobox(animation,textvariable=motion,values=MOTIONS,
                         state="readonly",width=16,
                         style="Studio.TCombobox").pack(side="left",padx=(6,15))
            ttk.Label(animation,text="Время движения, с:",
                      style="Studio.TLabel").pack(side="left")
            ttk.Entry(animation,textvariable=motion_time,width=7,
                      style="Studio.TEntry").pack(side="left",padx=(6,0))

        ttk.Label(body,text="03 · ТИТР НА ЭКРАНЕ (необязательно)",
                  style="Studio.TLabel").pack(anchor="w")
        ttk.Entry(body,textvariable=self.title_text,
                  style="Studio.TEntry").pack(fill="x",pady=(3,10))
        self._picker(body,"04 · ФОНОВАЯ МУЗЫКА",self.music,"audio")
        volume_row=ttk.Frame(body,style="Studio.TFrame")
        volume_row.pack(fill="x",pady=(0,8))
        ttk.Label(volume_row,text="Громкость музыки (0–0.7)",
                  style="Studio.TLabel").pack(side="left")
        ttk.Entry(volume_row,textvariable=self.music_volume,
                  width=8,style="Studio.TEntry").pack(side="left",padx=(8,0))
        self._picker(body,"05 · ОЗВУЧКА / ГОЛОС",self.voice,"audio")
        self._picker(body,"06 · НОВЫЙ РЕЗУЛЬТАТ MP4",self.output,"output")

        footer=ttk.Frame(self,style="Studio.TFrame",padding=12)
        footer.pack(fill="x")
        self.status=tk.StringVar(value="Выбери основной MP4 и место для нового видео.")
        ttk.Label(footer,textvariable=self.status,
                  style="Studio.Small.TLabel",wraplength=780).pack(anchor="w")
        self._progress=ttk.Progressbar(
            footer,mode="indeterminate",style="Studio.Horizontal.TProgressbar")
        self._progress.pack(fill="x",pady=(5,1))
        actions=ttk.Frame(footer,style="Studio.TFrame")
        actions.pack(fill="x",pady=(7,0))
        self.go=ttk.Button(
            actions,text="ПРОВЕРИТЬ И СОБРАТЬ MP4",
            style="Studio.Primary.TButton",command=self.start)
        self.go.pack(side="left")
        ttk.Button(actions,text="ОТМЕНА",style="Studio.TButton",
                   command=self.cancel).pack(side="left",padx=(9,0))
        ttk.Button(actions,text="Сохранить проект",
                   style="Studio.TButton",
                   command=self.save_project).pack(side="right",padx=(6,0))
        ttk.Button(actions,text="Открыть проект",
                   style="Studio.TButton",
                   command=self.load_project).pack(side="right")
        ttk.Button(footer,text="Просмотреть готовое видео в Windows-плеере",
                   style="Studio.TButton",command=self.open_finished_video
                   ).pack(anchor="w",pady=(4,0))
        self._attach_wheel(body,scroller)
        self.after(130,self._pump)

    def _attach_wheel(self,widget,canvas):
        def on_wheel(event):
            if event.delta:
                canvas.yview_scroll(-1 if event.delta>0 else 1,"units")
            return "break"
        widget.bind("<MouseWheel>",on_wheel,add="+")
        for child in widget.winfo_children():
            self._attach_wheel(child,canvas)

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

    def _project(self,*,for_export=True):
        layers=[]
        for file,pos,start,seconds,width,opacity,motion,motion_time in zip(
                self.layer_files,self.layer_positions,
                self.layer_starts,self.layer_durations,
                self.layer_widths,self.layer_opacities,
                self.layer_motions,self.layer_motion_times):
            if file.get().strip():
                layers.append(VisualLayer(
                    Path(file.get()),start=float(start.get()),
                    duration=float(seconds.get()),position=pos.get(),
                    width_percent=int(width.get()),
                    opacity=float(opacity.get()),
                    motion=motion.get(),motion_seconds=float(motion_time.get())))
        return validate_project(MultitrackProject(
            base_video=Path(self.base.get()),
            output_video=Path(self.output.get()),
            layers=tuple(layers),
            title=self.title_text.get().strip(),
            music=Path(self.music.get()) if self.music.get().strip() else None,
            voiceover=Path(self.voice.get()) if self.voice.get().strip() else None,
            music_volume=float(self.music_volume.get()),
        ),for_export=for_export)

    def save_project(self):
        if self._busy:
            return
        try:
            project=self._project(for_export=False)
        except (MultitrackError,ValueError,OSError) as exc:
            messagebox.showerror("Проект",str(exc),parent=self)
            return
        selected=filedialog.asksaveasfilename(
            parent=self,title="Сохранить редактируемые дорожки",
            defaultextension=".json",filetypes=[("JARVIS Multitrack","*.json")])
        if selected:
            try:
                path=save_multitrack(project,Path(selected))
                self.status.set("Дорожки сохранены: "+str(path))
            except (MultitrackError,OSError) as exc:
                messagebox.showerror("Проект",str(exc),parent=self)

    def load_project(self):
        if self._busy:
            return
        selected=filedialog.askopenfilename(
            parent=self,title="Открыть сохранённые дорожки",
            filetypes=[("JARVIS Multitrack","*.json")])
        if not selected:
            return
        try:
            project=load_multitrack(Path(selected))
        except (MultitrackError,OSError) as exc:
            messagebox.showerror("Проект",str(exc),parent=self)
            return
        self.base.set(str(project.base_video))
        self.title_text.set(project.title)
        self.music.set(str(project.music) if project.music else "")
        self.voice.set(str(project.voiceover) if project.voiceover else "")
        self.music_volume.set(str(project.music_volume))
        for i in range(3):
            layer=project.layers[i] if i<len(project.layers) else None
            self.layer_files[i].set(str(layer.path) if layer else "")
            self.layer_positions[i].set(layer.position if layer else "bottom-right")
            self.layer_starts[i].set(str(layer.start) if layer else "0")
            self.layer_durations[i].set(str(layer.duration) if layer else "4")
            self.layer_widths[i].set(str(layer.width_percent) if layer else "26")
            self.layer_opacities[i].set(str(layer.opacity) if layer else "1.0")
            self.layer_motions[i].set(layer.motion if layer else "static")
            self.layer_motion_times[i].set(
                str(layer.motion_seconds) if layer else "0.45")
        output=Path(project.output_video)
        if output.exists() or output.with_name(
                output.stem+"_MULTITRACK.json").exists():
            output=output.with_name(output.stem+"_again.mp4")
        self.output.set(str(output))
        self.status.set("Проект загружен. Проверь параметры и новый MP4.")

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
        self._busy_since=time.monotonic()
        self._last_busy_second=-1
        self._progress.start(14)
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
                self._busy_since=None
                self._progress.stop()
                self.go.configure(state="normal")
                if kind=="done":
                    self._last_export=Path(value["output"])
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
        if self._busy and self._busy_since is not None:
            seconds=int(time.monotonic()-self._busy_since)
            if seconds!=self._last_busy_second:
                self._last_busy_second=seconds
                self.status.set(
                    f"FFmpeg обрабатывает слои: {seconds} с. "
                    "При ошибке/остановке частичный MP4 удаляется. "
                    "Нажми ОТМЕНА, чтобы остановить.")
        self.after(130,self._pump)

    def open_finished_video(self):
        if self._busy:
            return
        if self._last_export is None or not self._last_export.is_file():
            selected=filedialog.askopenfilename(
                parent=self,title="Выбери готовое MP4 для просмотра",
                filetypes=[("MP4","*.mp4")])
            if not selected:
                return
            video=Path(selected)
        else:
            video=self._last_export
        try:
            from video_preview import open_local_mp4
            opened=open_local_mp4(video,confirmed=True)
            self.status.set("Видео открыто в системном плеере: "+opened.name)
        except (OSError,ValueError,PermissionError) as exc:
            messagebox.showerror("Просмотр готового MP4",str(exc),parent=self)

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
