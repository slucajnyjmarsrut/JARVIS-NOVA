# -*- coding: utf-8 -*-
"""Chat-first routing for *explicit* JARVIS NOVA requests.

Pure data-only intent classification: no file writes, networking, model-suggested
tool names, or implicit permissions. Only existing audited controller actions
may be selected; ambiguous questions remain ordinary conversation.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from code_languages import ALIASES


@dataclass(frozen=True)
class ChatIntent:
    kind: str
    value: str = ""


def _normal(text: str) -> str:
    text = re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip()
    text = text.strip(" .,!?;:…")
    if text.startswith("я хочу "):
        text = text[2:]
    elif text.startswith("я бы хотел "):
        text = "хочу " + text[len("я бы хотел "):]
    return re.sub(
        r"^(?:(?:эй|слушай|окей|привет)[ ,]+)?"
        r"(?:джарвис|жарвис|джервис|гарвис)[ ,:!-]+",
        "", text, count=1).strip(" .,!?;:…")


def _language(text: str) -> str | None:
    # Exclude ambiguous one-letter words and unrelated 'go', 'r', 'си'.
    ignored = {"c", "си", "go", "го", "r", "lua"}
    languages = {
        language for alias, language in ALIASES.items()
        if alias not in ignored and
        re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
    }
    # A site is typically HTML, but the user can name another language.
    if len(languages) > 1:
        return ""  # Ask, never choose one at random.
    if languages:
        return next(iter(languages))
    return "html" if re.search(r"\b(?:сайт|веб.?страниц[ауые]?|лендинг)\b", text) else "python"


def route_chat_request(text: str) -> ChatIntent | None:
    """Return an allowlisted intent or None: no side effects at this stage."""
    if not isinstance(text, str) or not 1 <= len(text) <= 1200:
        return None
    s = _normal(text)
    if not s or re.match(
        r"^(?:не |я не |не надо |не нужно |если |допустим |"
        r"расскажи |объясни |как |почему |зачем |когда |"
        r"можно ли |возможно ли |что будет |а если )", s):
        return None
    if s in {
        "что ты умеешь", "что ты можешь", "что умеешь", "помощь", "помоги разобраться",
        "покажи команды", "список команд", "что можно написать",
    }:
        return ChatIntent("help")
    if s in {"открой настройки", "покажи настройки", "хочу открыть настройки",
             "хочу настроить джарвис", "настройки джарвис", "настройки"}:
        return ChatIntent("settings")
    if s in {"проверь обновления", "проверить обновления", "обнови джарвис",
             "хочу обновить джарвис", "покажи обновления", "есть ли обновления",
             "хочу проверить обновления"}:
        return ChatIntent("updates")
    if s in {"скачай qwen", "установи qwen", "проверь qwen",
             "проверь локальную модель", "скачай локальную модель",
             "установи локальную модель", "хочу установить qwen"}:
        return ChatIntent("model")
    if s in {"останови скачивание qwen", "отмени загрузку qwen",
             "останови загрузку модели", "отмени скачивание модели"}:
        return ChatIntent("cancel_model")
    if s in {"разреши управлять компьютером", "хочу разрешить управление пк",
             "разреши управление пк"}:
        return ChatIntent("permission_control")
    if s in {"разреши видеть экран", "разреши чтение экрана",
             "хочу разрешить анализ экрана"}:
        return ChatIntent("permission_screen")
    if s in {"отзови все разрешения", "отключи доступ к компьютеру",
             "отключи все разрешения"}:
        return ChatIntent("revoke")
    if s in {"открой мини чат", "сверни джарвис", "спрячь главное окно"}:
        return ChatIntent("minimize")

    ai = re.fullmatch(
        r"(?:хочу использовать|включи|выбери|переключись на) "
        r"(qwen|квен|локальную qwen|freellm|фриллм|только команды)", s)
    if ai:
        names = {"qwen": "bundled", "квен": "bundled",
                 "локальную qwen": "bundled", "freellm": "freellm",
                 "фриллм": "freellm", "только команды": "none"}
        return ChatIntent("engine", names[ai.group(1)])

    if s in {"хочу показать скриншот", "хочу отправить скриншот",
             "открой разметку скриншота", "проверить скриншот",
             "хочу проверить скриншот"}:
        return ChatIntent("screenshot")
    if s in {"открой filmcraft", "хочу filmcraft", "запусти filmcraft"}:
        return ChatIntent("filmcraft")
    if s in {"открой видеостудию", "открой видео студию", "хочу видеостудию",
             "открой студию видео"}:
        return ChatIntent("studio")
    if s in {"хочу создать аккаунт youtube", "хочу зарегистрироваться в tiktok",
             "хочу создать аккаунт в инстаграм", "открой регистрацию аккаунтов"}:
        return ChatIntent("accounts")
    if (re.match(r"^(?:хочу |мне нужно |помоги )", s) and
        re.search(r"\b(?:опубликовать|выложить|публикацию)\b", s) and
        re.search(r"\b(?:видео|ролик|youtube|ютуб|тикток|tiktok)\b", s)) or s in {
            "открой подготовку публикации", "подготовь публикацию видео"}:
        return ChatIntent("publish")

    # Prefer the specialised multitrack editor to the generic timeline.
    if s in {"открой многодорожечный монтаж", "хочу многодорожечный монтаж",
             "открой редактор наложений"} or (
        re.match(r"^(?:хочу |мне нужно |помоги |добавь |наложи )", s) and
        re.search(r"(?:наложени|логотип|озвучк|музык.*на видео|"
                  r"картинк.*на видео|видео на видео)", s)):
        return ChatIntent("multitrack")
    if s in {"хочу эдит", "хочу сделать эдит", "сделай эдит",
             "хочу shorts", "хочу reels", "хочу tiktok монтаж",
             "открой редактор эдитов"}:
        return ChatIntent("edits")
    if (re.match(r"^(?:хочу |сделай |собери |смонтируй |сократи )",s)
            and re.search(r"\b15\s*(?:минут|мин)\b",s)
            and re.search(r"(?:длинн|двухчас|2\s*час|из .*видео|из .*клип|из .*запис)",s)):
        return ChatIntent("longform","900")
    if s in {"открой таймлайн", "открой видеоредактор",
             "хочу смонтировать видео", "хочу сделать монтаж",
             "хочу монтировать видео", "хочу монтаж видео",
             "хочу отредактировать видео", "хочу обрезать видео",
             "хочу смонтировать ролик", "хочу монтаж", "открой монтаж",
             "мне нужно смонтировать ролик", "начать монтаж"}:
        return ChatIntent("timeline")
    if s in {"хочу создать ролик", "хочу сделать ролик",
             "хочу создать видео", "хочу снять ролик",
             "хочу сделать видео", "хочу видео для ютуба"}:
        return ChatIntent("studio")

    if s in {"хочу поиграть", "хочу играть", "давай поиграем",
             "открой игровой режим"}:
        return ChatIntent("gaming")

    # Default language for an unspecified software project is Python.
    code_starts = (
        "хочу написать ", "хочу создать ", "хочу сделать ",
        "мне нужно написать ", "мне нужно создать ",
        "помоги написать ", "помоги создать ", "открой редактор кода",
        "открой программирование", "хочу программировать",
        "хочу писать код",
    )
    if s in {"открой программирование", "открой редактор кода",
             "хочу программировать", "хочу писать код"} or (
        s.startswith(code_starts) and re.search(
            r"\b(?:программ\w*|код\w*|сайт|лендинг|скрипт\w*|"
            r"приложени\w*|бот\w*|игру|игра|проект\w*|"
            r"плагин\w*|мод\w*|модел\w*|карт\w*|мир|сервер\w*|api)\b", s)):
        return ChatIntent("code", _language(s))

    # Allow natural 'I want to open X' for already vetted desktop planner.
    # The controller still calls parse_local+validate_plan, never a shell.
    match = re.fullmatch(
        r"(?:хочу |мне нужно |пожалуйста )?(?:открыть|запустить) (.{1,90})", s)
    if match:
        return ChatIntent("open_desktop", match.group(1))
    match = re.fullmatch(r"хочу (?:открыть|запустить) (.{1,90})", s)
    if match:
        return ChatIntent("open_desktop", match.group(1))
    return None
