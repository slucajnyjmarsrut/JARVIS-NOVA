# -*- coding: utf-8 -*-
"""Editable JARVIS NOVA video timeline: true trims, cut order, preview, undo.

FFmpeg never starts automatically. Every export requires explicit confirmation.
The project format is a local JSON document, not executable model output.
"""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from video_timeline import (
    ASPECTS, COLORS, MAX_CUTS, TimelineCut, TimelineError, TimelineHistory,
    TimelineProject, _input_video, estimate_seconds,
    load_timeline, render_timeline, save_timeline, validate_timeline,
)
from pro_montage import SAFE_TRANSITIONS


class TimelineWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        from studio_theme import apply_video_theme, BG, CARD, EDGE, CYAN, TEXT
        from windows_titlebar import install_dark_titlebar
        self.title("JARVIS NOVA · Редактор таймлайна")
        self.configure(bg=BG)
        self.geometry(f"{min(980,max(710,self.winfo_screenwidth()-90))}x"
                      f"{min(780,max(560,self.winfo_screenheight()-90))}")
        self.minsize(700, 530)
        apply_video_theme(self)
        install_dark_titlebar(self,background=BG)
        self._busy=False
        self._cancel=threading.Event()
        self._events=queue.Queue()
        self._history=TimelineHistory()
        self._cuts=[]
        self._preview_image=None
        self._latest_video=None
        self.protocol("WM_DELETE_WINDOW",self.close)

        self.aspect=tk.StringVar(value=list(ASPECTS)[0])
        self.color=tk.StringVar(value="natural")
        self.transition=tk.StringVar(value="fade")
        self.fade=tk.StringVar(value="0.17")
        self.volume=tk.StringVar(value="0.18")
        self.music=tk.StringVar()
        self.subtitles=tk.StringVar()
        self.output=tk.StringVar()
        self.trim_start=tk.StringVar(value="0")
        self.trim_length=tk.StringVar(value="2.0")
        self.speed=tk.StringVar(value="1.0")
        self.caption=tk.StringVar()
        self.split_at=tk.StringVar(value="1.0")
        self.status=tk.StringVar(
            value="Добавь свои клипы. Ничего не изменяется до подтверждения экспорта.")
        self._bg=BG
        self._card=CARD
        self._edge=EDGE
        self._cyan=CYAN

        root=ttk.Frame(self,style="Studio.TFrame",padding=12)
        root.pack(fill="both",expand=True)
        ttk.Label(root,text="ТАЙМЛАЙН · МОНТАЖ С УПРАВЛЕНИЕМ КАДРАМИ",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(root,text=(
            "Перетаскивать клипы не обязательно: меняй порядок стрелками, "
            "обрезай, ускоряй, добавляй титр. 10 клипов · до 90 секунд."),
            wraplength=910,style="Studio.Small.TLabel").pack(anchor="w",pady=(3,7))

        preview=tk.Frame(root,bg=CARD,padx=8,pady=8)
        preview.pack(fill="x",pady=(0,8))
        self._preview_label=tk.Label(
            preview,bg="#07101A",fg="#A9BFCE",width=45,height=9,
            text="ПРЕДПРОСМОТР КАДРА\n(без переходов и звука)",
            font=("Segoe UI",10))
        self._preview_label.pack(side="left",fill="both",expand=True)
        control_preview=ttk.Frame(preview,style="Studio.Card.TFrame")
        control_preview.pack(side="right",padx=(9,1))
        ttk.Button(
            control_preview,text="Показать выбранный кадр",
            command=self.preview_frame,
            style="Studio.TButton").pack(fill="x",pady=(0,8))
        ttk.Label(control_preview,text="Исходный кадр; эффекты\nвидны после экспорта.",
                  style="Studio.Card.TLabel",justify="left").pack(anchor="w")

        self._timeline=tk.Canvas(root,bg="#0B1D30",height=68,
                                  highlightthickness=1,highlightbackground=EDGE)
        self._timeline.pack(fill="x",pady=(0,7))
        self._timeline.bind("<Configure>",lambda event:self._draw_timeline())
        self._timeline.bind("<Button-1>",self._timeline_clicked)

        middle=ttk.Frame(root,style="Studio.TFrame")
        middle.pack(fill="both",expand=True)
        left=ttk.Frame(middle,style="Studio.TFrame")
        left.pack(side="left",fill="both",expand=True,padx=(0,9))
        self._list=tk.Listbox(
            left,bg=CARD,fg=TEXT,selectbackground="#11636A",
            selectforeground="#FFFFFF",font=("Consolas",10),
            activestyle="none",height=7,exportselection=False)
        self._list.pack(fill="both",expand=True)
        self._list.bind("<<ListboxSelect>>",self._selected)
        commands=ttk.Frame(left,style="Studio.TFrame")
        commands.pack(fill="x",pady=(5,5))
        for name,action in (
            ("+ Клип",self.add_videos),("− Удалить",self.remove),
            ("↑",lambda:self.move(-1)),("↓",lambda:self.move(1)),
            ("Копия",self.duplicate),("Разделить",self.split),
        ):
            ttk.Button(commands,text=name,command=action,
                       style="Studio.TButton").pack(side="left",padx=(0,4))
        history=ttk.Frame(left,style="Studio.TFrame")
        history.pack(fill="x")
        ttk.Button(history,text="Отменить",command=self.undo,
                   style="Studio.TButton").pack(side="left",padx=(0,5))
        ttk.Button(history,text="Вернуть",command=self.redo,
                   style="Studio.TButton").pack(side="left",padx=(0,5))
        ttk.Button(history,text="Сохранить проект JSON",command=self.save_project,
                   style="Studio.TButton").pack(side="left",padx=(0,5))
        ttk.Button(history,text="Открыть проект",command=self.load_project,
                   style="Studio.TButton").pack(side="left")

        right=ttk.Frame(middle,style="Studio.TFrame")
        right.pack(side="right",fill="y")
        self._form_entry(right,"Старт в источнике, сек",self.trim_start)
        self._form_entry(right,"Длина в финале, сек",self.trim_length)
        self._form_entry(right,"Скорость (0.5–2)",self.speed)
        self._form_entry(right,"Титр выбранного кадра",self.caption)
        ttk.Button(right,text="Применить к клипу",command=self.apply_cut,
                   style="Studio.Primary.TButton").pack(fill="x",pady=(2,5))
        self._form_entry(right,"Разделить на секунде",self.split_at)

        settings=ttk.Frame(root,style="Studio.TFrame")
        settings.pack(fill="x",pady=(8,5))
        self._combo(settings,"Кадр",self.aspect,list(ASPECTS),26)
        self._combo(settings,"Цвет",self.color,list(COLORS),15)
        self._combo(settings,"Переход",self.transition,sorted(SAFE_TRANSITIONS),16)
        self._form_entry(settings,"Переход, сек",self.fade,width=7,side="left")
        self._form_entry(settings,"Музыка, 0–0.45",self.volume,width=7,side="left")

        audio=ttk.Frame(root,style="Studio.TFrame")
        audio.pack(fill="x",pady=(0,6))
        ttk.Label(audio,text="Музыка:",style="Studio.TLabel").pack(side="left")
        ttk.Entry(audio,textvariable=self.music,
                  style="Studio.TEntry").pack(side="left",fill="x",expand=True,padx=5)
        ttk.Button(audio,text="Выбрать",command=self.choose_music,
                   style="Studio.TButton").pack(side="left")
        ttk.Button(audio,text="Очистить",command=lambda:self.music.set(""),
                   style="Studio.TButton").pack(side="left",padx=(4,0))
        subrow=ttk.Frame(root,style="Studio.TFrame")
        subrow.pack(fill="x",pady=(0,5))
        ttk.Label(subrow,text="SRT:",style="Studio.TLabel").pack(side="left")
        ttk.Entry(subrow,textvariable=self.subtitles,
                  style="Studio.TEntry").pack(side="left",fill="x",
                                             expand=True,padx=5)
        ttk.Button(subrow,text="Субтитры",command=self.choose_subtitles,
                   style="Studio.TButton").pack(side="left")
        ttk.Button(subrow,text="Очистить",command=lambda:self.subtitles.set(""),
                   style="Studio.TButton").pack(side="left",padx=(4,0))
        outrow=ttk.Frame(root,style="Studio.TFrame")
        outrow.pack(fill="x",pady=(0,5))
        ttk.Label(outrow,text="MP4:",style="Studio.TLabel").pack(side="left")
        ttk.Entry(outrow,textvariable=self.output,
                  style="Studio.TEntry").pack(side="left",fill="x",expand=True,padx=5)
        ttk.Button(outrow,text="Выбрать новый MP4",command=self.choose_output,
                   style="Studio.TButton").pack(side="left")

        footer=ttk.Frame(self,style="Studio.TFrame",padding=10)
        footer.pack(fill="x")
        ttk.Label(footer,textvariable=self.status,
                  wraplength=910,style="Studio.Small.TLabel").pack(anchor="w")
        bar=ttk.Frame(footer,style="Studio.TFrame")
        bar.pack(fill="x",pady=(6,0))
        self._export_button=ttk.Button(
            bar,text="ЭКСПОРТ MP4 · С ПРОВЕРКОЙ",
            command=self.export,style="Studio.Primary.TButton")
        self._export_button.pack(side="left")
        ttk.Button(bar,text="СТОП",command=self.cancel,
                   style="Studio.TButton").pack(side="left",padx=(8,0))
        next_actions=ttk.Frame(footer,style="Studio.TFrame")
        next_actions.pack(fill="x",pady=(5,0))
        ttk.Button(next_actions,text="Дальше: слои / озвучка",
                   command=self.open_layers,style="Studio.TButton").pack(
                       side="left",padx=(0,6))
        ttk.Button(next_actions,text="Открыть FilmCraft",
                   command=self.open_filmcraft,
                   style="Studio.TButton").pack(side="left",padx=(0,6))
        ttk.Button(next_actions,text="Дальше: публикация",
                   command=self.open_publish,
                   style="Studio.TButton").pack(side="left")
        self.after(130,self._pump)

    def _form_entry(self,parent,title,var,*,width=18,side=None):
        frame=ttk.Frame(parent,style="Studio.TFrame")
        frame.pack(side=side or "top",fill="x" if side is None else "none",
                   padx=(0,5),pady=(0,5))
        ttk.Label(frame,text=title,style="Studio.TLabel").pack(anchor="w")
        ttk.Entry(frame,textvariable=var,width=width,
                  style="Studio.TEntry").pack(fill="x")

    def _combo(self,parent,title,var,values,width):
        frame=ttk.Frame(parent,style="Studio.TFrame")
        frame.pack(side="left",padx=(0,5))
        ttk.Label(frame,text=title,style="Studio.TLabel").pack(anchor="w")
        ttk.Combobox(
            frame,textvariable=var,values=values, width=width,
            state="readonly",style="Studio.TCombobox").pack()

    def _index(self):
        selection=self._list.curselection()
        return int(selection[0]) if selection else None

    def _select(self,index):
        self._list.selection_clear(0,"end")
        if self._cuts and index is not None:
            index=max(0,min(index,len(self._cuts)-1))
            self._list.selection_set(index)
            self._list.activate(index)
            self._list.see(index)
            self._selected()
        self._draw_timeline()

    def _selected(self,event=None):
        index=self._index()
        if index is not None and 0<=index<len(self._cuts):
            cut=self._cuts[index]
            self.trim_start.set(str(cut.source_start))
            self.trim_length.set(str(cut.duration))
            self.speed.set(str(cut.speed))
            self.caption.set(cut.caption)
        self._draw_timeline()

    def _refresh(self,index=None):
        self._list.delete(0,"end")
        for i,cut in enumerate(self._cuts):
            self._list.insert(
                "end",f"{i+1:02d}  {Path(cut.path).name[:26]:26} "
                f"{cut.duration:4.1f}c  x{cut.speed:.2f}"
                + ("  · титр" if cut.caption else ""))
        self._select(index)

    def _draw_timeline(self):
        if not hasattr(self,"_timeline"):
            return
        canvas=self._timeline
        canvas.delete("all")
        if not self._cuts:
            canvas.create_text(15,27,text="Добавь клипы — появится шкала монтажа",
                               fill="#A9BFCE",anchor="w")
            return
        total=sum(c.duration for c in self._cuts)
        width=max(240,canvas.winfo_width()-16)
        offset=8.
        selected=self._index()
        for i,cut in enumerate(self._cuts):
            span=width*cut.duration/total
            border="#43DFE5" if i==selected else "#2D5269"
            fill="#11636A" if i==selected else "#10253A"
            canvas.create_rectangle(offset,7,offset+span,55,
                                     fill=fill,outline=border,width=2)
            if span>=58:
                canvas.create_text(
                    offset+5,18,text=f"{i+1} · {cut.duration:.1f} c",
                    fill="#EAF5FC",anchor="w",font=("Segoe UI",9))
            if span>=90:
                canvas.create_text(
                    offset+5,41,text=Path(cut.path).name[:14],
                    fill="#A9BFCE",anchor="w",font=("Segoe UI",8))
            offset+=span
        canvas.create_text(width,63,text=f"{total:.1f} с до переходов",
                           anchor="e",fill="#A9BFCE",font=("Segoe UI",8))

    def _timeline_clicked(self,event):
        if not self._cuts:
            return
        total=sum(c.duration for c in self._cuts)
        t=(event.x-8)/max(1,self._timeline.winfo_width()-16)*total
        elapsed=0.
        for i,cut in enumerate(self._cuts):
            elapsed+=cut.duration
            if t<=elapsed:
                self._select(i)
                return
        self._select(len(self._cuts)-1)

    def _modify(self,new,index=None):
        if self._busy:
            return
        old=tuple(self._cuts)
        if tuple(new)==old:
            return
        self._history.push(old)
        self._cuts=list(new)
        self._refresh(index)
        self.status.set("Таймлайн изменён. Экспорт ещё не выполнялся.")

    def add_videos(self):
        if self._busy:
            return
        names=filedialog.askopenfilenames(
            parent=self,title="Выбери свои видеоклипы (до 10)",
            filetypes=[("Видео","*.mp4 *.mov *.mkv *.webm *.avi *.m4v")])
        if not names:
            return
        try:
            if len(self._cuts)+len(names)>MAX_CUTS:
                raise TimelineError("Максимум 10 клипов.")
            files=[_input_video(Path(name)) for name in names]
            cuts=self._cuts+[TimelineCut(p) for p in files]
            self._modify(cuts,len(cuts)-1)
        except (TimelineError,OSError) as exc:
            messagebox.showerror("Клипы",str(exc),parent=self)

    def remove(self):
        index=self._index()
        if index is not None:
            clips=self._cuts[:index]+self._cuts[index+1:]
            self._modify(clips,index-1 if clips else None)

    def duplicate(self):
        index=self._index()
        if index is None:
            return
        if len(self._cuts)>=MAX_CUTS:
            messagebox.showwarning("Клипы","Максимум 10 клипов.",parent=self)
            return
        self._modify(
            self._cuts[:index+1]+[self._cuts[index]]+self._cuts[index+1:],
            index+1)

    def move(self,step):
        index=self._index()
        if index is None or not 0<=index+step<len(self._cuts):
            return
        cuts=self._cuts.copy()
        cuts[index],cuts[index+step]=cuts[index+step],cuts[index]
        self._modify(cuts,index+step)

    def apply_cut(self):
        index=self._index()
        if index is None:
            return
        try:
            cut=replace(
                self._cuts[index],
                source_start=float(self.trim_start.get()),
                duration=float(self.trim_length.get()),
                speed=float(self.speed.get()),
                caption=self.caption.get().strip())
            if (not 0<=cut.source_start<=18000 or
                    not .75<=cut.duration<=15 or
                    not .5<=cut.speed<=2 or
                    not len(cut.caption)<=110):
                raise ValueError("start/duration/speed/title")
            self._modify(self._cuts[:index]+[cut]+self._cuts[index+1:],index)
        except (ValueError,OverflowError):
            messagebox.showerror(
                "Клип","Начало от 0, длина 0.75–15 сек, скорость 0.5–2, "
                "титр до 110 символов.",parent=self)

    def split(self):
        index=self._index()
        if index is None:
            return
        if len(self._cuts)>=MAX_CUTS:
            messagebox.showwarning("Разделить","Максимум 10 клипов.",parent=self)
            return
        cut=self._cuts[index]
        try:
            at=float(self.split_at.get())
            if not .75<=at<=cut.duration-.75:
                raise ValueError("split")
        except ValueError:
            messagebox.showwarning(
                "Разделить","Укажи время разреза с запасом 0.75 с с каждой стороны.",
                parent=self)
            return
        first=replace(cut,duration=round(at,3))
        second=replace(
            cut,source_start=round(cut.source_start+at*cut.speed,3),
            duration=round(cut.duration-at,3))
        self._modify(
            self._cuts[:index]+[first,second]+self._cuts[index+1:],index+1)

    def undo(self):
        if self._busy:
            return
        self._cuts=list(self._history.undo(tuple(self._cuts)))
        self._refresh(min(self._index() or 0,len(self._cuts)-1)
                      if self._cuts else None)

    def redo(self):
        if self._busy:
            return
        self._cuts=list(self._history.redo(tuple(self._cuts)))
        self._refresh(min(self._index() or 0,len(self._cuts)-1)
                      if self._cuts else None)

    def choose_music(self):
        selected=filedialog.askopenfilename(
            parent=self,title="Выбери музыку, на которую у тебя есть права",
            filetypes=[("Аудио","*.mp3 *.m4a *.wav *.flac *.ogg *.aac")])
        if selected:
            self.music.set(selected)

    def choose_subtitles(self):
        selected=filedialog.askopenfilename(
            parent=self,title="Выбери свой UTF-8 файл субтитров SRT",
            filetypes=[("SubRip subtitles","*.srt")])
        if selected:
            self.subtitles.set(selected)

    def choose_output(self):
        selected=filedialog.asksaveasfilename(
            parent=self,title="Создать НОВЫЙ MP4, без перезаписи",
            defaultextension=".mp4",filetypes=[("MP4","*.mp4")],
            initialfile="JARVIS_TIMELINE.mp4")
        if selected:
            self.output.set(selected)

    def _project(self,*,export=False):
        try:
            project=TimelineProject(
                cuts=tuple(self._cuts),output=Path(self.output.get()),
                aspect=self.aspect.get(),color=self.color.get(),
                transition=self.transition.get(),
                transition_seconds=float(self.fade.get()),
                music=Path(self.music.get()) if self.music.get().strip() else None,
                music_volume=float(self.volume.get()),
                subtitles=Path(self.subtitles.get()) if
                          self.subtitles.get().strip() else None)
        except (ValueError,TypeError) as exc:
            raise TimelineError("Проверь числовые настройки перехода и музыки.") from exc
        return validate_timeline(project,for_export=export)

    def save_project(self):
        if self._busy:
            return
        try:
            project=self._project()
        except (TimelineError,OSError) as exc:
            messagebox.showerror("Проект",str(exc),parent=self)
            return
        destination=filedialog.asksaveasfilename(
            parent=self,title="Сохранить редактируемый таймлайн",
            defaultextension=".json",filetypes=[("JARVIS Timeline","*.json")],
            initialfile="JARVIS_PROJECT.json")
        if destination:
            try:
                saved=save_timeline(project,Path(destination))
                self.status.set("Таймлайн сохранён: "+str(saved))
            except (TimelineError,OSError) as exc:
                messagebox.showerror("Проект",str(exc),parent=self)

    def load_project(self):
        if self._busy:
            return
        destination=filedialog.askopenfilename(
            parent=self,title="Открыть свой таймлайн",
            filetypes=[("JARVIS Timeline","*.json")])
        if not destination:
            return
        try:
            project=load_timeline(Path(destination))
        except (TimelineError,OSError) as exc:
            messagebox.showerror("Проект",str(exc),parent=self)
            return
        self._history=TimelineHistory()
        self._cuts=list(project.cuts)
        self.aspect.set(project.aspect)
        self.color.set(project.color)
        self.transition.set(project.transition)
        self.fade.set(str(project.transition_seconds))
        self.volume.set(str(project.music_volume))
        self.music.set(str(project.music) if project.music else "")
        self.subtitles.set(str(project.subtitles) if project.subtitles else "")
        output=Path(project.output)
        if output.exists() or output.with_name(
                output.stem+"_TIMELINE.json").exists():
            output=output.with_name(output.stem+"_again.mp4")
        self.output.set(str(output))
        self._refresh(0)
        self.status.set("Проект загружен. Проверь параметры перед экспортом.")

    def preview_frame(self):
        if self._busy:
            return
        index=self._index()
        if index is None:
            return
        cut=self._cuts[index]
        self._cancel.clear()
        self._busy=True
        self.status.set("Получаю один кадр через локальный FFmpeg.")
        def worker():
            try:
                from viral_studio import ffmpeg_tools, _execute
                ffmpeg,_=ffmpeg_tools()
                image=_execute([
                    ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
                    "-ss",f"{cut.source_start:.3f}",
                    "-i",str(_input_video(cut.path)),
                    "-vf","scale=400:-2","-frames:v","1",
                    "-f","image2pipe","-c:v","png","-",
                ],timeout=30,cancel=self._cancel)
                if not 128<len(image)<4_000_000:
                    raise TimelineError("Кадр не удалось показать.")
                self._events.put(("preview",image))
            except Exception as exc:
                self._events.put(("error",str(exc)[:300]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-timeline-preview").start()

    def export(self):
        if self._busy:
            return
        try:
            project=self._project(export=True)
            length=estimate_seconds(project)
        except (TimelineError,OSError,ValueError) as exc:
            messagebox.showerror("Проверка проекта",str(exc),parent=self)
            return
        if not messagebox.askyesno(
            "Подтвердить экспорт таймлайна?",
            f"Клипов: {len(project.cuts)} · ~{length:.1f} секунд\n"
            f"Размер: {ASPECTS[project.aspect]}\n"
            f"Цвет: {project.color} · переход: {project.transition}\n"
            f"Музыка: {Path(project.music).name if project.music else 'нет'}\n"
            f"Субтитры: {Path(project.subtitles).name if project.subtitles else 'нет'}\n"
            f"Новый MP4: {project.output}\n\n"
            "FFmpeg обработает выбранные файлы локально. Оригиналы не "
            "изменятся. Никакой публикации или загрузки в интернет.",
            parent=self):
            return
        self._cancel.clear()
        self._busy=True
        self._export_button.configure(state="disabled")
        self.status.set("Начинаю офлайн-экспорт.")
        def callback(completed,total,label):
            self._events.put(("progress",(
                completed,total,label)))
        def worker():
            try:
                result=render_timeline(
                    project,cancel=self._cancel,progress=callback)
                self._events.put(("done",result))
            except Exception as exc:
                self._events.put(("error",str(exc)[:300]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-timeline-render").start()

    def _pump(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                event,value=self._events.get_nowait()
                if event=="progress":
                    n,total,stage=value
                    self.status.set(f"{stage} · {n}/{total}")
                    continue
                self._busy=False
                self._export_button.configure(state="normal")
                if event=="preview":
                    try:
                        from PIL import Image, ImageTk
                        image=Image.open(BytesIO(value))
                        image.thumbnail((400,250))
                        self._preview_image=ImageTk.PhotoImage(image)
                        self._preview_label.configure(
                            image=self._preview_image,text="")
                        self.status.set("Предпросмотр исходного кадра готов.")
                    except (OSError,ValueError) as exc:
                        self.status.set("Предпросмотр не готов: "+str(exc)[:100])
                elif event=="filmcraft":
                    self.status.set("FilmCraft открыт: "+value)
                elif event=="done":
                    self._latest_video=Path(value["output"])
                    self.status.set(
                        "ГОТОВО: "+value["output"]+
                        " · монтажный лист _TIMELINE.json. Можно добавить слои.")
                    messagebox.showinfo(
                        "Монтаж завершён",
                        "MP4 создан и прошёл техническую проверку.\n"+
                        value["output"]+"\nИсходные файлы не изменены.",
                        parent=self)
                else:
                    self.status.set("Экспорт/предпросмотр не завершён: "+value)
                    messagebox.showerror("Таймлайн",value,parent=self)
        except queue.Empty:
            pass
        self.after(130,self._pump)

    def cancel(self):
        if self._busy:
            self._cancel.set()
            self.status.set("Запросил остановку FFmpeg; неполный MP4 не сохраняется.")

    def open_filmcraft(self):
        if self._busy:
            return
        if not self._latest_video or not self._latest_video.is_file():
            messagebox.showinfo(
                "FilmCraft","Сначала экспортируй MP4 с таймлайна.",parent=self)
            return
        from filmcraft_bridge import find_filmcraft, FilmCraftError
        try:
            executable=find_filmcraft()
        except FilmCraftError:
            messagebox.showinfo(
                "FilmCraft","FilmCraft не установлен. Его можно установить "
                "из видеостудии JARVIS с отдельным подтверждением. "
                "Ничего автоматически не скачивается.",parent=self)
            return
        if not messagebox.askyesno(
            "Открыть FilmCraft?",
            "Открыть твой готовый MP4 и доступные редактируемые исходные "
            "склейки в установленном FilmCraft? Ничего не публикуется.",
            parent=self):
            return
        self._busy=True
        self.status.set("Передаю проверенный MP4 в локальный FilmCraft.")
        def worker():
            try:
                from filmcraft_bridge import open_in_filmcraft
                result=open_in_filmcraft(executable,self._latest_video)
                self._events.put(("filmcraft",str(result.mode)))
            except Exception as exc:
                self._events.put(("error",str(exc)[:300]))
        threading.Thread(target=worker,daemon=True,
                         name="jarvis-timeline-filmcraft").start()

    def open_layers(self):
        if not self._latest_video or not self._latest_video.is_file():
            messagebox.showinfo(
                "Слои","Сначала создай MP4 через экспорт таймлайна.",parent=self)
            return
        from multitrack_ui import MultitrackWindow
        MultitrackWindow(self,base_video=self._latest_video)

    def open_publish(self):
        if not self._latest_video or not self._latest_video.is_file():
            messagebox.showinfo(
                "Публикация","Сначала экспортируй собственное видео.",parent=self)
            return
        from creator_publish_ui import PublishWindow
        PublishWindow(self,video=self._latest_video)

    def close(self):
        if self._busy:
            if not messagebox.askyesno(
                "Остановить монтаж?",
                "Текущий рендер или предпросмотр будет остановлен. "
                "Изменения в памяти таймлайна не сохранятся.",
                parent=self):
                return
            self._cancel.set()
        self.destroy()
