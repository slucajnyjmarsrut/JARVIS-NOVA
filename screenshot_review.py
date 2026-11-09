# -*- coding: utf-8 -*-
"""Locally annotate a screenshot and send it to the user's offline Qwen Vision.

Images are never uploaded or sent to an external AI provider. Sending requests
analysis only; it cannot authorize code edits, GitHub pushes or upgrades.
The source screenshot is never modified.
"""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageOps, ImageTk, UnidentifiedImageError

MAX_FILE_BYTES = 20_000_000
MAX_PIXELS = 20_000_000
MAX_JPEG_BYTES = 4_000_000


def load_screenshot(filename: str | Path) -> Image.Image:
    """Open a bounded user-selected raster image, without modifying the file."""
    path = Path(filename)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Файл отсутствует или слишком большой (максимум 20 МБ).")
    try:
        with Image.open(path) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                raise ValueError("Выбери PNG, JPG, WEBP или BMP.")
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Слишком большое изображение.")
            picture = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Невозможно открыть изображение.") from exc
    picture.thumbnail((1850, 1850), Image.Resampling.LANCZOS)
    return picture


def annotate_jpeg(image: Image.Image, strokes: list[list[tuple[float, float]]]) -> bytes:
    """Draw red marks onto a copy; return a bounded JPEG for local Vision."""
    picture = image.convert("RGB").copy()
    pen = ImageDraw.Draw(picture)
    width = max(3, round(min(picture.size) / 170))
    for stroke in strokes:
        points = [(int(x), int(y)) for x, y in stroke]
        if len(points) == 1:
            x, y = points[0]
            pen.ellipse((x-width, y-width, x+width, y+width), fill="#FF3434")
        elif len(points) > 1:
            pen.line(points, fill="#FF3434", width=width, joint="curve")
    for quality in (91, 84, 75, 65):
        output = BytesIO()
        picture.save(output, "JPEG", quality=quality)
        result = output.getvalue()
        if len(result) <= MAX_JPEG_BYTES:
            return result
    raise ValueError("Скриншот слишком сложный. Уменьши изображение.")


def screenshot_folder() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".jarvisnova")
    return root / "JarvisNova" / "screenshot-reports"


def save_annotated(jpeg: bytes, folder: Path | None = None) -> Path:
    """Save the reviewed copy to user data, outside the EXE installation."""
    if not isinstance(jpeg, bytes) or not 32 <= len(jpeg) <= MAX_JPEG_BYTES:
        raise ValueError("Неправильный скриншот.")
    destination = Path(folder) if folder is not None else screenshot_folder()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ("marked-" + uuid4().hex + ".jpg")
    with path.open("xb") as stream:
        stream.write(jpeg)
    return path


class ScreenshotReview(tk.Toplevel):
    """Manual red pen. A visible Send button is required for analysis."""

    def __init__(self, parent):
        super().__init__(parent)
        from windows_titlebar import install_dark_titlebar
        self.parent = parent
        self.title("JARVIS NOVA — Скриншот и отметки")
        self.configure(bg="#081421")
        self.geometry(
            f"{min(890,max(430,self.winfo_screenwidth()-80))}x"
            f"{min(730,max(450,self.winfo_screenheight()-90))}")
        self.image = None
        self.preview = None
        self._photo = None
        self._strokes = []
        self._active = None
        self._saved = None
        install_dark_titlebar(self, background="#081421")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        fg, bg, button = "#EAF5FC", "#081421", "#17334C"
        tk.Label(self, text="СКРИНШОТ · ПОКАЖИ КРАСНЫМ, ЧТО ИСПРАВИТЬ",
                 bg=bg, fg="#43DFE5", font=("Segoe UI", 11, "bold")).pack(
                     anchor="w", padx=14, pady=(12, 6))
        tk.Label(self, text="Выбери файл, обведи проблемные места мышью и напиши задачу.",
                 bg=bg, fg=fg).pack(anchor="w", padx=14)
        row = tk.Frame(self, bg=bg)
        row.pack(fill="x", padx=12, pady=7)
        tk.Button(row, text="Выбрать скриншот", command=self.choose,
                  bg=button, fg=fg).pack(side="left", padx=3)
        tk.Button(row, text="Очистить отметки", command=self.clear_marks,
                  bg=button, fg=fg).pack(side="left", padx=3)
        tk.Button(row, text="Сохранить копию", command=self.save_copy,
                  bg=button, fg=fg).pack(side="left", padx=3)

        self.canvas = tk.Canvas(self, bg="#10253A",
                                highlightthickness=1, highlightbackground="#2D5269")
        self.canvas.pack(fill="both", expand=True, padx=12, pady=4)
        self.canvas.bind("<ButtonPress-1>", self._begin)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._end)
        tk.Label(self, text="Что JARVIS должен найти или исправить?",
                 bg=bg, fg=fg).pack(anchor="w", padx=14, pady=(7, 2))
        self.question = tk.Entry(self, bg="#10253A", fg=fg, insertbackground=fg,
                                  font=("Segoe UI", 10), relief="flat")
        self.question.insert(0, "Посмотри на красные отметки. Что здесь нужно исправить?")
        self.question.pack(fill="x", padx=14, ipady=7)
        self.status = tk.StringVar(value="Обработка изображения только локально. Изменения кода не выполняются.")
        tk.Label(self, textvariable=self.status, bg=bg, fg="#A9BFCE",
                 anchor="w", wraplength=760).pack(fill="x", padx=14, pady=6)
        tk.Button(self, text="ОТПРАВИТЬ JARVIS НА АНАЛИЗ", command=self.send,
                  bg="#147A85", fg="white", font=("Segoe UI", 10, "bold")).pack(
                      fill="x", padx=14, pady=(0, 12))
        self.after(100, self.choose)

    def choose(self):
        path = filedialog.askopenfilename(
            parent=self, title="Выбери скриншот",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        try:
            image = load_screenshot(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Скриншот", str(exc), parent=self)
            return
        self.image = image
        self.preview = image.copy()
        max_width = max(260, min(810, self.winfo_width()-50))
        max_height = max(180, min(440, self.winfo_height()-230))
        self.preview.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(self.preview, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self._strokes.clear()
        self._saved = None
        self.status.set("Выбран скриншот. Красные отметки можно рисовать мышью.")

    def _point(self, event):
        if self.preview is None:
            return None
        x = max(0, min(event.x, self.preview.width-1))
        y = max(0, min(event.y, self.preview.height-1))
        return (x * self.image.width / self.preview.width,
                y * self.image.height / self.preview.height)

    def _begin(self, event):
        point = self._point(event)
        if point is not None:
            self._active = [point]
            self._strokes.append(self._active)
            self._saved = None

    def _move(self, event):
        point = self._point(event)
        if point is None or self._active is None:
            return
        prev = self._active[-1]
        self._active.append(point)
        scale_x = self.preview.width / self.image.width
        scale_y = self.preview.height / self.image.height
        self.canvas.create_line(
            prev[0]*scale_x, prev[1]*scale_y,
            point[0]*scale_x, point[1]*scale_y,
            fill="#FF3434", width=3, capstyle="round", tags="mark")

    def _end(self, event):
        self._active = None

    def clear_marks(self):
        self._strokes.clear()
        self._active = None
        self._saved = None
        self.canvas.delete("mark")

    def save_copy(self):
        if self.image is None:
            self.status.set("Сначала выбери скриншот.")
            return None
        try:
            jpeg = annotate_jpeg(self.image, self._strokes)
            self._saved = save_annotated(jpeg)
        except (ValueError, OSError) as exc:
            self.status.set("Не удалось сохранить: " + str(exc))
            return None
        self.status.set("Размеченная копия сохранена: " + str(self._saved))
        return self._saved

    def send(self):
        if self.image is None:
            self.status.set("Сначала выбери скриншот.")
            return
        question = self.question.get().strip()
        if not 1 <= len(question) <= 900:
            self.status.set("Напиши задачу длиной от 1 до 900 символов.")
            return
        # A failed model call must never discard hand-drawn markings.
        if not self.parent.screenshot_ready():
            self.status.set("Qwen недоступна. Открой ⚙ → «Проверить локальную модель».")
            return
        try:
            jpeg = annotate_jpeg(self.image, self._strokes)
            if self._saved is None:
                self._saved = save_annotated(jpeg)
        except (ValueError, OSError) as exc:
            self.status.set("Не удалось подготовить скриншот: " + str(exc))
            return
        if self.parent.submit_screenshot(question, jpeg):
            self.parent.log("Система", "Размеченная копия сохранена локально: " + str(self._saved))
            self.destroy()
        else:
            self.status.set("JARVIS занят. Попробуй отправить снова.")
