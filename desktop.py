# -*- coding: utf-8 -*-
"""Windows desktop executor. Never runs a shell or writes screenshot files."""
from __future__ import annotations
from pathlib import Path
import base64, io, os, re, webbrowser, time
from agent_core import Step, request_json, validate_step
from self_improve import LearningStore, propose_installed_name, safe_name, canonicalize


class AppSuggestion(Exception):
    def __init__(self, spoken: str, installed: str):
        self.spoken, self.installed = spoken, installed
        super().__init__(f"Возможно, имелась в виду программа «{installed}»?")


class Desktop:
    def __init__(self, allow_control=lambda:False, allow_vision=lambda:False, learning=None):
        self.allow_control=allow_control
        self.allow_vision=allow_vision
        self._active_override=None
        self.learning=learning

    @staticmethod
    def shortcuts():
        roots=[Path(os.getenv("APPDATA",""))/"Microsoft/Windows/Start Menu/Programs",
               Path(os.getenv("PROGRAMDATA",""))/"Microsoft/Windows/Start Menu/Programs"]
        entries=[]
        for root in roots:
            if root.is_dir():
                for p in root.rglob("*.lnk"):
                    if len(p.parts)>25: continue
                    entries.append(p)
        return entries

    @staticmethod
    def builtin_programs():
        return {"notepad": "notepad.exe", "блокнот": "notepad.exe",
                "calculator": "calc.exe", "калькулятор": "calc.exe",
                "explorer": "explorer.exe", "проводник": "explorer.exe"}

    def installed_names(self):
        from agent_core import UNSAFE_APPS
        return sorted({p.stem for p in self.shortcuts()
                       if safe_name(p.stem) and canonicalize(p.stem) not in UNSAFE_APPS})

    def is_installed(self, name: str) -> bool:
        from agent_core import UNSAFE_APPS
        key=canonicalize(name)
        if not safe_name(name) or key in UNSAFE_APPS:
            return False
        if key in self.builtin_programs():
            return True
        return any(canonicalize(p.stem)==key for p in self.shortcuts())

    def open_app(self, name: str):
        from agent_core import UNSAFE_APPS
        key=canonicalize(name)
        if not safe_name(name) or key in UNSAFE_APPS:
            raise PermissionError("Запуск этой программы запрещён")
        spoken=name
        learned=self.learning.resolve(name) if self.learning else None
        if learned is not None:
            if not self.is_installed(learned):
                raise FileNotFoundError("Ранее выученная программа больше не установлена. Удали её соответствие в меню обучения.")
            name=learned
            key=canonicalize(name)
        builtin=self.builtin_programs()
        if key in builtin:
            os.startfile(builtin[key])
            return "Открываю "+name
        candidates=[p for p in self.shortcuts()
                    if canonicalize(p.stem)==key and safe_name(p.stem)
                    and canonicalize(p.stem) not in UNSAFE_APPS]
        if candidates:
            candidates.sort(key=lambda p:(len(p.parts),str(p)))
            # Exact verified name only. Do not execute a random fuzzy shortcut.
            os.startfile(str(candidates[0]))
            return "Запускаю "+candidates[0].stem
        guess=propose_installed_name(spoken,self.installed_names())
        if guess is not None:
            raise AppSuggestion(spoken,guess)
        raise FileNotFoundError(f"Программа «{spoken}» не найдена в меню Пуск.")

    def active_window(self):
        if self._active_override is not None:
            return self._active_override
        import pygetwindow as gw
        window=gw.getActiveWindow()
        if not window: raise RuntimeError("Активное окно не найдено")
        return window

    def run(self,s:Step):
        validate_step(s)
        if s.kind=="open_app": return self.open_app(s.value)
        if s.kind=="open_url":
            if not webbrowser.open(s.value): raise RuntimeError("Браузер не открыл ссылку")
            return "Открываю сайт"
        if s.kind=="window_status":
            try: return "Активное окно: "+self.active_window().title[:150]
            except Exception: return "Название активного окна недоступно"
        if s.kind=="screen_describe": return self.describe_screen()
        if not self.allow_control():
            raise PermissionError("Сначала разреши управление мышью и окнами в JARVIS")
        import pyautogui as pag
        pag.FAILSAFE=True
        pag.PAUSE=0.10
        if s.kind=="zoom_in": pag.hotkey("ctrl","+");return "Увеличиваю масштаб"
        if s.kind=="zoom_out": pag.hotkey("ctrl","-");return "Уменьшаю масштаб"
        if s.kind=="volume_up": pag.press("volumeup",presses=2,interval=0.08);return "Громче"
        if s.kind=="volume_down": pag.press("volumedown",presses=2,interval=0.08);return "Тише"
        if s.kind=="mute": pag.press("volumemute");return "Переключаю звук"
        if s.kind=="minimize": self.active_window().minimize();return "Окно свёрнуто"
        if s.kind=="maximize": self.active_window().maximize();return "Окно развёрнуто"
        if s.kind=="restore": self.active_window().restore();return "Окно восстановлено"
        if s.kind=="close_window": self.active_window().close();return "Закрываю окно"
        if s.kind=="move":
            width,height=pag.size()
            if s.x>=width or s.y>=height: raise ValueError("Координаты вне экрана")
            pag.moveTo(s.x,s.y,0.2);return "Курсор перемещён"
        if s.kind=="click":
            width,height=pag.size()
            if s.x>=width or s.y>=height: raise ValueError("Координаты вне экрана")
            pag.click(s.x,s.y);return "Нажал"
        if s.kind=="scroll": pag.scroll(s.amount);return "Прокручено"
        if s.kind=="hotkey":
            if "+" in s.value: pag.hotkey(*s.value.split("+"))
            else: pag.press(s.value)
            return "Клавиша нажата"
        if s.kind=="type":
            # Use clipboard paste to support Cyrillic. Clipboard is restored after use.
            import tkinter as tk
            old=""
            clipboard=tk.Tk()
            clipboard.withdraw()
            try:
                try:old=clipboard.clipboard_get()
                except Exception:pass
                clipboard.clipboard_clear()
                clipboard.clipboard_append(s.value)
                clipboard.update()
                pag.hotkey("ctrl","v")
                time.sleep(0.4)  # let target app consume clipboard before restoring
                return "Текст введён"
            finally:
                clipboard.clipboard_clear()
                if old:clipboard.clipboard_append(old)
                clipboard.update()
                clipboard.destroy()
        raise ValueError("Неподдерживаемое действие")

    def describe_screen(self):
        if not self.allow_vision():
            raise PermissionError("Разреши анализ экрана в JARVIS")
        from PIL import ImageGrab
        image=ImageGrab.grab()  # only in RAM, never save to disk
        image.thumbnail((1280,720))
        buffer=io.BytesIO()
        image.save(buffer,format="JPEG",quality=80)
        encoded=base64.b64encode(buffer.getvalue()).decode("ascii")
        # No cloud screen uploads. Only local Ollama is permitted.
        try:
            resp=request_json("http://127.0.0.1:11434/api/generate",
                {"model":os.getenv("JARVIS_VISION_MODEL","qwen3-vl:2b"),
                 "prompt":"Кратко опиши по-русски, что видно на скриншоте. Не выдумывай невидимых элементов.",
                 "images":[encoded],"stream":False},timeout=80)
            return resp.get("response","Не удалось получить описание.")
        except Exception:
            return ("Нейросетевое зрение недоступно. "
                    "Для описания пикселей нужна локальная Ollama-модель с поддержкой изображений.")
