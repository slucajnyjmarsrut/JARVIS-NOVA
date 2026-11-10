# -*- coding: utf-8 -*-
"""User-led creator account registration, with fixed official websites only.

JARVIS does not collect passwords, personal identity, SMS/2FA codes or
cookies. No account is created or claimed by this module. The user's
default browser handles registration in the service's own interface.
"""
from __future__ import annotations

from dataclasses import dataclass
import webbrowser


@dataclass(frozen=True)
class CreatorSite:
    key: str
    name: str
    signup_url: str
    guide: str
    help_url: str


SITES = (
    CreatorSite(
        "youtube", "YouTube",
        "https://www.youtube.com/channel_switcher",
        "Войди в свой Google-аккаунт (или создай его), затем выбери "
        "«Создать канал». Укажи название, аватар и @имя канала. "
        "Подтверди создание в YouTube.",
        "https://support.google.com/youtube/answer/1646861",
    ),
    CreatorSite(
        "tiktok", "TikTok",
        "https://www.tiktok.com/signup",
        "Выбери регистрацию по телефону или email. На сайте TikTok "
        "укажи возраст и придумай надёжный пароль. Самостоятельно введи "
        "код подтверждения и выбери имя профиля.",
        "https://support.tiktok.com/en/getting-started/setting-up-your-profile",
    ),
    CreatorSite(
        "instagram", "Instagram",
        "https://www.instagram.com/accounts/emailsignup/",
        "Зарегистрируйся на сайте Instagram через email, телефон или "
        "доступный способ входа. Введи код подтверждения, настрой "
        "имя профиля и включи двухфакторную защиту.",
        "https://help.instagram.com/",
    ),
)
SITE_BY_KEY = {site.key: site for site in SITES}


class CreatorSignupError(ValueError):
    pass


def is_creator_signup_request(message: str) -> bool:
    """An intent to open user-owned signup, never permission to create accounts."""
    if not isinstance(message,str) or not 5<=len(message)<=400:
        return False
    value=" ".join(message.casefold().replace("ё","е").split()).strip(" !.,")
    if not any(name in value for name in (
            "youtube", "ютуб", "ютюб", "tiktok", "тик ток", "тикток",
            "instagram", "инстаграм", "инста")):
        return False
    return any(phrase in value for phrase in (
        "создай аккаунт", "создать аккаунт", "сделай аккаунт",
        "зарегистрируй", "регистрация в ", "зарегистрироваться",
        "создай канал", "открой регистрацию",
    ))


def creator_site(key: str) -> CreatorSite:
    if not isinstance(key, str) or key not in SITE_BY_KEY:
        raise CreatorSignupError("Можно выбрать только YouTube, TikTok или Instagram.")
    return SITE_BY_KEY[key]


def open_creator_registration(key: str, *, confirmed: bool = False, browser=None) -> bool:
    """Open an exact allowlisted URL, only after an explicit user click."""
    if confirmed is not True:
        raise PermissionError("Открытие сайта регистрации требует разрешения.")
    site = creator_site(key)
    opener = browser or webbrowser.open_new_tab
    return bool(opener(site.signup_url))


def open_creator_help(key: str, *, confirmed: bool = False, browser=None) -> bool:
    if confirmed is not True:
        raise PermissionError("Открытие справки требует разрешения.")
    site = creator_site(key)
    opener = browser or webbrowser.open_new_tab
    return bool(opener(site.help_url))


def suggest_creator_handles(brand: str) -> tuple[str, ...]:
    """Ideas only: names are not checked for availability or reserved."""
    import re
    ascii_word = re.sub(r"[^a-z0-9_]", "", str(brand).casefold())[:20].strip("_")
    if len(ascii_word) < 3:
        raise CreatorSignupError(
            "Для латинского @имени введи от 3 букв или цифр латиницей.")
    return (ascii_word, (ascii_word + "_studio")[:30],
            (ascii_word + "_edits")[:30], (ascii_word + "_nova")[:30])
