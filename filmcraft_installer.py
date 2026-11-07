# -*- coding: utf-8 -*-
"""One-click, per-user installation of the official FilmCraft portable build.

No administrator privileges or third-party Python dependencies required.
Download is triggered only by the user's explicit "Open FilmCraft" action.
Version, release URL, size and SHA256 are pinned and verified before extracting.
Installation never overwrites user projects or existing application folders.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from dataclasses import dataclass

FILMCRAFT_VERSION = "v0.18.0"
FILMCRAFT_ARCHIVE = "filmcraft-0.18.0-windows-x64-portable.zip"
FILMCRAFT_URL = (
    "https://github.com/storytold/filmcraft/releases/download/"
    + FILMCRAFT_VERSION + "/" + FILMCRAFT_ARCHIVE
)
FILMCRAFT_SHA256 = "82847cf49087e95fd3f72dde80955d1c63af2821ad677e34e3de7a0e873e95bf"
FILMCRAFT_ARCHIVE_BYTES = 109616261

MAX_ARCHIVE_BYTES = 160_000_000
MAX_FILES = 3000
MAX_UNCOMPRESSED_BYTES = 1_000_000_000
ALLOWED_REDIRECT_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com"
})
_DOWNLOAD_BUFFER = 1024 * 1024


class FilmCraftInstallError(RuntimeError):
    """Safe text to show in JARVIS status bar; never contains secret tokens."""


class _RestrictedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme != "https" or
                parsed.hostname not in ALLOWED_REDIRECT_HOSTS or
                parsed.username or parsed.password or
                parsed.port not in (None, 443) or self.count >= 6):
            raise FilmCraftInstallError(
                "FilmCraft: GitHub перенаправил загрузку на непроверенный адрес.")
        self.count += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_install_root():
    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "JARVIS-NOVA" / "FilmCraft"


def installed_executable(root=None):
    root = Path(root) if root is not None else default_install_root()
    folder = root / FILMCRAFT_VERSION
    marker = folder / ".jarvis_filmcraft_sha256"
    try:
        if not folder.is_dir() or folder.is_symlink():
            return None
        if marker.is_symlink() or marker.read_text(encoding="ascii").strip() != FILMCRAFT_SHA256:
            return None
        matches = [p for p in folder.rglob("filmcraft.exe")
                   if p.is_file() and not p.is_symlink()]
        if len(matches) != 1 or matches[0].resolve().is_relative_to(folder.resolve()) is False:
            return None
        cli = matches[0].with_name("filmcraft-cli.exe")
        if not cli.is_file() or cli.is_symlink():
            return None
        return matches[0].resolve()
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return None


def _check_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise FilmCraftInstallError("Скачивание FilmCraft отменено.")


def _notify(progress, phase, completed, total):
    if progress is not None:
        progress(phase, completed, total)


def _download(archive, *, progress=None, cancel=None, opener=None):
    """Download only the pinned release and fail closed on bad size/hash."""
    redirects = _RestrictedRedirects()
    transport = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler(), redirects)
    request = urllib.request.Request(
        FILMCRAFT_URL, headers={"User-Agent": "JARVIS-NOVA-FilmCraft",
                               "Accept": "application/octet-stream"},
        method="GET")
    try:
        response = transport.open(request, timeout=60)
        with response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in ALLOWED_REDIRECT_HOSTS:
                raise FilmCraftInstallError("FilmCraft: адрес загрузки не прошёл проверку.")
            stated = response.headers.get("Content-Length")
            if stated is not None:
                try:
                    if not 0 < int(stated) <= MAX_ARCHIVE_BYTES:
                        raise FilmCraftInstallError("FilmCraft: архив слишком большой.")
                except ValueError:
                    raise FilmCraftInstallError("FilmCraft: неверный размер архива.") from None
            count = 0
            digest = hashlib.sha256()
            with Path(archive).open("xb") as output:
                while True:
                    _check_cancelled(cancel)
                    block = response.read(_DOWNLOAD_BUFFER)
                    if not block:
                        break
                    count += len(block)
                    if count > MAX_ARCHIVE_BYTES or count > FILMCRAFT_ARCHIVE_BYTES:
                        raise FilmCraftInstallError("FilmCraft: неверный размер загрузки.")
                    output.write(block)
                    digest.update(block)
                    _notify(progress, "download", count, FILMCRAFT_ARCHIVE_BYTES)
            if count != FILMCRAFT_ARCHIVE_BYTES or digest.hexdigest().lower() != FILMCRAFT_SHA256:
                raise FilmCraftInstallError("Проверка SHA-256 FilmCraft не прошла; файл не установлен.")
    except FilmCraftInstallError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        raise FilmCraftInstallError(
            "Не удалось скачать FilmCraft с GitHub. Проверь интернет и повтори.") from None


_RESERVED = frozenset({"con","prn","aux","nul"} |
                      {"com"+str(i) for i in range(1,10)} |
                      {"lpt"+str(i) for i in range(1,10)})


def _safe_zip_member(member):
    raw = member.filename
    if (not raw or len(raw) > 600 or "\\" in raw or
            raw.startswith("/") or "\0" in raw):
        raise FilmCraftInstallError("Небезопасный путь внутри архива FilmCraft.")
    pure = PurePosixPath(raw)
    parts = pure.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise FilmCraftInstallError("В архиве FilmCraft обнаружен выход из папки.")
    for part in parts:
        if (part.endswith((" ", ".")) or ":" in part or len(part) > 200 or
                part.split(".", 1)[0].casefold() in _RESERVED):
            raise FilmCraftInstallError("В архиве FilmCraft обнаружен неверный путь.")
    mode = (member.external_attr >> 16) & 0o170000
    if mode not in (0, stat.S_IFDIR, stat.S_IFREG):
        raise FilmCraftInstallError("Символические ссылки в FilmCraft запрещены.")
    if member.file_size < 0 or member.file_size > MAX_UNCOMPRESSED_BYTES:
        raise FilmCraftInstallError("В архиве FilmCraft обнаружен слишком большой файл.")
    return parts


def _unpack(archive, destination, *, progress=None, cancel=None):
    try:
        with zipfile.ZipFile(archive, "r") as zipped:
            members = zipped.infolist()
            if not members or len(members) > MAX_FILES:
                raise FilmCraftInstallError("Неверное количество файлов FilmCraft.")
            names = set()
            total = 0
            for item in members:
                parts = _safe_zip_member(item)
                normalized = "/".join(parts).casefold()
                if normalized in names:
                    raise FilmCraftInstallError("Повторяющиеся пути в архиве FilmCraft.")
                names.add(normalized)
                total += item.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise FilmCraftInstallError("FilmCraft: распаковка превышает 1 ГБ.")
            copied = 0
            for item in members:
                _check_cancelled(cancel)
                path = Path(destination).joinpath(*_safe_zip_member(item))
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(item) as reader, path.open("xb") as writer:
                    while True:
                        _check_cancelled(cancel)
                        block = reader.read(_DOWNLOAD_BUFFER)
                        if not block:
                            break
                        writer.write(block)
                        copied += len(block)
                        if copied > total:
                            raise FilmCraftInstallError("FilmCraft: повреждённый ZIP.")
                        _notify(progress, "unpack", copied, max(1, total))
            matches = [x for x in Path(destination).rglob("filmcraft.exe")
                       if x.is_file() and not x.is_symlink()]
            if len(matches) != 1 or not matches[0].with_name("filmcraft-cli.exe").is_file():
                raise FilmCraftInstallError(
                    "В официальном ZIP FilmCraft не найдены редактор и CLI.")
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError):
        raise FilmCraftInstallError("Архив FilmCraft повреждён или не распаковывается.") from None


def install_filmcraft(*, root=None, progress=None, cancel=None, opener=None):
    """Download verified release to LOCALAPPDATA and return runnable EXE.

    Called from a JARVIS background worker after user clicks the FilmCraft
    button. Never overwrite existing version folder or any user projects.
    """
    root = Path(root) if root is not None else default_install_root()
    current = installed_executable(root)
    if current:
        _notify(progress, "ready", 1, 1)
        return current
    if sys_platform_windows() is False and root == default_install_root():
        raise FilmCraftInstallError("Автозагрузка FilmCraft доступна в JARVIS для Windows.")
    root.mkdir(parents=True, exist_ok=True)
    final = root / FILMCRAFT_VERSION
    if final.exists():
        raise FilmCraftInstallError(
            "Папка FilmCraft уже существует, но установка повреждена. "
            "Проверь её вручную, чтобы не потерять свои файлы.")
    _check_cancelled(cancel)
    stage = Path(tempfile.mkdtemp(prefix=".filmcraft-install-", dir=str(root)))
    try:
        archive = stage / FILMCRAFT_ARCHIVE
        _download(archive, progress=progress, cancel=cancel, opener=opener)
        extracted = stage / "app"
        extracted.mkdir()
        _unpack(archive, extracted, progress=progress, cancel=cancel)
        (extracted / ".jarvis_filmcraft_sha256").write_text(
            FILMCRAFT_SHA256 + "\n", encoding="ascii")
        _check_cancelled(cancel)
        if final.exists():
            current = installed_executable(root)
            if current:
                _notify(progress, "ready", 1, 1)
                return current
            raise FilmCraftInstallError("FilmCraft уже изменён другим процессом.")
        extracted.rename(final)
        result = installed_executable(root)
        if result is None:
            raise FilmCraftInstallError("Не удалось проверить установленный FilmCraft.")
        _notify(progress, "ready", 1, 1)
        return result
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def sys_platform_windows():
    import sys
    return sys.platform == "win32"
