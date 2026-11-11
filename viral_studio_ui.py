# -*- coding: utf-8 -*-
"""Native Tk dialog for Viral Studio. Footage stays local; publishing is manual."""
from __future__ import annotations
import os
import queue
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from uuid import uuid4

from viral_studio import (ViralStudioError, create_local_brief, research_trends,
                          template_brief, save_brief, load_brief, render_video)
from online_media import search_free_video, download_free_video, OnlineMediaError
from editing_knowledge import read_ffmpeg_guide
from channel_audience import read_channel_csv, analyze_audience, AudienceDataError
from creator_experts import recommend_topic, expert_report
from video_forecast import evaluate_final_cut, save_review
from post_montage_review import analyze_and_recut
from self_repair import retry_readonly


def _home():
    # Data are preserved by Inno Setup upgrades/uninstalls.
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'JarvisNova' / 'viral_studio'


class ViralStudioWindow(tk.Toplevel):
    def __init__(self, parent, speaker=None):
        super().__init__(parent)
        from studio_theme import (
            apply_video_theme, BG, CARD, ALT, EDGE, CYAN, TEXT, MUTED,
        )
        apply_video_theme(self)
        self.configure(bg=BG)
        self.title("JARVIS NOVA — Видео-студия")
        # Match the dark studio with its native Windows caption and controls.
        from windows_titlebar import install_dark_titlebar
        install_dark_titlebar(self, background=BG)
        screen_w=self.winfo_screenwidth()
        screen_h=self.winfo_screenheight()
        width=min(1050,max(650,screen_w-70))
        height=min(800,max(570,screen_h-100))
        self.geometry(f"{width}x{height}")
        self.minsize(min(650,screen_w),min(520,screen_h))
        self.parent=parent
        self.speaker=speaker
        self.brief=None
        self.project=None
        self.profile=None
        self.rendered_video=None
        self.rendered_info=None
        self.filmcraft_exe=None
        self.running=False
        self.stop_event=threading.Event()
        self._notifications=queue.Queue()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.topic=tk.StringVar(value="")
        self.country=tk.StringVar(value="RU")
        self.web_enabled=tk.BooleanVar(value=False)
        self.scenario_mode=tk.StringVar(value="fast")
        self.pro_enabled=tk.BooleanVar(value=True)
        self.pro_color=tk.StringVar(value="natural")
        self.pro_transition=tk.StringVar(value="0.22")
        self.pro_music=tk.StringVar(value="")
        self.pro_semantic=tk.BooleanVar(value=False)
        self.edit_style=tk.StringVar(value="YouTube Shorts")
        self.status=tk.StringVar(
            value="Укажи тему и создай сценарий. CSV аудитории необязателен.")
        header=tk.Frame(self,bg=BG)
        header.pack(fill="x",padx=18,pady=(14,10))
        ttk.Label(header,text="▣  ВИДЕО-СТУДИЯ NOVA",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(header,
            text="Сценарий → план съёмки → монтаж → ручная доработка FilmCraft",
            style="Studio.Small.TLabel").pack(anchor="w",pady=(2,0))
        # Scroll just the options, not the script: buttons remain available on
        # small screens and the generated output gets most of the window.
        controls_box=tk.Frame(self,bg=BG)
        controls_box.pack(fill="x",padx=15,pady=(0,6))
        self.controls_canvas=tk.Canvas(controls_box,height=330,bg=BG,
                                        highlightthickness=0,bd=0)
        controls_scroll=ttk.Scrollbar(
            controls_box,orient="vertical",
            command=self.controls_canvas.yview,style="Studio.Vertical.TScrollbar")
        self.controls_canvas.pack(side="left",fill="x",expand=True)
        controls_scroll.pack(side="right",fill="y")
        self.controls_canvas.configure(yscrollcommand=controls_scroll.set)
        controls=ttk.Frame(self.controls_canvas,style="Studio.TFrame")
        self._controls_window=self.controls_canvas.create_window(
            (0,0),window=controls,anchor="nw")
        controls.bind("<Configure>",lambda e:self.controls_canvas.configure(
            scrollregion=self.controls_canvas.bbox("all")),add="+")
        self.controls_canvas.bind("<Configure>",lambda e:self.controls_canvas.itemconfigure(
            self._controls_window,width=e.width),add="+")
        self.controls_canvas.bind("<MouseWheel>",lambda e:self.controls_canvas.yview_scroll(
            -1 if e.delta>0 else 1,"units"),add="+")
        # Topic + country + speed controls
        setup=ttk.LabelFrame(controls,text="01 / СЦЕНАРИЙ",
                              padding=(12,9),style="Studio.TLabelframe")
        setup.pack(fill="x",pady=(0,9))
        setup.columnconfigure(0,weight=1)
        ttk.Label(setup,text="Тема ролика",style="Studio.Card.TLabel").grid(
            row=0,column=0,sticky="w",pady=(0,4))
        ttk.Label(setup,text="Страна",style="Studio.Card.TLabel").grid(
            row=0,column=1,sticky="w",padx=(12,0))
        ttk.Entry(setup,textvariable=self.topic,style="Studio.TEntry").grid(
            row=1,column=0,sticky="ew",pady=(0,8))
        ttk.Combobox(setup,textvariable=self.country,
            values=["RU","DE","US","GB","UA","KZ"],width=7,
            state="readonly",style="Studio.TCombobox").grid(
            row=1,column=1,sticky="w",padx=(12,0),pady=(0,8))
        ttk.Label(setup,text="Скорость:",style="Studio.Card.TLabel").grid(
            row=2,column=0,sticky="w")
        speed=ttk.Frame(setup,style="Studio.Card.TFrame")
        speed.grid(row=3,column=0,columnspan=2,sticky="w",pady=(1,3))
        for value,label in (
            ("fast","⚡ Быстро · без ожидания ИИ"),
            ("standard","AI · стандарт"),
            ("deep","AI · подробно"),
        ):
            ttk.Radiobutton(speed,text=label,value=value,
                variable=self.scenario_mode,style="Studio.TRadiobutton").pack(
                side="left",padx=(0,10))
        ttk.Checkbutton(setup,text="Дополнить публичными трендами Google (интернет, с разрешением)",
                        variable=self.web_enabled,
                        style="Studio.TCheckbutton").grid(
            row=4,column=0,columnspan=2,sticky="w",pady=(3,1))
        # Actual interactive actions arranged in a grid, not a row clipping
        # off the right side of a 790px studio window.
        actions=ttk.LabelFrame(controls,text="02 / ДЕЙСТВИЯ",padding=(12,9),
                               style="Studio.TLabelframe")
        actions.pack(fill="x",pady=(0,9))
        for col in (0,1):
            actions.columnconfigure(col,weight=1,uniform="actions")
        def action(row,col,label,command,primary=False):
            button=ttk.Button(actions,text=label,command=command,
                style=("Studio.Primary.TButton" if primary else "Studio.TButton"))
            button.grid(row=row,column=col,sticky="ew",padx=4,pady=4)
            return button
        self.audience_button=action(0,0,"1. Загрузить статистику CSV",self.import_audience)
        self.make_button=action(0,1,"2. СОЗДАТЬ СЦЕНАРИЙ",self.generate,True)
        self.load_button=action(1,0,"Открыть сохранённый сценарий",self.open_brief)
        self.speak_button=action(1,1,"Показать план съёмки",self.read_shots)
        self.edit_button=action(2,0,"3. Монтаж · мои или онлайн-видео",self.montage)
        self.review_button=action(2,1,"4. Проверить монтаж и оценку",self.review)
        self.auto_button=action(3,0,"АВТОМОНТАЖ · СОБРАТЬ MP4",self.auto_montage,True)
        action(3,1,"Отменить текущую работу",self.cancel)
        # Pro options and music remain available, but no crowded single row.
        pro=ttk.LabelFrame(controls,text="03 / ПРОФЕССИОНАЛЬНЫЙ МОНТАЖ",
                            style="Studio.TLabelframe",padding=(12,9))
        pro.pack(fill="x",pady=(0,9))
        ttk.Checkbutton(pro,text="Плавные переходы, анимированные титры",
            variable=self.pro_enabled,style="Studio.TCheckbutton").pack(anchor="w")
        selectors=ttk.Frame(pro,style="Studio.Card.TFrame")
        selectors.pack(fill="x",pady=(4,6))
        ttk.Label(selectors,text="Цвет",style="Studio.Card.TLabel").pack(side="left")
        ttk.Combobox(selectors,textvariable=self.pro_color,
            values=["natural","cinematic","none"],width=11,state="readonly",
            style="Studio.TCombobox").pack(side="left",padx=(7,16))
        ttk.Label(selectors,text="Переход, сек",style="Studio.Card.TLabel").pack(side="left")
        ttk.Combobox(selectors,textvariable=self.pro_transition,
            values=["0","0.16","0.22","0.32"],width=6,state="readonly",
            style="Studio.TCombobox").pack(side="left",padx=(7,0))
        soundtrack=ttk.Frame(pro,style="Studio.Card.TFrame")
        soundtrack.pack(fill="x",pady=(0,5))
        ttk.Label(soundtrack,text="Музыка",style="Studio.Card.TLabel").pack(
            side="left",padx=(0,8))
        ttk.Entry(soundtrack,textvariable=self.pro_music,
                  style="Studio.TEntry").pack(side="left",fill="x",expand=True)
        ttk.Button(soundtrack,text="Выбрать",command=self._choose_music,
                   style="Studio.TButton").pack(side="left",padx=(7,0))
        ttk.Button(soundtrack,text="Очистить",command=lambda:self.pro_music.set(""),
                   style="Studio.TButton").pack(side="left",padx=(6,0))
        ttk.Checkbutton(pro,text="Подбор кадров через Qwen Vision (медленнее)",
            variable=self.pro_semantic,style="Studio.TCheckbutton").pack(anchor="w")
        # Real, independent FFmpeg quick edits using the user's own clips.
        # No AI model, web account, or storyboard is required.
        from popular_edits import STYLES
        edits=ttk.LabelFrame(controls,text="04 / ЭДИТЫ · 16 ПОПУЛЯРНЫХ СТИЛЕЙ",
                             padding=(12,9),style="Studio.TLabelframe")
        edits.pack(fill="x",pady=(0,9))
        ttk.Label(edits,text="Выбери монтаж для Shorts, TikTok, Reels, AMV, игр, влогов и кино.",
                  style="Studio.Card.TLabel").pack(anchor="w",pady=(0,5))
        ttk.Combobox(edits,textvariable=self.edit_style,
                     values=[style.label for style in STYLES],
                     state="readonly",width=36,
                     style="Studio.TCombobox").pack(fill="x",pady=(0,6))
        buttons=ttk.Frame(edits,style="Studio.Card.TFrame")
        buttons.pack(fill="x")
        self.quick_edit_button=ttk.Button(
            buttons,text="СОБРАТЬ ЭДИТ ИЗ СВОИХ КЛИПОВ",
            command=self.quick_montage,style="Studio.Primary.TButton")
        self.quick_edit_button.pack(side="left",padx=(0,8))
        ttk.Button(buttons,text="YouTube / TikTok / Instagram",
                   command=self.open_creator_accounts,
                   style="Studio.TButton").pack(side="left")
        tools=ttk.LabelFrame(controls,text="04 / ИНСТРУМЕНТЫ",padding=(12,9),
                             style="Studio.TLabelframe")
        tools.pack(fill="x",pady=(0,7))
        tools.columnconfigure(0,weight=1)
        tools.columnconfigure(1,weight=1)
        self.filmcraft_button=ttk.Button(
            tools,text="FILMCRAFT · СКАЧАТЬ И ОТКРЫТЬ",
            command=self.open_filmcraft,style="Studio.Primary.TButton")
        self.filmcraft_button.grid(row=0,column=0,sticky="ew",padx=4,pady=4)
        ttk.Button(tools,text="Справка FFmpeg",
            command=self.study_editing,style="Studio.TButton").grid(
            row=0,column=1,sticky="ew",padx=4,pady=4)
        self.multitrack_button=ttk.Button(
            tools,text="МНОГОДОРОЖЕЧНЫЙ МОНТАЖ",
            command=self.open_multitrack,style="Studio.Primary.TButton")
        self.multitrack_button.grid(row=1,column=0,sticky="ew",padx=4,pady=4)
        ttk.Button(tools,text="Подготовить публикацию",
                   command=self.open_publish_preparation,
                   style="Studio.TButton").grid(
            row=1,column=1,sticky="ew",padx=4,pady=4)
        # Results should stay readable while tool options scroll separately.
        resultbar=tk.Frame(self,bg=BG)
        resultbar.pack(fill="x",padx=17,pady=(5,5))
        tk.Label(resultbar,text="РЕЗУЛЬТАТ И СЦЕНАРИЙ",bg=BG,fg=CYAN,
                 font=("Segoe UI",11,"bold")).pack(side="left")
        ttk.Button(resultbar,text="Сохранить текст",command=self.save_result,
                   style="Studio.TButton").pack(side="right",padx=(6,0))
        ttk.Button(resultbar,text="Копировать",command=self.copy_result,
                   style="Studio.TButton").pack(side="right")
        output=tk.Frame(self,bg=ALT,highlightbackground=EDGE,highlightthickness=1)
        output.pack(fill="both",expand=True,padx=16,pady=(0,7))
        self.viewer=tk.Text(output,wrap="word",font=("Segoe UI",10),
            bg=ALT,fg=TEXT,insertbackground=CYAN,selectbackground="#215D75",
            relief="flat",bd=0,padx=14,pady=12,spacing1=3,spacing3=5)
        self.viewer.pack(side="left",fill="both",expand=True)
        bar=ttk.Scrollbar(output,orient="vertical",command=self.viewer.yview,
                           style="Studio.Vertical.TScrollbar")
        bar.pack(side="right",fill="y")
        self.viewer.configure(yscrollcommand=bar.set)
        self.viewer.insert("end","Напиши тему и нажми «СОЗДАТЬ СЦЕНАРИЙ».\n"
                           "⚡ Быстрый режим создаёт сценарий без ожидания модели.\n"
                           "AI-режимы доступны для более подробной версии.\n\n"
                           "После съёмки положи кадры 01.mp4, 02.mp4... в одну папку.\n"
                           "JARVIS не публикует видео без твоего решения.")
        self.viewer.configure(state="disabled")
        footer=tk.Frame(self,bg=BG)
        footer.pack(fill="x",padx=17,pady=(0,8))
        self.status_label=tk.Label(footer,textvariable=self.status,bg=BG,
                                   fg=MUTED,font=("Segoe UI",9),
                                   anchor="w",justify="left")
        self.status_label.pack(fill="x")
        self.focus_set()
        self.after(100,self._pump_notifications)

    def copy_result(self):
        content=self.viewer.get("1.0","end-1c").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.status.set("Текст результата скопирован.")

    def save_result(self):
        content=self.viewer.get("1.0","end-1c").strip()
        if not content:
            self.status.set("Нет результата для сохранения.")
            return
        filename=filedialog.asksaveasfilename(parent=self,
            title="Сохранить сценарий",defaultextension=".txt",
            filetypes=[("Текст","*.txt"),("Markdown","*.md")])
        if not filename:
            return
        try:
            # Do not overwrite files that may contain personal notes.
            with Path(filename).open("x",encoding="utf-8") as output:
                output.write(content+"\n")
        except FileExistsError:
            messagebox.showwarning("Файл уже есть",
                "Файл не перезаписан. Выбери новое имя.",parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Сохранение",str(exc),parent=self)
            return
        self.status.set("Текст сохранён: "+str(filename))

    def open_filmcraft(self):
        """One click: auto-download verified FilmCraft if needed, then open."""
        if self.running:
            return
        video=getattr(self,'rendered_video',None)
        if video is not None and not Path(video).is_file():
            video=None
        metadata=(self.rendered_info if video is not None else None)
        from filmcraft_bridge import find_filmcraft, FilmCraftError
        try:
            installed=find_filmcraft(getattr(self,"filmcraft_exe",None))
        except FilmCraftError:
            installed=None
            if not messagebox.askyesno(
                "Разрешить установку FilmCraft?",
                "Редактор FilmCraft пока не найден. Скачать проверенный "
                "архив с официального GitHub и распаковать его в папку "
                "пользователя?\n\n"
                "Это сетевое действие. Личные видео не отправляются. "
                "Существующие проекты не перезаписываются.",
                parent=self):
                self.status.set("Загрузка FilmCraft отменена пользователем.")
                return
        self.status.set('Открываю FilmCraft…' if installed is not None
                        else 'Скачиваю проверенный FilmCraft после разрешения…')

        def worker():
            from filmcraft_bridge import open_in_filmcraft
            executable=installed
            if executable is None:
                from filmcraft_installer import install_filmcraft
                previous=[None]
                def progress(phase,completed,total):
                    percent=int(completed*100/max(1,total))
                    if phase=='download':
                        label=f'Скачиваю FilmCraft с официального GitHub: {percent}%'
                    elif phase=='unpack':
                        label=f'Распаковываю проверенную версию FilmCraft: {percent}%'
                    else:
                        label='FilmCraft установлен, открываю редактор…'
                    # Only queue a GUI refresh every 5%, not for every chunk.
                    step=(phase,percent//5)
                    if step!=previous[0]:
                        previous[0]=step
                        self._notify(lambda value=label: self.status.set(value))
                executable=install_filmcraft(
                    progress=progress,cancel=self.stop_event)
                self.filmcraft_exe=executable
            if self.stop_event.is_set():
                return
            result=open_in_filmcraft(executable,video,metadata=metadata)
            def done():
                self.status.set('FilmCraft открыт: '+result.mode)
                self._show(
                    result.detail+'\n\n'
                    +(('Редактируемый проект: '+str(result.project)+'\n')
                      if result.project else '')
                    +(('OTIO-шкала: '+str(result.timeline)+'\n')
                      if result.timeline else '')
                    +'Готовый MP4 остаётся на диске и не меняется.\n'
                    'После правок сохрани новый .fcproj и экспортируй видео в FilmCraft.')
            self._notify(done)
        self._spawn(worker)

    def open_multitrack(self):
        """Standalone offline compositor, separate from basic auto montage."""
        previous=getattr(self,"_multitrack_window",None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return previous
        from multitrack_ui import MultitrackWindow
        self._multitrack_window=MultitrackWindow(self)
        return self._multitrack_window

    def open_publish_preparation(self):
        """User prepares video details locally, then uploads it manually."""
        previous=getattr(self,"_publish_window",None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return previous
        from creator_publish_ui import PublishWindow
        video=self.rendered_video if self.rendered_video and self.rendered_video.is_file() else None
        self._publish_window=PublishWindow(self,video=video)
        return self._publish_window

    def open_creator_accounts(self):
        """Only open fixed official sites in the owner's regular browser."""
        old=getattr(self,"_creator_window",None)
        if old is not None and old.winfo_exists():
            old.lift()
            return old
        from creator_accounts_ui import CreatorAccountsWindow
        self._creator_window=CreatorAccountsWindow(self)
        return self._creator_window

    def quick_montage(self):
        """A complete offline edit of owned footage, without an AI dependency."""
        if self.running:
            return
        from popular_edits import STYLES, source_clips, PopularEditError
        labels={entry.label: entry for entry in STYLES}
        chosen=labels.get(self.edit_style.get())
        if chosen is None:
            messagebox.showerror("Стиль эдита","Выбери один из готовых стилей.",parent=self)
            return
        folder=filedialog.askdirectory(
            parent=self,title="Выбери папку со своими видеоклипами")
        if not folder:
            return
        try:
            selected=source_clips(Path(folder))
        except (PopularEditError,OSError) as exc:
            messagebox.showerror("Исходные видео",str(exc),parent=self)
            return
        output=filedialog.asksaveasfilename(
            parent=self,title="Новый MP4 (не в папке исходников)",
            defaultextension=".mp4",filetypes=[("MP4 video","*.mp4")],
            initialfile="JARVIS_EDIT_"+chosen.name+".mp4")
        if not output:
            return
        soundtrack=self.pro_music.get().strip()
        music_label=(Path(soundtrack).name[:90] if soundtrack else "нет")
        if not messagebox.askyesno(
            "Разрешить офлайн-монтаж",
            f"Стиль: {chosen.label} ({chosen.size[0]}×{chosen.size[1]})\n"
            f"Видео: {len(selected)}\nМузыка: {music_label}\n"
            f"Файл: {output}\n\n"
            "Монтировать только твои файлы? Оригиналы не меняются. "
            "Проверь права на видео и музыку перед публикацией. "
            "Автоматической публикации нет.",
            parent=self):
            return
        self.status.set("Монтаж "+chosen.label+" — локальный FFmpeg, без облака.")
        def work():
            from popular_edits import render_popular_edit
            result=render_popular_edit(
                Path(folder),Path(output),style=chosen.name,
                music_path=Path(soundtrack) if soundtrack else None,
                cancel=self.stop_event)
            def done():
                self.rendered_video=Path(result["output"])
                # The social edit uses a different, explicitly saved EDL
                # schema. FilmCraft can open its MP4, not fake native metadata.
                self.rendered_info=None
                self._show(
                    "ЭДИТ ГОТОВ!\n\n"
                    "Стиль: "+chosen.label+"\n"
                    "Видео: "+result["output"]+"\n"
                    "Формат: "+str(result["size"][0])+" × "+str(result["size"][1])+"\n"
                    "Длительность: "+str(round(result["duration"],2))+" сек.\n"
                    "Исходных клипов: "+str(len(result["segments"]))+"\n"
                    "Монтажный лист: "+str(Path(result["output"]).with_name(
                        Path(result["output"]).stem+"_EDL.json"))+"\n\n"
                    "Проверь звук, монтаж и права перед публикацией. "
                    "JARVIS ничего не отправлял в интернет.")
                self.status.set("Эдит готов, MP4 и монтажный лист сохранены.")
            self._notify(done)
        self._spawn(work)

    def _choose_music(self):
        folder=filedialog.askopenfilename(
            parent=self,title='Выбери собственную музыку',
            filetypes=[('Аудио','*.mp3 *.m4a *.wav *.flac *.ogg *.aac')])
        if folder:self.pro_music.set(folder)

    def _video_options(self):
        """Return None for classic editors and lightweight regression stubs."""
        selected=getattr(self,'pro_enabled',None)
        if selected is None or not selected.get():
            return None
        from pro_montage import ProOptions, validate_options
        music=self.pro_music.get().strip()
        return validate_options(ProOptions(
            transition=float(self.pro_transition.get()),
            color=self.pro_color.get(),
            animated_titles=True,
            music_path=Path(music) if music else None,
            beat_sync=True,
            semantic=self.pro_semantic.get()))

    def _semantic_describer(self, opts):
        """Only the bundled local Qwen; never send footage to FreeLLM/cloud."""
        if opts is None or not opts.semantic:
            return None
        parent=getattr(self,'parent',None)
        runtime=(getattr(parent,'runtime',None) or
                 getattr(getattr(parent,'trimodal',None),'runtime',None))
        if runtime is None:return None
        try:
            from vision_engine import LocalOllamaVision, VisionConfig
            vision=LocalOllamaVision(VisionConfig(endpoint=runtime.start()))
            vision.initialize()
            return vision.describe
        except Exception:
            # Retain honest pixel-based selection when local Vision unavailable.
            return None

    def focus_stage(self, stage: str):
        """Navigate without triggering filesystem dialogs, web requests or rendering."""
        descriptions={
            'audience':('1. Анализ аудитории: импортируй свою статистику CSV.',self.audience_button),
            'script':('2. Сценарий: введи тему и выбери быстрый или AI режим.',self.make_button),
            'shoot':('3. Съёмка: открой текстовый список кадров.',self.speak_button),
            'edit':('4. Монтаж: выбери отснятые кадры и подтверди обработку.',self.edit_button),
            'edits':('Эдиты: выбери стиль и папку собственных клипов.',self.quick_edit_button),
            'review':('5. Оценка: проверь готовый MP4 относительно данных аудитории.',self.review_button),
            'auto':('Автомонтаж: введи тему и разреши поиск свободных видеоматериалов.',self.auto_button),
        }
        message,button=descriptions.get(stage,descriptions['audience'])
        self.status.set(message)
        try:button.focus_set()
        except tk.TclError:pass

    def _show(self, text):
        if not self.winfo_exists():return
        self.viewer.configure(state='normal')
        self.viewer.delete('1.0','end')
        self.viewer.insert('end',text)
        self.viewer.configure(state='disabled')

    def _busy(self, value):
        self.running=value
        state='disabled' if value else 'normal'
        for widget in (self.make_button,self.edit_button,self.load_button,self.audience_button,
                       self.review_button,self.auto_button,
                       self.filmcraft_button,self.quick_edit_button,
                       self.multitrack_button):
            widget.configure(state=state)

    def _pump_notifications(self):
        if not self.winfo_exists():return
        try:
            while True:
                callback=self._notifications.get_nowait()
                if self.winfo_exists() and not getattr(self.parent,"_closing",False):
                    callback()
        except queue.Empty:
            pass
        self.after(100,self._pump_notifications)

    def _notify(self,func):
        # Tk objects are touched exclusively by the main UI thread.
        self._notifications.put(func)

    def _spawn(self, worker):
        if self.running:return
        self.stop_event.clear()
        self._busy(True)
        def task():
            try:
                worker()
            except Exception as exc:
                detail=f'{type(exc).__name__}: {str(exc)[:400]}'
                self._notify(lambda: self.status.set('Ошибка: '+detail))
            finally:
                self._notify(lambda:self._busy(False))
        threading.Thread(target=task,daemon=True,name='jarvis-viral-studio').start()

    def _speak(self, text):
        if self.speaker and not self.parent._closing:
            threading.Thread(target=self.speaker.say,args=(text[:500],),daemon=True).start()

    def import_audience(self):
        path=filedialog.askopenfilename(parent=self,title='Выбери экспорт статистики своего канала',
                                        filetypes=[('Экспорт CSV','*.csv')])
        if not path:return
        if not messagebox.askyesno('Доступ к аналитике',
            'Прочитать ВЫБРАННЫЙ CSV локально, определить любимые темы зрителей и формат? '
            'Пароли и видеозаписи не передаются. Отчёт остаётся на ПК.',parent=self):return
        self.status.set('Анализирую реальные просмотры, темы и удержание…')
        requested_topic=self.topic.get().strip()
        def work():
            videos=read_channel_csv(Path(path))
            profile=analyze_audience(videos,source='CSV из папки пользователя')
            try: topic=requested_topic or recommend_topic(profile)
            except ValueError:topic='Тема будет выбрана вручную'
            report=expert_report(profile,topic)
            def done():
                self.profile=profile
                if not self.topic.get().strip() and topic!='Тема будет выбрана вручную':
                    self.topic.set(topic)
                self._show(report)
                self.status.set('Аудитория изучена: '+str(profile.sample_size)+
                                ' роликов. Можно создавать сценарий.')
                self._speak('Я изучил показатели канала. Теперь предложу, что снимать для этой аудитории.')
            self._notify(done)
        self._spawn(work)

    def generate(self):
        from quick_video_brief import select_brief
        topic=self.topic.get().strip()
        if not topic:
            if self.profile is None:
                messagebox.showwarning("Нужна тема",
                    "Введи тему ролика или загрузи статистику CSV.",
                    parent=self)
                return
            try:
                topic=recommend_topic(self.profile)
            except ValueError:
                messagebox.showwarning("Тема",
                    "Не удалось выделить тему из CSV. Укажи её вручную.",
                    parent=self)
                return
        if not 2<=len(topic)<=100:
            messagebox.showwarning("Тема",
                "Тема должна содержать от 2 до 100 символов.",parent=self)
            return
        online=self.web_enabled.get()
        if online and not messagebox.askyesno("Разрешить поиск трендов?",
            "Получить публичные поисковые тренды по указанной стране? "
            "Личные файлы не передаются.",parent=self):
            return
        geo=self.country.get()
        mode=self.scenario_mode.get()
        runtime=getattr(self.parent,"runtime",None)
        self.status.set("⚡ Готовлю быстрый сценарий…" if mode=="fast"
                        else "Qwen готовит сценарий · можно отменить…")
        def work():
            trends=[]
            note=""
            if online:
                try:
                    trends=research_trends(geo=geo,consent=True)
                except Exception as exc:
                    note="Тренды недоступны ("+str(exc)[:100]+").\n"
            if self.stop_event.is_set():
                return
            brief,message=select_brief(
                topic,trends,mode=mode,audience=self.profile,runtime=runtime)
            if self.stop_event.is_set():
                return
            project=_home()/("video_"+datetime.now().strftime("%Y%m%d_%H%M%S")
                              +"_"+uuid4().hex[:6])
            save_brief(brief,project)
            if self.profile is not None:
                (project/"AUDIENCE_EXPERTS_RU.md").write_text(
                    expert_report(self.profile,topic),encoding="utf-8")
            text=(note+message+"\n\n"
                  +"Заголовок: "+brief.title+"\n"
                  +"Зацепка: "+brief.hook+"\n\n"
                  +"СЦЕНАРИЙ:\n"+brief.script+"\n\n"
                  +"ПЛАН СЪЁМКИ:\n")
            for i,shot in enumerate(brief.shots,1):
                text+=f"{i:02d}. [{shot.seconds:g} сек] {shot.film}\n"
                text+="    НА ЭКРАНЕ: "+shot.caption+"\n"
            text+="\nФинал: "+brief.call_to_action+"\n"
            text+="\nПроект: "+str(project)+"\n"
            text+="Режим: "+brief.generator+"\n"
            if trends:
                text+="\nТренды ПОИСКА:\n"+"\n".join(
                    item.title+" — "+item.traffic for item in trends)
            def done():
                self.brief=brief
                self.project=project
                self._show(text)
                self.status.set("Сценарий готов. Посмотри план съёмки или переходи к монтажу.")
            self._notify(done)
        self._spawn(work)

    def study_editing(self):
        if not messagebox.askyesno('Разрешить справку FFmpeg',
                'Загрузить только публичную официальную документацию с ffmpeg.org? '
                'Никакие команды с сайта не выполняются и модели не переобучаются.',
                parent=self):
            return
        self.status.set('Читаю официальную документацию FFmpeg…')
        def work():
            reference=retry_readonly('official_ffmpeg_docs',
                                     lambda:read_ffmpeg_guide(consent=True),
                                     cancel=self.stop_event)
            def done():
                self._show(reference)
                self.status.set('Справка получена. Это справочная информация, не изменение алгоритмов.')
            self._notify(done)
        self._spawn(work)

    def read_shots(self):
        """Show the complete shot plan: the app has NO speech hardware."""
        if not self.brief:
            messagebox.showinfo("План съёмки",
                "Сначала создай или открой сценарий.",parent=self)
            return
        lines=["ПЛАН СЪЁМКИ: "+self.brief.title,""]
        for index,shot in enumerate(self.brief.shots,1):
            lines.append(f"{index:02d}. {shot.seconds:g} сек — {shot.film}")
            lines.append("     Титр: "+shot.caption)
            lines.append("")
        lines.append("Финал: "+self.brief.call_to_action)
        self._show("\n".join(lines))
        self.status.set("План съёмки открыт. Все кадры показаны текстом.")

    def open_brief(self):
        path=filedialog.askopenfilename(parent=self,title='Открыть brief.json',filetypes=[('JSON сценарий','*.json')])
        if not path:return
        try:
            brief=load_brief(Path(path));self.brief=brief;self.project=Path(path).parent
            self._show((self.project/'WHAT_TO_FILM_RU.md').read_text('utf-8') if (self.project/'WHAT_TO_FILM_RU.md').exists() else brief.script)
            self.status.set('Сценарий открыт. Можно приступать к монтажу.')
        except Exception as exc:messagebox.showerror('Ошибка',str(exc),parent=self)

    def auto_montage(self):
        """One confirmed workflow: topic, offline AI brief, licensed sources, FFmpeg.

        No mandatory channel CSV or manual clip selection. Does not publish.
        Network permission is explicit and limited to the topic and selected
        Commons clip downloads. The AI only provides bounded script content.
        """
        topic=self.topic.get().strip()
        if not 2<=len(topic)<=100:
            messagebox.showwarning('Тема ролика',
                'Введи тему ролика (от 2 до 100 символов). Данные канала не обязательны.',
                parent=self)
            return
        if not messagebox.askyesno('Разрешить полный автомонтаж',
                f'Создать ролик по теме «{topic}»?\n\n'
                'JARVIS получит публичные видео Wikimedia Commons, '
                'подберёт фрагменты, выровняет громкость, добавит надписи, '
                'сохранит авторство и соберёт MP4 на компьютере. '
                'Будет отправлена только тема, без твоих файлов и голоса. '
                'Скачанные материалы не публикуются автоматически. '
                'Окончательный результат нужно проверить.',
                parent=self):
            return
        try:
            pro=ViralStudioWindow._video_options(self)
        except (ValueError,OSError) as exc:
            messagebox.showerror('Профессиональный монтаж',str(exc),parent=self)
            return
        from quick_video_brief import select_brief
        speed_selector=getattr(self,"scenario_mode",None)
        mode=speed_selector.get() if speed_selector is not None else "legacy"
        runtime=getattr(getattr(self,"parent",None),"runtime",None)
        self.status.set('Автомонтаж: создаю сценарий по теме…')
        def work():
            if mode=="legacy":
                # Preserve API for earlier automation and editor integrations.
                try:
                    brief=create_local_brief(topic,audience=self.profile)
                    note=""
                except Exception as exc:
                    brief=template_brief(topic)
                    note="Локальная модель недоступна; использован шаблон: "+str(exc)[:120]
            else:
                brief,note=select_brief(
                    topic,mode=mode,audience=self.profile,runtime=runtime)
            if self.stop_event.is_set():return
            project=_home()/('auto_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:6])
            save_brief(brief,project)
            candidates=retry_readonly('commons_search',
                                      lambda:search_free_video(topic,consent=True),
                                      cancel=self.stop_event)
            if len(candidates)<len(brief.shots):
                raise OnlineMediaError(
                    f'Недостаточно подходящих свободных исходников: {len(candidates)} из '
                    f'{len(brief.shots)}. Попробуй более конкретную тему. '
                    'Готовый сценарий сохранён: '+str(project))
            if self.stop_event.is_set():return
            source=project/'licensed_media'
            download_free_video(candidates[:len(brief.shots)],source,
                                consent=True,cancel=self.stop_event)
            if self.stop_event.is_set():return
            options=({'pro_options':pro,
                      'semantic_describe':ViralStudioWindow._semantic_describer(self,pro)}
                     if pro is not None else {})
            outcome=analyze_and_recut(
                brief,source,project,profile=self.profile,
                filename='JARVIS_NOVA_AUTO_VERTICAL.mp4',cancel=self.stop_event,
                **options)
            out=outcome.output
            result=outcome.rendered
            def done():
                self.brief=outcome.brief
                self.project=project
                self.rendered_video=out
                self.rendered_info=result
                self._show(
                    'Автомонтаж завершён.\n\n'
                    'Тема: '+topic+'\n'
                    'Видео: '+str(out)+'\n'
                    'Длительность: '+str(round(result['duration'],1))+' сек.\n'
                    'Техническая проверка: '+str(result.get('technical_quality',{}))+'\n'
                    'Проверено вариантов: '+str(len(outcome.attempts))+'\n'
                    'Отчёт о просмотрах и правках: '+str(outcome.report)+'\n'
                    'Монтажный лист: '+str(out.with_name(out.stem+'_EDL.json'))+'\n'
                    'Исходники и авторство: '+str(source/'CREDITS_RU.md')+'\n\n'
                    +note+'\n'
                    'Проверь сюжет, права, музыку, качество и соответствие теме перед публикацией.'
                )
                self.status.set('Автомонтаж и повторная оценка закончены. Публикации нет.')
                self._speak(outcome.speech)
            self._notify(done)
        self._spawn(work)

    def montage(self):
        if not self.brief or not self.project:
            messagebox.showinfo('Нет сценария','Сначала подготовь сценарий.',parent=self);return
        online=messagebox.askyesno('Источник видео',
            'Искать открытые видеоклипы на Wikimedia Commons?\n\n'
            'Будет передана только тема ролика. Сохраняются ссылки на '
            'источники и условия CC0, Public Domain или CC BY. '
            'Авторство и применимость лицензии проверь до публикации.\n\n'
            'Нет — выбрать собственные видео.',parent=self)
        folder=None
        if not online:
            folder=filedialog.askdirectory(parent=self,title='Выбери папку с клипами 01.mp4, 02.mp4 ...')
            if not folder:return
            if not messagebox.askyesno('Подтверждение монтажа',
                f'Смонтировать {len(self.brief.shots)} кадров из {folder}? '
                'Исходные файлы не изменятся.',parent=self):return
        try:
            pro=ViralStudioWindow._video_options(self)
        except (ValueError,OSError) as exc:
            messagebox.showerror('Профессиональный монтаж',str(exc),parent=self)
            return
        brief=self.brief
        project=self.project
        out=project/'JARVIS_NOVA_VERTICAL.mp4'
        self.status.set('Ищу открытые материалы…' if online else
                        'Монтирую локально: кадрирование, склейка, экранные тексты…')
        def work():
            source=Path(folder) if folder is not None else None
            credits=''
            if online:
                candidates=retry_readonly('commons_search',
                                          lambda:search_free_video(brief.topic,consent=True),
                                          cancel=self.stop_event)
                if len(candidates)<len(brief.shots):
                    raise OnlineMediaError(
                        f'По теме «{brief.topic}» найдено {len(candidates)} клипов, '
                        f'нужно {len(brief.shots)}. Уточни тему или выбери свою папку.')
                source=project/('online_clips_'+uuid4().hex[:8])
                download_free_video(candidates[:len(brief.shots)],source,
                                    consent=True,cancel=self.stop_event)
                credits=str(source/'CREDITS_RU.md')
            if self.stop_event.is_set():return
            options=({'pro_options':pro,
                      'semantic_describe':ViralStudioWindow._semantic_describer(self,pro)}
                     if pro is not None else {})
            outcome=analyze_and_recut(
                brief,source,project,profile=self.profile,
                filename='JARVIS_NOVA_VERTICAL.mp4',cancel=self.stop_event,
                **options)
            out=outcome.output
            data=outcome.rendered
            review=outcome.review
            report=outcome.report
            def done():
                self.rendered_video=out
                self.rendered_info=data
                self.brief=outcome.brief

                self.status.set('Ролик готов: '+str(out)+
                                (f' | оценка {review.index}/100 (НЕ вероятность вирусности)' if review else
                                 ' | структура проверена; исторические просмотры без CSV недоступны'))
                self._show('Готово!\n\nФайл: '+data['output']+'\n'
                           'Длительность: '+str(round(data['duration'],1))+' сек.\n'
                           'Соотношение: 9:16\n'
                           'Лицензии и авторство: '+credits+'\n'
                           'Монтажный лист: '+str(out.with_name(out.stem+'_EDL.json'))+'\n'
                           'Оценка и повторный монтаж: '+str(report)+'\n'
                           'Проверено вариантов: '+str(len(outcome.attempts))+'\n\n'
                           'Проверь результат перед публикацией. JARVIS ничего не публикует автоматически.')
                self._speak(outcome.speech)
            self._notify(done)
        self._spawn(work)

    def review(self):
        if not self.brief or not self.project:
            messagebox.showwarning('Нет данных','Сначала создай или открой сценарий и смонтируй ролик.',parent=self)
            return
        # Always show the independently saved post-montage audit, including
        # cases without CSV. Do not make up future views.
        last_report=self.project/'POST_MONTAGE_REVIEW_RU.md'
        if last_report.is_file():
            self._show(last_report.read_text('utf-8'))
            self.status.set('Проверка закончена: результаты прошлых видео НЕ прогноз будущих просмотров.')
            self._speak('Проверил монтаж и сохранил вывод. Исторические просмотры не гарантируют новые.')
            return
        if self.profile is None:
            messagebox.showinfo('Просмотры',
                'Добавь CSV статистики канала. Без неё будущие просмотры '
                'оценить нельзя. После следующего монтажа сохранится структурный отчёт.',
                parent=self)
            return
        out=self.rendered_video or self.project/'JARVIS_NOVA_VERTICAL.mp4'
        if not out.is_file():
            messagebox.showwarning('Нет ролика','Сначала смонтируй видео.',parent=self);return
        self.status.set('Проверяю готовый MP4 и соответствие аудитории…')
        def work():
            review=evaluate_final_cut(self.brief,self.profile,out)
            file=save_review(review,self.project)
            def done():
                self._show(file.read_text('utf-8'))
                self.status.set('Индекс соответствия: '+str(review.index)+'/100. Это НЕ вероятность популярности.')
                self._speak('Оценка закончена. Это индекс соответствия каналу, а не гарантия просмотров.')
            self._notify(done)
        self._spawn(work)

    def cancel(self):
        self.stop_event.set()
        self.status.set('Запрошена отмена операции.')

    def close(self):
        self.cancel()
        self.destroy()
