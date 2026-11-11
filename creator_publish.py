# -*- coding: utf-8 -*-
"""Safe, offline publication preparation for creator-owned video.

No network access, OAuth token storage, account automation, background
publishing or API upload. The video stays on disk. The user explicitly opens
one official creator portal and personally chooses the file and audience.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import webbrowser


class PublishingError(ValueError):
    pass


PORTALS = {
    "youtube": ("YouTube Studio", "https://studio.youtube.com/"),
    "tiktok": ("TikTok Studio", "https://www.tiktok.com/tiktokstudio"),
    "instagram": ("Instagram", "https://www.instagram.com/"),
}
MAX_FILE = 5_000_000_000
MAX_NOTE = 3000


@dataclass(frozen=True)
class PublishDraft:
    platform: str
    video: Path
    title: str
    description: str
    hashtags: str = ""


def is_publish_prep_request(text: str) -> bool:
    if not isinstance(text,str) or not 4 <= len(text) <= 400:
        return False
    value=" ".join(text.casefold().replace("ё","е").split())
    return any(phrase in value for phrase in (
        "подготовь публикацию", "подготовь видео к публикации",
        "загрузи видео на ютуб", "загрузи видео в тикток",
        "опубликуй ролик в инстаграм", "помоги опубликовать видео",
    ))


def clean_draft(draft: PublishDraft) -> PublishDraft:
    if not isinstance(draft, PublishDraft) or draft.platform not in PORTALS:
        raise PublishingError("Выбери YouTube, TikTok или Instagram.")
    raw = Path(draft.video).expanduser()
    if raw.is_symlink() or not raw.is_file() or raw.suffix.lower() != ".mp4":
        raise PublishingError("Для публикации нужен существующий MP4, а не ссылка.")
    if not 1024 <= raw.stat().st_size <= MAX_FILE:
        raise PublishingError("Видеофайл слишком большой или не готов.")
    if not isinstance(draft.title, str) or not 1 <= len(draft.title.strip()) <= 100:
        raise PublishingError("Заголовок: от 1 до 100 символов.")
    if not isinstance(draft.description, str) or len(draft.description) > MAX_NOTE:
        raise PublishingError("Описание слишком длинное.")
    if not isinstance(draft.hashtags, str) or len(draft.hashtags) > 240:
        raise PublishingError("Слишком много хештегов.")
    for item in (draft.title, draft.description, draft.hashtags):
        if "\x00" in item or "\r" in item:
            raise PublishingError("Недопустимые управляющие символы.")
    for tag in draft.hashtags.split():
        if not re.fullmatch(r"#[\w]{1,30}", tag, re.UNICODE):
            raise PublishingError("Хештеги: через пробел, каждый начинается с #.")
    return draft


def prepared_caption(draft: PublishDraft) -> str:
    clean_draft(draft)
    return "\n\n".join(filter(None,(
        draft.title.strip(),
        draft.description.strip(),
        draft.hashtags.strip(),
    )))


def prepare_publish_package(draft: PublishDraft, output_dir: Path,
                            *, confirmed: bool = False) -> Path:
    """Make an exclusive JSON draft: never copy/upload video or store secrets."""
    if confirmed is not True:
        raise PermissionError("Подготовка публикации требует подтверждения.")
    clean_draft(draft)
    destination = Path(output_dir).expanduser()
    if destination.is_symlink() or not destination.is_dir():
        raise PublishingError("Выбери существующую обычную папку для черновика.")
    source = Path(draft.video).expanduser().resolve()
    destination = destination.resolve()
    file = destination / (source.stem + "_" + draft.platform + "_UPLOAD_DRAFT.json")
    if file.is_symlink() or file.exists():
        raise PublishingError("Черновик уже существует; перезапись запрещена.")
    digest = hashlib.sha256()
    before = source.stat()
    with source.open("rb") as data:
        for block in iter(lambda: data.read(1024*1024), b""):
            digest.update(block)
    after = source.stat()
    if (before.st_size != after.st_size or
            before.st_mtime_ns != after.st_mtime_ns):
        raise PublishingError(
            "Видео изменилось во время проверки; подготовь черновик заново.")
    payload = {
        "schema": "jarvis_publish_draft_v1",
        "platform": draft.platform,
        "official_portal": PORTALS[draft.platform][1],
        "video_path": str(source),
        "video_sha256": digest.hexdigest(),
        "title": draft.title.strip(),
        "description": draft.description.strip(),
        "hashtags": draft.hashtags.strip(),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "uploaded": False,
        "published": False,
        "notice": "Не опубликовано. Проверь права и загрузи MP4 на официальном сайте вручную.",
    }
    with file.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return file


def open_upload_portal(platform: str, *, confirmed: bool = False, browser=None):
    if confirmed is not True:
        raise PermissionError("Открытие сайта требует явного согласия.")
    if platform not in PORTALS:
        raise PublishingError("Недопустимая площадка.")
    opener = browser or webbrowser.open_new_tab
    return bool(opener(PORTALS[platform][1]))
