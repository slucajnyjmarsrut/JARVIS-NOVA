# -*- coding: utf-8 -*-
"""Opt-in Wikimedia Commons footage for local Viral Studio.

Only public Commons API metadata and allowlisted upload.wikimedia.org videos.
No user footage is uploaded; no arbitrary URLs, scripts, shell or redirects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit, quote
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
MAX_METADATA = 900_000
MAX_CLIP = 55_000_000
MIMES = {"video/webm": ".webm", "video/mp4": ".mp4", "video/ogg": ".ogv"}


class OnlineMediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class FreeClip:
    title: str
    url: str
    page: str
    license: str
    size: int
    mime: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise OnlineMediaError("Источник перенаправил запрос; загрузка отменена")


def _fetch(url: str, size_limit: int) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-NOVA/0.5 (Commons research)"})
    with opener.open(req, timeout=18) as response:
        data = response.read(size_limit + 1)
    if len(data) > size_limit:
        raise OnlineMediaError("Ответ источника превышает допустимый размер")
    return data


def _approved_video(url: str, mime: str) -> bool:
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return (u.scheme == "https" and u.hostname == "upload.wikimedia.org"
            and not (u.username or u.password or u.port or u.query or u.fragment)
            and u.path.startswith("/wikipedia/commons/")
            and u.path.lower().endswith(MIMES.get(mime, "INVALID")))


def _licence(text: str) -> str | None:
    clean = " ".join(str(text).casefold().replace("-", " ").split())
    if clean in {"cc0", "cc0 1.0", "public domain", "pd", "public domain mark 1.0"}:
        return "Public domain / CC0"
    if clean in {"cc by 4.0", "cc by 3.0", "cc by 2.0"}:
        return clean.upper()
    return None


def search_free_video(topic: str, *, consent=False, transport=None, limit=40) -> list[FreeClip]:
    """Search filename/description metadata; not a promise that clips exist."""
    if not consent:
        raise PermissionError("Сначала разреши поиск видеоматериалов в интернете")
    if not isinstance(topic, str) or not (2 <= len(topic.strip()) <= 100):
        raise ValueError("Укажи тему видео от 2 до 100 символов")
    if any(ord(c) < 32 for c in topic):
        raise ValueError("Недопустимые символы темы")
    if not 1 <= limit <= 50:
        raise ValueError("Максимум 50 результатов")
    params = urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": topic.strip(), "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
    })
    raw = (transport or _fetch)(API + "?" + params, MAX_METADATA)
    if not isinstance(raw, bytes) or len(raw) > MAX_METADATA:
        raise OnlineMediaError("Недопустимый ответ каталога")
    try:
        obj = json.loads(raw)
        pages = obj.get("query", {}).get("pages", {})
    except (ValueError, AttributeError, TypeError) as exc:
        raise OnlineMediaError("Каталог вернул некорректные данные") from exc
    if not isinstance(pages, dict):
        raise OnlineMediaError("Некорректный список файлов")
    found = []
    for page in pages.values():
        if not isinstance(page, dict) or not str(page.get("title", "")).startswith("File:"):
            continue
        items = page.get("imageinfo") or ()
        info = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        mime = str(info.get("mime", ""))
        url = str(info.get("url", ""))
        meta = info.get("extmetadata") or {}
        if mime not in MIMES or not _approved_video(url, mime) or not isinstance(meta, dict):
            continue
        licence = _licence((meta.get("LicenseShortName") or {}).get("value", ""))
        try:
            size = int(info.get("size", 0))
        except (ValueError, TypeError):
            continue
        if not licence or not 1024 <= size <= MAX_CLIP:
            continue
        title = str(page["title"])[:220]
        source = "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe=":")
        found.append(FreeClip(title, url, source, licence, size, mime))
    return found


def download_free_video(clips: list[FreeClip], folder: Path, *, consent=False,
                        transport=None, cancel=None) -> Path:
    """Download clips without overwriting files; store attribution manifest."""
    if not consent:
        raise PermissionError("Загрузка видео из интернета требует согласия")
    if not 1 <= len(clips) <= 10:
        raise OnlineMediaError("Нужно от 1 до 10 проверенных видео")
    folder = Path(folder)
    if folder.exists():
        raise OnlineMediaError("Папка загрузки уже существует; файлы не заменяются")
    folder.mkdir(parents=True, exist_ok=False)
    manifest = []
    for i, clip in enumerate(clips, 1):
        if cancel is not None and cancel.is_set():
            raise OnlineMediaError("Загрузка отменена")
        if not isinstance(clip, FreeClip) or clip.mime not in MIMES or not _approved_video(clip.url, clip.mime):
            raise OnlineMediaError("Недоверенный адрес видео")
        if not 1024 <= clip.size <= MAX_CLIP or not _licence(clip.license):
            # Normalized CC0/PD output also accepted, CC BY validated below.
            if clip.license != "Public domain / CC0" or not 1024 <= clip.size <= MAX_CLIP:
                raise OnlineMediaError("Лицензия или размер клипа не подтверждены")
        payload = (transport or _fetch)(clip.url, min(MAX_CLIP, clip.size + 2048))
        if not isinstance(payload, bytes) or len(payload) > MAX_CLIP or not payload:
            raise OnlineMediaError("Некорректные данные видео")
        if clip.mime == "video/webm" and not payload.startswith(b"\\x1a\\x45\\xdf\\xa3"):
            raise OnlineMediaError("Неверный заголовок WebM")
        if clip.mime == "video/mp4" and payload[4:8] != b"ftyp":
            raise OnlineMediaError("Неверный заголовок MP4")
        if clip.mime == "video/ogg" and not payload.startswith(b"OggS"):
            raise OnlineMediaError("Неверный заголовок Ogg")
        name = f"{i:02d}" + MIMES[clip.mime]
        path = folder / name
        with path.open("xb") as file:
            file.write(payload)
        manifest.append({**asdict(clip), "local_file": name})
    (folder / "SOURCES_AND_LICENSES.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    notes = ["# Источники материалов для монтажа", "",
             "Проверь страницы авторов и условия лицензий перед публикацией.",
             "CC BY требует указания автора, лицензии и внесённых изменений.", ""]
    for entry in manifest:
        notes.append(f"- {entry['local_file']}: {entry['title']} — {entry['license']} — {entry['page']}")
    (folder / "CREDITS_RU.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    return folder
