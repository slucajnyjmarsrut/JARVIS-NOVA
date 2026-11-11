# -*- coding: utf-8 -*-
"""Manual upload assistant. No account credentials or automatic publication."""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from creator_publish import (
    PORTALS, PublishDraft, PublishingError, clean_draft,
    prepare_publish_package, prepared_caption, open_upload_portal,
)


class PublishWindow(tk.Toplevel):
    def __init__(self, parent, video=None):
        super().__init__(parent)
        from studio_theme import apply_video_theme, BG
        from windows_titlebar import install_dark_titlebar
        self.title("JARVIS NOVA — Подготовка публикации")
        self.geometry(f"{min(820,self.winfo_screenwidth()-70)}x"
                      f"{min(650,self.winfo_screenheight()-70)}")
        self.minsize(525,460)
        self.configure(bg=BG)
        apply_video_theme(self)
        install_dark_titlebar(self,background=BG)
        self._busy=False
        self._messages=queue.Queue()
        self.platform=tk.StringVar(value="youtube")
        self.video=tk.StringVar(value=str(video) if video else "")
        self.title_text=tk.StringVar()
        self.tags=tk.StringVar()
        self.output_dir=tk.StringVar()

        root=ttk.Frame(self,padding=15,style="Studio.TFrame")
        root.pack(fill="both",expand=True)
        ttk.Label(root,text="ПОДГОТОВИТЬ ВИДЕО К ПУБЛИКАЦИИ",
                  style="Studio.Heading.TLabel").pack(anchor="w")
        ttk.Label(root,style="Studio.Small.TLabel",wraplength=740,
                  text="Черновик и открытие официального сайта. "
                       "JARVIS не загружает и не публикует ролики, "
                       "не получает пароли и не читает аккаунты.").pack(
                           anchor="w",pady=(4,12))
        ttk.Label(root,text="Площадка",style="Studio.TLabel").pack(anchor="w")
        ttk.Combobox(root,textvariable=self.platform,
                     values=list(PORTALS),state="readonly",
                     style="Studio.TCombobox").pack(fill="x",pady=(2,10))
        self._picker(root,"Готовый MP4",self.video,"video")
        self._picker(root,"Куда сохранить черновик",self.output_dir,"folder")
        ttk.Label(root,text="Название (до 100 символов)",
                  style="Studio.TLabel").pack(anchor="w")
        ttk.Entry(root,textvariable=self.title_text,
                  style="Studio.TEntry").pack(fill="x",pady=(2,10))
        ttk.Label(root,text="Описание",style="Studio.TLabel").pack(anchor="w")
        self.description=tk.Text(
            root,height=5,wrap="word",bg="#0B1D30",fg="#EAF5FC",
            insertbackground="#43DFE5",relief="flat")
        self.description.pack(fill="both",expand=True,pady=(2,10))
        ttk.Label(root,text="Хештеги (#edit #nova)",
                  style="Studio.TLabel").pack(anchor="w")
        ttk.Entry(root,textvariable=self.tags,
                  style="Studio.TEntry").pack(fill="x",pady=(2,10))
        actions=ttk.Frame(root,style="Studio.TFrame")
        actions.pack(fill="x",pady=(3,8))
        self.save_button=ttk.Button(
            actions,text="СОЗДАТЬ ЧЕРНОВИК",command=self.save,
            style="Studio.Primary.TButton")
        self.save_button.pack(side="left")
        ttk.Button(actions,text="Скопировать подпись",
                   command=self.copy_caption,
                   style="Studio.TButton").pack(side="left",padx=(8,0))
        ttk.Button(actions,text="Открыть кабинет",
                   command=self.open_portal,
                   style="Studio.TButton").pack(side="left",padx=(8,0))
        self.status=tk.StringVar(
            value="После создания черновика вручную выбери MP4 на официальном сайте.")
        ttk.Label(root,textvariable=self.status,wraplength=740,
                  style="Studio.Small.TLabel").pack(anchor="w")
        self.after(130,self._pump)

    def _picker(self,parent,label,var,kind):
        ttk.Label(parent,text=label,style="Studio.TLabel").pack(anchor="w")
        row=ttk.Frame(parent,style="Studio.TFrame")
        row.pack(fill="x",pady=(2,10))
        ttk.Entry(row,textvariable=var,
                  style="Studio.TEntry").pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="Выбрать",command=lambda:self._browse(var,kind),
                   style="Studio.TButton").pack(side="left",padx=(8,0))

    def _browse(self,var,kind):
        if kind=="folder":
            selected=filedialog.askdirectory(
                parent=self,title="Папка черновика публикации")
        else:
            selected=filedialog.askopenfilename(
                parent=self,title="Готовый MP4",filetypes=[("MP4","*.mp4")])
        if selected:
            var.set(selected)

    def _draft(self):
        return clean_draft(PublishDraft(
            platform=self.platform.get(),
            video=Path(self.video.get()),
            title=self.title_text.get(),
            description=self.description.get("1.0","end-1c"),
            hashtags=self.tags.get(),
        ))

    def copy_caption(self):
        try:
            text=prepared_caption(self._draft())
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status.set("Подпись скопирована; JARVIS не отправлял её в интернет.")
        except (PublishingError,OSError) as exc:
            messagebox.showerror("Подпись",str(exc),parent=self)

    def open_portal(self):
        platform=self.platform.get()
        if platform not in PORTALS:
            return
        name,url=PORTALS[platform]
        if not messagebox.askyesno(
            "Открыть официальный сайт?",
            f"Открыть {name}?\n{url}\n\n"
            "Выбери файл MP4 и нажми публикацию самостоятельно.",
            parent=self):
            return
        try:
            if not open_upload_portal(platform,confirmed=True):
                raise PublishingError("Не удалось открыть браузер.")
            self.status.set("Кабинет открыт. Видео ещё не загружено и не опубликовано.")
        except (PublishingError,OSError) as exc:
            messagebox.showerror("Кабинет",str(exc),parent=self)

    def save(self):
        if self._busy:
            return
        try:
            draft=self._draft()
            destination=Path(self.output_dir.get())
            if not destination.is_dir() or destination.is_symlink():
                raise PublishingError("Выбери папку для черновика.")
        except (PublishingError,OSError) as exc:
            messagebox.showerror("Черновик",str(exc),parent=self)
            return
        if not messagebox.askyesno(
            "Подготовить локальный черновик?",
            f"Площадка: {PORTALS[draft.platform][0]}\n"
            f"Видеофайл: {draft.video}\n"
            f"Папка: {destination}\n\n"
            "Создать новый JSON с подписью и контрольной суммой? "
            "JARVIS ничего не публикует и не отправляет аккаунту.",
            parent=self):
            return
        self._busy=True
        self.save_button.configure(state="disabled")
        self.status.set("Проверяю SHA-256 локального видео, интернет не используется.")
        def work():
            try:
                path=prepare_publish_package(
                    draft,destination,confirmed=True)
                self._messages.put(("done",str(path)))
            except Exception as exc:
                self._messages.put(("error",str(exc)[:280]))
        threading.Thread(target=work,daemon=True,
                         name="jarvis-publish-draft").start()

    def _pump(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind,data=self._messages.get_nowait()
                self._busy=False
                self.save_button.configure(state="normal")
                if kind=="done":
                    self.status.set("Черновик сохранён: "+data+
                                    " · публикации НЕ было.")
                else:
                    self.status.set("Черновик не создан: "+data)
                    messagebox.showerror("Подготовка публикации",data,parent=self)
        except queue.Empty:
            pass
        self.after(130,self._pump)
