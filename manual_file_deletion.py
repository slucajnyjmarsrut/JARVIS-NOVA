# -*- coding: utf-8 -*-
"""JARVIS file deletion policy: reveal-only. No delete API or shell.

A request to delete user files always means: let the user choose the item,
then open the Windows Explorer location. JARVIS never deletes the item.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

_NO_DELETE_MESSAGE = (
    "JARVIS не удаляет файлы, папки, модели или проекты. "
    "Выбери объект — я только открою его расположение в Проводнике "
    "Windows. Удалить его можешь только ты сам."
)

# Imperatives / explicit requests only. Questions, quotations and negations
# do not produce an action or open a file chooser.
_PRELUDE = (
    r"(?:(?:эй|слушай|окей|привет)[\s,.:;!?—–-]+)?"
    r"(?:(?:джарвис|жарвис|джервис|гарвис)[\s,.:;!?—–-]+)?"
    r"(?:(?:пожалуйста|мне|за меня)[\s,]+)?"
    r"(?:(?:хочу|нужно|надо|можешь|помоги|попробуй|давай|"
    r"я хочу|я бы хотел)[\s,]+)?"
)
_DELETE_WORDS = re.compile(
    "^" + _PRELUDE +
    r"(?:удали|удалить|удаляй|стереть|сотри|стирай|снести|"
    r"снеси|уничтожь|уничтожить|выкинь|выброси|"
    r"delete|remove|erase|rm|rmdir|del)\b",
    flags=re.I,
)
_CLEAN_WORDS = re.compile(
    "^" + _PRELUDE +
    r"(?:очисти|очистить|опустоши|опустошить)\s+"
    r"(?:мне\s+)?(?:папк\w*|директори\w*|каталог\w*|"
    r"диск\w*|корзин\w*|файл\w*|загрузк\w*|кэш\w*|"
    r"проект\w*|всё|все)\b",flags=re.I,
)
_TRASH_WORDS = re.compile(
    "^" + _PRELUDE + r"(?:отправь|отправить|перемести|перенеси)\s+"
    r"(?:файл\w*|папк\w*|все|всё|это)?\s*"
    r"(?:в\s+)?корзин\w*\b",flags=re.I,
)
_NO_ACTION = re.compile(
    r"^(?:не|я не|никогда не|не надо|не нужно|"
    r"если|допустим|представь|как|почему|зачем|"
    r"объясни|расскажи|что будет|можно ли)\b",flags=re.I,
)


def is_delete_request(text: str) -> bool:
    """Detect actionable deletion requests before model/OS tool routing."""
    if not isinstance(text,str) or not 1<=len(text)<=1200:
        return False
    norm=re.sub(r"\s+"," ",text.casefold().replace("ё","е")).strip(" .,!?;:…")
    if _NO_ACTION.match(norm):
        return False
    # Negated direct requests must not trigger a selection dialog either.
    norm=re.sub(
        r"^(?:(?:эй|слушай|окей)[\s,]+)?"
        r"(?:джарвис|жарвис|джервис|гарвис)[\s,.:;!?—–-]+",
        "",norm,count=1,
    )
    if re.match(r"^(?:не|никогда не|не надо|не нужно)\b",norm):
        return False
    if re.match(r"^(?:пожалуйста\s+)?(?:не\s+)",norm):
        return False
    return bool(_DELETE_WORDS.match(norm) or _CLEAN_WORDS.match(norm)
                or _TRASH_WORDS.match(norm))


def is_folder_request(text: str) -> bool:
    if not isinstance(text,str):
        return False
    return bool(re.search(
        r"\b(?:папк\w*|директори\w*|каталог\w*|"
        r"диск\w*|корзин\w*|загрузк\w*|проект\w*)\b",
        text.casefold().replace("ё","е")))


def reveal_in_explorer(path, *, launcher=None, platform=None) -> Path:
    """Open Explorer with a selected *existing* item, never execute it.

    No shell, clipboard, file reads, writes, moves or deletes. The item is
    selected in Explorer if a file; a folder is opened directly.
    """
    if (os.name if platform is None else platform) != "nt":
        raise OSError("Открытие папки доступно только на Windows.")
    if not isinstance(path,(str,Path)) or not str(path).strip():
        raise ValueError("Сначала выбери файл или папку.")
    if len(str(path))>32760 or "\x00" in str(path):
        raise ValueError("Недопустимый путь.")
    target=Path(path).absolute()
    if not target.exists():
        raise FileNotFoundError("Файл или папка больше не существует.")
    if not target.is_file() and not target.is_dir():
        raise ValueError("Можно показать только обычный файл или папку.")
    explorer=str(Path(os.environ.get("SystemRoot",r"C:\Windows"))/"explorer.exe")
    cmd=([explorer,str(target)] if target.is_dir()
         else [explorer,"/select,",str(target)])
    (launcher or subprocess.Popen)(cmd,shell=False)
    return target


def choose_for_manual_deletion(parent=None, *, folder=False,
                               file_picker=None, directory_picker=None,
                               launcher=None, platform=None) -> Path | None:
    """Selection and location only; user must perform any deletion manually."""
    if file_picker is None or directory_picker is None:
        from tkinter import filedialog
        if file_picker is None:
            file_picker=filedialog.askopenfilename
        if directory_picker is None:
            directory_picker=filedialog.askdirectory
    if folder:
        chosen=directory_picker(parent=parent,title="Выбери папку для просмотра")
    else:
        chosen=file_picker(parent=parent,title="Выбери файл для просмотра")
    if not chosen:
        return None
    return reveal_in_explorer(chosen,launcher=launcher,platform=platform)


def user_explanation() -> str:
    return _NO_DELETE_MESSAGE
